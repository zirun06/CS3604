"""Exercise batch boundaries, canonical conventions and transactional validation."""

from collections import Counter
from unittest.mock import Mock

import pytest

from infrastructure.pipeline import backend_apis
from infrastructure.shared.agent import design_batches
from infrastructure.shared.agent.tasks import StageIncomplete
from infrastructure.stages.requirements.batching import DesignPlan
from infrastructure.utils.files import read_artifact, save_json


def leaf(identity, name="Shared note", description="", references=()):
    return {"id": identity, "name": name, "description": description,
        "scenarios": [{"id": "scenario-" + identity, "steps": [
            {"id": "step-" + identity, "references": list(references)}]}]}


def module(identity, *leaves):
    return {"id": identity, "children": list(leaves)}


def test_plan_splits_large_modules_and_keeps_shared_dependencies_and_source_ownership():
    first = leaf("first", description="x" * 1400, references=[r"\ref[requirement](owner)"])
    second = leaf("second")
    owner = leaf("owner")
    root = module("root", module("feature", first, second), module("common", owner))
    plan = DesignPlan(root, max_chars=1000)
    assert [batch.leaves for batch in plan.batches] == [("second",), ("owner",), ("first",)]
    assert plan.dependencies["first"] == ["owner"]
    assert plan.evidence()["shared_symbol_candidates"]["note"] == ["first", "second", "owner"]
    assert plan.describe(plan.batches[-1])["oversize_single_leaf"]
    assert plan.leaf_context["first"]["source"]["description"] == first["description"]
    coverage = plan.audit(plan.batches)
    assert Counter(row["id"] for row in coverage["steps"]) == Counter(["step-first", "step-second", "step-owner"])
    assert {row["id"]: row["batch"] for row in coverage["scenarios"]}["scenario-first"] == plan.batches[-1].id
    with pytest.raises(ValueError, match="coverage"):
        plan.audit([*plan.batches, plan.batches[0]])


def test_large_assembled_request_splits_before_model_dispatch(tmp_path, monkeypatch):
    root = module("root", module("feature", leaf("left"), leaf("right")))
    batches = design_batches.DesignBatches(tmp_path, "02_example", Mock(), root)
    monkeypatch.setattr(design_batches, "MAX_REQUEST_CHARS", 1)
    model = Mock()

    def generate(_instructions, request):
        assert len(request["order"]) == 1
        return {"requirements": {request["order"][0]: {}}}

    model.generate_json.side_effect = generate

    def process(batch):
        batches.propose(batch, model, "", dict.fromkeys(batch.leaves, {}), lambda value: value, 1)
        return True

    batches.run(process)
    report = read_artifact(tmp_path, "design_batches_02.json")
    assert report["attempts"][0]["split_reason"] == "input_size"
    assert model.generate_json.call_count == 2


def backend_fixture(tmp_path, root, obligations):
    save_json(tmp_path / "requirements.json", root)
    save_json(tmp_path / "db_schema.json", {"entities": {"Note": {"fields": {"id": {}}}}, "requirements": {}})
    empty = {"read": [], "write": []}
    save_json(tmp_path / "db_obligations.json", {
        "requirements": {root["id"]: empty, **{node["id"]: empty for node in root["children"]}, **obligations},
        "steps": {"step-" + rid: record for rid, record in obligations.items()}})


def test_backend_batch_rejects_missing_leaf_coverage_without_publishing(tmp_path, monkeypatch):
    root = module("root", module("feature", leaf("left"), leaf("right")))
    backend_fixture(tmp_path, root, {"left": {"read": [], "write": []}, "right": {"read": ["Note.id"], "write": []}})
    model = Mock(max_output_tokens=12288)
    model.generate_records.return_value = {"apis": {}, "modules": {}, "requirements": {
        rid: {"api_ids": [], "module_ids": []} for rid in ("left", "right")}}
    monkeypatch.setattr(backend_apis, "TextModel", lambda **_: model)

    with pytest.raises(StageIncomplete) as error:
        backend_apis.design_backend_apis(tmp_path, max_attempts=1)
    assert "right" in error.value.failures[0]["error"]
    assert "Note.id" in error.value.failures[0]["error"]
    assert "left" not in read_artifact(tmp_path, "backend_apis.json")["requirements"]


def test_backend_reuses_canonical_decisions_across_modules(tmp_path, monkeypatch):
    root = module("root", module("account", leaf("left")), module("preferences", leaf("right")))
    empty = {"read": [], "write": []}
    backend_fixture(tmp_path, root, {"left": empty, "right": empty})
    model = Mock(max_output_tokens=12288)
    requests = []

    def generate(_instructions, request):
        requests.append(request)
        rid = request["order"][0]
        assert "session" in request["shared_catalog"]["policies"]
        decisions = request["shared_catalog"]["shared_conventions"]
        if rid == "left":
            assert not decisions
            choice = "Use session cookie sid"
        else:
            assert decisions["session-cookie"]["description"] == "Use session cookie sid"
            assert "right" in request["shared_catalog"]["source_symbols"]["note"]
            choice = "Use session cookie different" if "correction" not in request else "Use session cookie sid"
        return {"apis": {}, "modules": {}, "requirements": {
            rid: {"api_ids": [], "module_ids": [], "conventions": {"session-cookie": choice}}}}

    model.generate_records.side_effect = generate
    monkeypatch.setattr(backend_apis, "TextModel", lambda **_: model)
    backend_apis.design_backend_apis(tmp_path, max_attempts=2)
    assert [req["order"] for req in requests] == [["left"], ["right"], ["right"]]
    assert "contradicts shared convention" in requests[-1]["correction"]["error"]
    assert read_artifact(tmp_path, "shared_conventions.json")["session-cookie"]["requirements"] == ["left", "right"]
