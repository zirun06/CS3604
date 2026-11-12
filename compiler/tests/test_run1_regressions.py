"""Regressions for partial handoffs, request limits and concurrent design."""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Event
from unittest.mock import Mock

import httpx
import pytest

from infrastructure.pipeline import database, db_obligations
from infrastructure.shared.agent.implementation_batches import ImplementationBatches
from infrastructure.shared.agent.tasks import StageIncomplete
from infrastructure.shared.models.text import ModelRequestFailed, TextModel, reasoning_scope
from infrastructure.utils.budget import BudgetExhausted, RunBudget, budget_scope, wait_for_reservations
from infrastructure.utils.files import save_json
from infrastructure.utils.presentation.model_io import DeadlineStream
from test_budget_boundaries import USAGE, answer, offline_model


def test_weighted_deadlines_reserve_later_stages_and_carry_time_forward():
    clock = Mock(return_value=0)
    stages = [f"{i:02d}_pass" for i in range(11)]
    budget = RunBudget({"seconds": 2400}, clock=clock, stages=len(stages))
    budget.allocate_stages(stages)
    assert budget.stage_deadlines["02"] == pytest.approx(670.6)
    assert budget.stage_deadlines["03"] == pytest.approx(958)
    assert budget.stage_deadlines["10"] == pytest.approx(2395)
    clock.return_value = 690
    budget.select_stage(8, "02")
    with pytest.raises(BudgetExhausted, match=r"seconds \(stage\)"):
        budget.check_time()
    budget.select_stage(7, "03")
    assert budget.check_time() == pytest.approx(268)
    assert budget.remaining_time(run_only=True) == 1705
    subset = RunBudget.from_settings({"COMPILER_BUDGET_SECONDS": "100",
        "COMPILER_STAGE_WEIGHTS": '{"02":1,"03":3}', "COMPILER_STAGE_OUTPUT_CAPS": '{"03":123}',
        "COMPILER_OBLIGATION_WORKERS": "1"}, stages=2)
    subset.allocate_stages(stages[2:4])
    subset.select_stage(0, "03")
    assert subset.stage_deadlines == {"02": 23.75, "03": 95}
    assert subset.output_limit(456) == 123 and subset.design_workers == 1


def test_socket_reads_use_absolute_deadline_without_dividing_first_byte_time():
    clock = Mock(return_value=0)
    budget = RunBudget({"seconds": 60}, clock=clock)
    stream = Mock()
    wrapped = DeadlineStream(stream)
    with budget_scope(budget):
        wrapped.read(10, timeout=600)
        stream.read.assert_called_with(10, timeout=55)
        clock.return_value = 40
        wrapped.read(10, timeout=55)
        stream.read.assert_called_with(10, timeout=15)
        clock.return_value = 56
        with pytest.raises(BudgetExhausted, match="seconds"):
            wrapped.read(10, timeout=55)
    assert stream.read.call_count == 2


@pytest.mark.parametrize("error,unknown", [("unsupported", False), ("connect", False), ("read", True)])
def test_http_accounting_caps_the_wire_and_refunds_proven_preflight_errors(error, unknown):
    sent = []

    def transport(request):
        sent.append(json.loads(request.content))
        if len(sent) == 2:
            return answer({}, usage=USAGE)
        if error == "unsupported":
            return httpx.Response(422, json={"error": {"message": "Unsupported parameter max_completion_tokens"}})
        if error == "connect":
            raise httpx.ConnectTimeout("before sending", request=request)
        raise httpx.ReadTimeout("may have been billed", request=request)

    model = offline_model(TextModel, transport, retries=1)
    model.max_output_tokens = 24000
    budget = RunBudget({"tokens": 20000, "seconds": 20})
    budget.select_stage(0, "03")
    try:
        with budget_scope(budget):
            assert model.generate_json("Reply with JSON", {"text": "fixture"}) == {}
    finally:
        model.client.close()
    assert [item.get("max_completion_tokens", item.get("max_tokens")) for item in sent] == [6144, 6144]
    state = budget.snapshot()
    assert state["used"]["calls"] == 1 and state["used"]["http_attempts"] == 2
    charged = state["unreported_tokens_charged"]
    assert (charged >= 6144 if unknown else charged == 0)
    assert state["used"]["tokens"] == 20 + charged and state["reserved_tokens"] == 0


def test_deepseek_defaults_disable_initial_reasoning_and_enable_repair(monkeypatch):
    from infrastructure.shared.models import text
    monkeypatch.setattr(text, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("MODEL_REASONING", raising=False)
    monkeypatch.delenv("MODEL_REPAIR_REASONING", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://fixture.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "offline")
    model = TextModel(model_name="deepseek-fixture")
    model.client.close()
    wire = []

    def transport(request):
        wire.append(json.loads(request.content))
        return answer({}, usage=USAGE)

    model.client = offline_model(TextModel, transport).client
    try:
        model.generate_json("Propose", {})
        with reasoning_scope(True):
            model.generate_json("Correct", {})
        model.generate_json("Propose again", {})
    finally:
        model.client.close()
    assert [row["thinking"]["type"] for row in wire] == ["disabled", "enabled", "disabled"]
    assert wire[1]["reasoning_effort"] == "low"


def test_concurrent_reservations_wait_for_reported_usage_without_overbooking():
    budget = RunBudget({"tokens": 100, "seconds": 10})
    holding, ready = Event(), Event()
    sent = []

    def first():
        with budget_scope(budget):
            attempt = budget.reserve_attempt(10, 70)
            budget.dispatch(attempt)
            holding.set()
            assert ready.wait(5)
            budget.settle(attempt, 10)

    def second():
        assert holding.wait(5)
        with budget_scope(budget), wait_for_reservations():
            ready.set()
            attempt = budget.reserve_attempt(10, 70)
            budget.dispatch(attempt)
            sent.append(attempt.tokens)
            state = budget.snapshot()
            assert state["used"]["tokens"] + state["reserved_tokens"] <= 100
            budget.settle(attempt, 20)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_worker, second_worker = pool.submit(first), pool.submit(second)
        first_worker.result()
        second_worker.result()
    assert sent == [80] and budget.snapshot()["used"]["tokens"] == 30


def test_stage03_parallel_keeps_serial_artifact_when_one_batch_fails(tmp_path, monkeypatch):
    leaves = ("R-A", "R-B", "R-C")
    root = {"id": "root", "name": "Fixture", "children": [
        {"id": rid, "name": rid, "description": {"text": "Fixture"}, "scenarios": [
            {"id": "C-" + rid, "name": rid, "steps": [{"id": "S-" + rid,
                "Given": "Start", "When": "Act", "Then": "Finish"}]}]} for rid in leaves]}
    outputs = []
    for workers in (1, 3):
        arc = tmp_path / str(workers) / ".arc"
        arc.mkdir(parents=True)
        save_json(arc / "requirements.json", root)
        save_json(arc / "db_schema.json", {"entities": {}, "requirements": {rid: [] for rid in leaves}})
        budget = RunBudget({"tokens": 100, "calls": 3, "http_attempts": 3, "seconds": 20})
        budget.design_workers = workers
        barrier = Barrier(workers)

        def generate(instructions, payload):
            rid, = payload["order"]
            assert "Requirements and steps are siblings" in instructions
            assert "Each leaf's entry is its own complete result" not in instructions
            assert payload["requirements"][rid]["expected_step_ids"] == ["S-" + rid]
            budget.start_call()
            attempt = budget.reserve_attempt(10, 20)
            budget.dispatch(attempt)
            barrier.wait(timeout=5)
            state = budget.snapshot()
            assert state["used"]["tokens"] + state["reserved_tokens"] <= 100
            budget.settle(attempt, 15)
            effects = {"read": [], "write": []}
            result = {"requirements": {rid: effects}}
            if rid != leaves[1]:
                result["steps"] = {"S-" + rid: effects}
            return result

        monkeypatch.setattr(db_obligations, "TextModel", lambda **_: Mock(generate_json=generate))
        with budget_scope(budget), pytest.raises(StageIncomplete):
            db_obligations.infer_db_obligations(arc, max_attempts=1)
        state = budget.snapshot()
        assert state["used"] == {"calls": 3, "http_attempts": 3, "tokens": 45}
        assert state["reserved_tokens"] == 0
        outputs.append(json.loads((arc / "db_obligations.json").read_text(encoding="utf-8")))
    assert outputs[0] == outputs[1]
    assert set(outputs[0]["requirements"]) == {"root", leaves[0], leaves[2]}
    assert set(outputs[0]["unavailable"]) == {leaves[1]}


def test_timed_out_seed_batch_rolls_back_and_keeps_other_leaf(tmp_path):
    arc = tmp_path / ".arc"
    arc.mkdir()
    leaves = ("good", "failed")
    save_json(arc / "requirements.json", {"id": "root", "name": "Fixture", "children": [
        {"id": rid, "name": rid} for rid in leaves]})
    batches = ImplementationBatches(arc, "04", Mock(), phase="seed").register(
        {rid: {} for rid in leaves}, {rid: [rid] for rid in leaves}, {rid: ["shared-table"] for rid in leaves})
    seed = tmp_path / "backend/src/db/seeds/startup.sql"
    seed.parent.mkdir(parents=True)

    def process(batch, _entry):
        if "failed" in batch.units:
            seed.write_text("unaccepted change", encoding="utf-8")
            raise ModelRequestFailed("Model request timed out")
        assert not seed.exists()
        seed.write_text("accepted change", encoding="utf-8")
        return {"good": {"rows": []}}

    report = batches.run(process)
    assert report["good"]["status"] == "GREEN"
    assert report["failed"]["status"] == "FAILED"
    assert report["failed"]["error_type"] == "ModelRequestFailed"
    assert seed.read_text(encoding="utf-8") == "accepted change"
    assert list((arc / "failures").glob("*/failure.json"))


def test_stage04_publishes_only_tables_with_accepted_foreign_key_targets(tmp_path, monkeypatch):
    arc = tmp_path / ".arc"
    arc.mkdir()
    for name in ("backend/package.json", "backend/src/db/client.ts", "backend/src/db/initialize.ts"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    references = {"parent": None, "dependent": "parent.id", "independent": None}
    save_json(arc / "requirements.json", {"id": "R", "name": "Fixture"})
    save_json(arc / "db_schema.json", {"requirements": {"R": [f"{name}.id" for name in references]},
        "entities": {name: {"fields": {"id": {"references": reference}}}
            for name, reference in references.items()}})

    def generate(request, _tools):
        for name, entry in request["tables"].items():
            if name == "parent":
                continue
            path = tmp_path / entry["output_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            reference = " REFERENCES parent(id)" if name == "dependent" else ""
            path.write_text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY{reference});", encoding="utf-8")

    verify = Mock(return_value={"status": "GREEN"})
    seeds = Mock(return_value={})
    monkeypatch.setattr(database, "DatabaseImplementationAgent", lambda **_: Mock(run=generate))
    monkeypatch.setattr(database, "implement_startup_data", seeds)
    monkeypatch.setattr(database, "verify_database_runtime", verify)
    report = database.implement_db(arc)
    assert report["status"] == "COMPLETED_WITH_FAILURES"
    assert set(verify.call_args.args[1]["entities"]) == {"independent"}
    assert seeds.call_args.args[3] == ["independent"]
    blocked, = [row for row in report["failures"] if row.get("table") == "dependent"]
    assert blocked["tables"] == ["parent"]
    initializer = (tmp_path / "backend/src/db/initialize.ts").read_text(encoding="utf-8")
    assert '"independent.sql"' in initializer and '"dependent.sql"' not in initializer


def test_stage04_rejects_schema_placeholder_without_verifying_runtime(tmp_path, monkeypatch):
    arc = tmp_path / ".arc"
    save_json(arc / "db_schema.json", {"entities": {}, "requirements": {}})
    verify = Mock()
    monkeypatch.setattr(database, "verify_database_runtime", verify)
    assert database.implement_db(arc)["status"] == "MISSING_PREREQUISITES"
    verify.assert_not_called()
