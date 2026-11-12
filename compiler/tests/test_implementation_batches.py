"""Verify recovery, source-grounded rows, and grouped implementation accounting."""

import json
from unittest.mock import Mock

import pytest

from infrastructure.pipeline.database import TableCheck
from infrastructure.shared.agent.implementation_batches import ImplementationBatches
from infrastructure.shared.models.text import ModelOutputTruncated
from infrastructure.stages.database.implementation import prerequisite_evidence, validate_seed_row
from infrastructure.utils.files import read_artifact, save_json, save_text
from infrastructure.utils.presentation.events import (
    begin_run, begin_stage, finish_stage, finish_run, model_metric, test_authoring as authoring,
    task_scope, validation_event,
)


def workspace(tmp_path):
    arc = tmp_path / ".arc"
    save_json(arc / "requirements.json", {"id": "root", "children": [
        {"id": "one", "scenarios": [{"id": "s", "steps": [{"id": "x"}]}]}, {"id": "two"}]})
    return arc


def test_partial_batch_retains_passing_unit_and_rolls_back_failed_retry(tmp_path):
    arc = workspace(tmp_path)
    batches = ImplementationBatches(arc, "08", Mock()).register(
        {"page-one": {}, "page-two": {}}, {"page-one": ["one"], "page-two": ["two"]},
        {"page-one": {"layout"}, "page-two": {"layout"}})
    app = tmp_path / "frontend/src/App.tsx"
    save_text(app, "original")

    def process(batch, entry):
        if len(batch.units) == 2:
            save_text(app, "working page-one")
            entry["rejected_checks"] = {"page-two": {"error": "missing page"}}
            return {"page-one": {"checks": "verified"}}
        assert batch.units == ("page-two",) and batches.regression(batch) == ["page-one"]
        assert app.read_text(encoding="utf-8") == "working page-one"
        save_text(app, "bad edit of both pages")
        raise ValueError("regression on page-one")

    results = batches.run(process)
    assert results["page-one"]["status"] == "GREEN"
    assert results["page-two"]["status"] == "FAILED"
    assert app.read_text(encoding="utf-8") == "working page-one"
    assert (tmp_path / results["page-two"]["archive"] / "files/frontend/src/App.tsx").read_text(
        encoding="utf-8") == "bad edit of both pages"
    report = read_artifact(arc, "implementation_batches_08.json")
    assert report["attempts"][0]["split_reason"] == "partial_acceptance"
    assert report["coverage"]["steps"][0]["batches"] == ["08-main-001"]


def test_truncated_batch_rolls_back_then_splits_without_replaying_passing_child(tmp_path):
    batches = ImplementationBatches(workspace(tmp_path), "06", Mock()).register(
        {"api-a": {}, "api-b": {}}, {"api-a": ["one"], "api-b": ["two"]},
        {"api-a": {"feature"}, "api-b": {"feature"}})
    app = tmp_path / "backend/src/api/register.ts"
    save_text(app, "baseline")

    def process(batch, _):
        if len(batch.units) > 1:
            save_text(app, "unfinished")
            raise ModelOutputTruncated("output length")
        if batch.units == ("api-a",):
            assert app.read_text(encoding="utf-8") == "baseline"
            save_text(app, "api a")
        else:
            assert app.read_text(encoding="utf-8") == "api a"
            assert batches.regression(batch) == ["api-a"]
        return {batch.units[0]: {}}

    assert set(batches.run(process)) == {"api-a", "api-b"}
    assert [row["status"] for row in batches.records] == ["FAILED", "GREEN", "GREEN"]
    assert batches.records[0]["split_reason"] == "ModelOutputTruncated"


def test_seed_rows_require_concrete_preexisting_source_and_canonical_insert():
    requirement = {"description": "Startup data: Note 6 exists.\n\nWhen saving, create Note 3."}
    steps = [{"id": "step1", "Given": "Note 7 exists", "When": "Create Note 8", "Then": "Note 8 is visible"},
        {"id": "step2", "Given": "There are no notes", "When": "", "Then": ""}]
    evidence = prerequisite_evidence(requirement, steps)
    sql = "INSERT INTO Note (id) SELECT 7 WHERE NOT EXISTS (SELECT 1 FROM Note WHERE id = 7);"
    row = {"table": "Note", "sql": sql, "evidence": {"source": "step1", "quote": "Note 7 exists", "identity": "7"}}
    assert validate_seed_row(row, evidence, ["Note"]) == sql
    assert set(evidence) == {"step1", "description:0"}
    with pytest.raises(ValueError, match="prerequisite evidence"):
        validate_seed_row({**row, "evidence": {"source": "step1", "quote": "Create Note 8", "identity": "8"}},
            evidence, ["Note"])
    with pytest.raises(ValueError, match="single|one idempotent"):
        validate_seed_row({**row, "sql": sql + " DELETE FROM Note;"}, evidence, ["Note"])
    assert TableCheck().run("Note", "CREATE TABLE Note (id INT); INSERT INTO Note VALUES (1);", ["id"])["returncode"]


def test_group_authoring_cost_is_charged_once_and_serialized(tmp_path):
    workspace(tmp_path)
    paths = ("backend/tests/one.test.ts", "backend/tests/two.test.ts")
    token, _ = begin_run(tmp_path, tmp_path, None, {})
    try:
        begin_stage("06_implement_backend_tdd")
        with task_scope("06-main-001", ["one", "two"], batch_id="06-main-001"):
            with authoring(paths, "generation"):
                model_metric("logical_calls")
            validation_event("http_test", 0.5, "passed", source="model", files=paths)
        finish_stage("06_implement_backend_tdd", "GREEN")
    finally:
        finish_run(token, "GREEN")
    rows = [json.loads(row) for row in (tmp_path / "compilation_events.jsonl").read_text(encoding="utf-8").splitlines()]
    checked, = [row for row in rows if row.get("event") == "validation"]
    assert checked["batch_id"] == "06-main-001" and checked["requirement_ids"] == ["one", "two"]
    assert checked["test_model_effort"]["generation"]["logical_calls"] == 1
    costs = read_artifact(tmp_path / ".arc", "test_model_effort.json")
    assert list(costs["group_files"].values()) == [list(paths)]
