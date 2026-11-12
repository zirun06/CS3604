"""Exercise the real model and process boundaries with no network transport."""

from unittest.mock import Mock, patch
import json
import subprocess

import httpx
from PIL import Image
import pytest

from infrastructure.pipeline import requirements
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.models.vision import VisualModel
from infrastructure.utils import processes
from infrastructure.utils.budget import BudgetExhausted, RunBudget, budget_scope
from infrastructure.utils.presentation import model_io
from infrastructure.utils.presentation.events import (
    begin_run, begin_stage, finish_run, finish_stage, test_authoring as authoring, validation,
)


def answer(payload=None, *, usage=None, finish="stop"):
    return httpx.Response(200, json={"id": "fixture", "object": "chat.completion",
        "created": 0, "model": "fixture-model", "choices": [{"index": 0,
            "finish_reason": finish, "message": {"role": "assistant",
                "content": json.dumps(payload) if payload is not None else "{}"}}], "usage": usage})


USAGE = {"prompt_tokens": 11, "completion_tokens": 9, "total_tokens": 20,
    "prompt_tokens_details": {"cached_tokens": 4},
    "completion_tokens_details": {"reasoning_tokens": 3}}


def offline_model(kind, handler, retries=0):
    model = kind.__new__(kind)
    transport = httpx.Client(transport=httpx.MockTransport(handler),
        event_hooks={"request": [model_io._http_request], "response": [model_io._http_response]})
    model.client = model_io.BudgetedOpenAI(api_key="fixture", base_url="https://fixture.invalid/v1",
        http_client=transport, max_retries=retries)
    model.name = "fixture-model"
    model.reasoning = "provider"
    model._token_parameter = "max_completion_tokens"
    model.max_output_tokens = 40
    return model


@pytest.fixture
def run(tmp_path):
    output = tmp_path / "app"
    token, _ = begin_run(output, tmp_path, None, {})
    stage = begin_stage("test_stage")
    yield output
    finish_stage(stage, "GREEN")
    finish_run(token, "GREEN")


def events(output, kind):
    return [event for line in (output / "compilation_events.jsonl").read_text(encoding="utf-8").splitlines()
        if (event := json.loads(line))["event"] == kind]


def test_native_request_counts_sdk_and_compatibility_retries(run):
    wire = []
    def handler(request):
        wire.append(json.loads(request.content))
        if len(wire) == 1:
            return httpx.Response(500, headers={"retry-after-ms": "1"}, json={"error": {"message": "retry"}})
        if len(wire) == 2:
            return httpx.Response(400, json={"error": {"message": "Unsupported parameter max_completion_tokens"}})
        return answer({}, usage=USAGE)
    budget = RunBudget({"calls": 1, "http_attempts": 3, "tokens": 10000, "seconds": 10})
    model = offline_model(TextModel, handler, retries=1)
    tool = {"type": "function", "function": {"name": "record", "parameters": {"type": "object"}}}
    with budget_scope(budget):
        model._request(model=model.name, messages=[{"role": "user", "content": "fixture"}], tools=[tool])
        with pytest.raises(BudgetExhausted, match="calls"):
            model._request(model=model.name, messages=[])
    model.client.close()
    assert len(wire) == 3 and "max_tokens" in wire[-1] and wire[-1]["tools"] == [tool]
    state = budget.snapshot()
    assert state["used"]["calls"] == 1 and state["used"]["http_attempts"] == 3
    assert state["unreported_tokens_charged"] > 0
    assert state["used"]["tokens"] == state["unreported_tokens_charged"] + 20
    assert state["reserved_tokens"] == 0
    starts = events(run, "http_attempt_started")
    assert len(starts) == 3 and len({item["logical_call_id"] for item in starts}) == 1


def test_sdk_retry_is_denied_before_second_transport_attempt(run):
    wire = Mock(return_value=httpx.Response(500, headers={"retry-after-ms": "1"},
        json={"error": {"message": "retry"}}))
    model = offline_model(TextModel, wire, retries=2)
    budget = RunBudget({"http_attempts": 1})
    with budget_scope(budget), pytest.raises(BudgetExhausted, match="http_attempts"):
        model._request(model=model.name, messages=[])
    model.client.close()
    assert wire.call_count == 1 and budget.snapshot()["reserved_http_attempts"] == 0


def test_truncation_and_missing_usage_are_visible(run):
    model = offline_model(TextModel, lambda _: answer(finish="length"))
    budget = RunBudget({"tokens": 4096})
    with budget_scope(budget), pytest.raises(ValueError, match="truncated"):
        model.generate_json("Reply with JSON", {})
    model.client.close()
    event, = events(run, "model_finished")
    assert event["status"] == "INCOMPLETE_RESPONSE" and event["usage"]["total_tokens"] is None
    assert budget.snapshot()["used"]["tokens"] == budget.snapshot()["unreported_tokens_charged"]


def test_each_context_query_and_file_read_consumes_a_logical_call(run):
    with budget_scope(RunBudget({"calls": 2})):
        requests = [answer({"context_request": {"kind": "schema", "ids": [key]}}, usage=USAGE)
            for key in ("A", "B")]
        wire = Mock(side_effect=requests)
        model = offline_model(TextModel, wire)
        with pytest.raises(BudgetExhausted, match="calls"):
            propose_json(model, "JSON", {}, lambda value: value, Mock(), "query", 4,
                ContextIndex({"schema": {"A": {}, "B": {}}}))
        model.client.close()
        assert wire.call_count == 2

    for key in ("first", "second"):
        path = run / f"backend/src/{key}.ts"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"export const result = 1;\n")
    requests = [answer({"tool_calls": [{"tool": "read_file", "path": f"backend/src/{key}.ts"}]}, usage=USAGE)
        for key in ("first", "second")]
    wire = Mock(side_effect=requests)
    model = offline_model(TextModel, wire)
    workspace = FileTools(run, ["backend"], stage="backend")
    with budget_scope(RunBudget({"calls": 2})), pytest.raises(BudgetExhausted, match="calls"):
        run_file_agent(model, "JSON", {}, workspace, Mock(), 4, Mock(), "read")
    model.client.close()
    assert wire.call_count == 2


def test_visual_reservation_and_context_survive_worker_dispatch(run, tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "requirements.yaml").write_bytes(b"""id: ROOT
description:
  text: View two references.
  image:
    - {id: A, reference: a.png}
    - {id: B, reference: b.png}
""")
    for name in ("a.png", "b.png"):
        Image.new("RGB", (4, 4), "white").save(source / name)
    wire = Mock(return_value=answer({"layout": "empty", "elements": [], "style": "light"}, usage=USAGE))
    model = offline_model(VisualModel, wire)
    budget = RunBudget({"calls": 1, "http_attempts": 1, "tokens": 12000})
    with budget_scope(budget), patch.object(requirements, "VisualModel", return_value=model):
        with pytest.raises(BudgetExhausted):
            requirements.explore_requirement(source, run / ".arc")
    assert wire.call_count == 1
    event, = events(run, "http_attempt_started")
    assert event["batch_id"] == "visual-1" and event["requirement_ids"] == ["ROOT"]
    visual = json.loads((run / ".arc/visual_analysis.json").read_text(encoding="utf-8"))
    assert set(visual) == {"a.png"} and budget.snapshot()["reserved_tokens"] == 0


def test_verification_effort_and_result_are_observed_without_changing_result(run):
    path = "backend/tests/sample.test.ts"
    class Checker:
        @validation("http_test", source="model", selected_files=True)
        def check(self, files):
            return {"returncode": 0, "pass": 1}
    model = offline_model(TextModel, lambda _: answer({}, usage=USAGE))
    with budget_scope(RunBudget({})):
        for phase in ("generation", "review"):
            with authoring(path, phase):
                model.generate_json("Reply with JSON", {})
        assert Checker().check([path]) == {"returncode": 0, "pass": 1}
    model.client.close()
    result, = events(run, "validation")
    assert result["result"] == "passed" and result["test_source"] == "model"
    assert {phase: (entry["logical_calls"], entry["total_tokens"])
        for phase, entry in result["test_model_effort"].items()} == {"generation": (1, 20), "review": (1, 20)}


def test_subprocess_deadline_limits_wait_and_prevents_start(run):
    now = [0.0]
    budget = RunBudget({"seconds": 10}, clock=lambda: now[0])
    process = Mock()
    process.communicate.side_effect = [subprocess.TimeoutExpired("fixture", 9), ("", "")]
    with patch.object(processes, "start_process", return_value=process) as start, \
            patch.object(processes, "stop_process") as stop, budget_scope(budget):
        with pytest.raises(BudgetExhausted) as expired:
            processes.capture_process(["fixture"], cwd=run, timeout=600)
        assert expired.value.process_started and process.communicate.call_args_list[0].kwargs["timeout"] == 9
        stop.assert_called_once_with(process)
        now[0] = 10
        with pytest.raises(BudgetExhausted):
            processes.capture_process(["fixture"], cwd=run, timeout=600)
        assert start.call_count == 1


def test_sdk_backoff_obeys_run_deadline(run):
    now = [0.0]
    def reply(_):
        now[0] = 8.8
        return httpx.Response(500, headers={"retry-after-ms": "1000"}, json={"error": {"message": "retry"}})
    wire = Mock(side_effect=reply)
    model = offline_model(TextModel, wire, retries=2)
    with budget_scope(RunBudget({"seconds": 10}, clock=lambda: now[0])), \
            pytest.raises(BudgetExhausted, match="seconds"):
        model._request(model=model.name, messages=[])
    model.client.close()
    assert wire.call_count == 1


def test_reported_usage_overrun_cannot_be_reported_as_success(run):
    model = offline_model(TextModel, lambda _: answer({}, usage={
        "prompt_tokens": 5000, "completion_tokens": 1, "total_tokens": 5001}))
    budget = RunBudget({"tokens": 4096})
    with budget_scope(budget), pytest.raises(BudgetExhausted, match="tokens"):
        model._request(model=model.name, messages=[{"role": "user", "content": "fixture"}])
    model.client.close()
    assert budget.snapshot()["used"]["tokens"] == 5001
