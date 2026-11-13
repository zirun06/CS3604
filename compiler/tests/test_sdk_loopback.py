"""Exercise the installed SDK and native transport against a local HTTP service."""

from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from threading import Event, Thread
from time import sleep

import pytest

from infrastructure.shared.models.text import TextModel
from infrastructure.shared.models.vision import VisualModel
from infrastructure.utils.budget import BudgetExhausted, ModelCircuitOpen, RunBudget, budget_scope
from infrastructure.utils.presentation import model_io


USAGE = {"prompt_tokens": 11, "completion_tokens": 9, "total_tokens": 20}
RESULT = {"ok": True}


@pytest.fixture
def service():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.server.requests.append((self.path, request))
            status, delay, trickle = self.server.mode
            reply = {"error": {"message": "Fixture rejected the request"}} if status != 200 else {
                "id": "local-fixture", "object": "chat.completion", "created": 0, "model": "fixture",
                "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(RESULT)}}], "usage": USAGE}
            if status == 200 and self.server.reply is not None:
                reply = self.server.reply(request, reply)
            body = json.dumps(reply).encode("utf-8")
            sleep(delay)
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if trickle:
                    self.wfile.write(body[:1])
                    self.wfile.flush()
                    sleep(trickle)
                    body = body[1:]
                self.server.finished.set()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *args):
            pass

    class TestServer(ThreadingHTTPServer):
        daemon_threads = False

    with TestServer(("127.0.0.1", 0), Handler) as server:
        server.reply = None
        server.mode = (200, 0, 0)
        server.requests = []
        server.finished = Event()
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        worker.start()
        try:
            yield server
        finally:
            server.shutdown()
            worker.join()


def endpoint(server):
    return f"http://127.0.0.1:{server.server_address[1]}/v1"


def make_model(monkeypatch, kind, url):
    monkeypatch.setenv("OPENAI_API_KEY", "loopback-fixture")
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    monkeypatch.setenv("MODEL", "fixture")
    monkeypatch.setenv("VISUAL_MODEL", "fixture")
    monkeypatch.setenv("MODEL_REASONING", "provider")
    monkeypatch.setenv("VISUAL_REASONING", "provider")
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "128")
    model = kind()
    model.client.max_retries = 0
    return model


def generate(model):
    payload = {"image_url": "data:image/png;base64,AA=="} if isinstance(model, VisualModel) else {}
    return model.generate_json("Return a JSON object.", payload)


@pytest.mark.parametrize("kind", [TextModel, VisualModel])
@pytest.mark.parametrize("scenario,mode,seconds", [
    ("success", (200, 0, 0), 10),
    ("slow", (200, 0.5, 0), 1.6),
    ("deadline", (200, 0.6, 1.2), 1.6),
    ("bad_request", (400, 0, 0), 10),
])
def test_sdk_loopback_response_and_budget(monkeypatch, service, kind, scenario, mode, seconds):
    service.mode = mode
    model = make_model(monkeypatch, kind, endpoint(service))
    budget = RunBudget({"seconds": seconds, "tokens": 20000})
    with closing(model.client), budget_scope(budget):
        if scenario == "deadline":
            with pytest.raises((BudgetExhausted, RuntimeError), match="(?i)timed out|seconds"):
                generate(model)
            assert not service.finished.is_set(), "The client waited past the deadline for the final body bytes"
        elif scenario == "bad_request":
            with pytest.raises(RuntimeError, match="Fixture rejected the request"):
                generate(model)
        else:
            assert generate(model) == RESULT
    assert len(service.requests) == 1
    path, request = service.requests[0]
    assert path == "/v1/chat/completions"
    if kind is VisualModel:
        assert request["messages"][0]["content"][1]["type"] == "image_url"
    state = budget.snapshot()
    assert state["used"]["http_attempts"] == 1 and state["reserved_tokens"] == 0
    if scenario in {"success", "slow"}:
        assert state["used"]["tokens"] == 20 and state["unreported_tokens_charged"] == 0
    else:
        assert state["used"]["tokens"] == state["unreported_tokens_charged"] > 0


@pytest.mark.parametrize("kind", [TextModel, VisualModel])
def test_sdk_loopback_connection_refused_refunds_tokens(monkeypatch, kind):
    with closing(socket.socket()) as unused:
        unused.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{unused.getsockname()[1]}/v1"
        model = make_model(monkeypatch, kind, url)
        budget = RunBudget({"seconds": 10, "tokens": 20000}, model_failure_threshold=2)
        with closing(model.client), budget_scope(budget):
            with pytest.raises(RuntimeError, match="Connection error"):
                generate(model)
            with pytest.raises(ModelCircuitOpen, match="connection"):
                generate(model)
            with pytest.raises(ModelCircuitOpen, match="connection"):
                generate(model)
    state = budget.snapshot()
    assert state["used"] == {"calls": 2, "http_attempts": 2, "tokens": 0}
    assert state["reserved_tokens"] == state["reserved_http_attempts"] == 0


def test_native_fallback_still_sends_and_accounts(monkeypatch, service):
    def unsupported(_backend):
        raise TypeError("Unrecognized native backend")

    monkeypatch.setattr(model_io, "DeadlineBackend", unsupported)
    with pytest.warns(RuntimeWarning, match="using native transport"):
        model = make_model(monkeypatch, TextModel, endpoint(service))
    budget = RunBudget({"seconds": 10, "tokens": 20000})
    with closing(model.client), budget_scope(budget):
        assert generate(model) == RESULT
    assert len(service.requests) == 1
    assert budget.snapshot()["used"]["tokens"] == 20


def test_local_transport_failure_refunds_and_opens_circuit(monkeypatch, service):
    model = make_model(monkeypatch, TextModel, endpoint(service))
    budget = RunBudget({"seconds": 10, "tokens": 20000}, model_failure_threshold=2)
    pool = model.client._client._transport._pool

    def fail_before_write(*args, **kwargs):
        raise AssertionError("Injected transport failure before socket write")

    monkeypatch.setattr(pool, "handle_request", fail_before_write)
    with closing(model.client), budget_scope(budget):
        # Legacy SDKs wrap AssertionError as a connection error.
        with pytest.raises((AssertionError, RuntimeError)):
            generate(model)
        for _ in range(2):
            with pytest.raises(ModelCircuitOpen, match="pre_send.*AssertionError"):
                generate(model)
    assert not service.requests
    state = budget.snapshot()
    assert state["used"] == {"calls": 2, "http_attempts": 2, "tokens": 0}
    assert state["reserved_tokens"] == state["reserved_http_attempts"] == 0


def test_authentication_circuit_counts_consecutive_failures_and_resets_on_success(monkeypatch, service):
    model = make_model(monkeypatch, TextModel, endpoint(service))
    budget = RunBudget({"seconds": 10, "tokens": 20000}, model_failure_threshold=2)
    with closing(model.client), budget_scope(budget):
        for status in (401, 200, 401, 403):
            service.mode = (status, 0, 0)
            if status == 200:
                assert generate(model) == RESULT
            elif status == 401:
                with pytest.raises(RuntimeError, match="401"):
                    generate(model)
            else:
                with pytest.raises(ModelCircuitOpen, match="authentication.*403"):
                    generate(model)
        with pytest.raises(ModelCircuitOpen):
            generate(model)
    state = budget.snapshot()
    assert len(service.requests) == 4
    assert state["used"] == {"calls": 4, "http_attempts": 4, "tokens": 20}
    assert state["unreported_tokens_charged"] == 0


def test_pipeline_stops_and_records_circuit_reason(monkeypatch, service, tmp_path):
    from infrastructure.compiler import Compiler

    source = tmp_path / "input"
    source.mkdir()
    (source / "requirements.yaml").write_text(
        "id: ROOT\nname: Fixture\nchildren:\n"
        "  - {id: A, name: Alpha}\n  - {id: B, name: Beta}\n  - {id: C, name: Gamma}\n",
        encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "loopback-fixture")
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint(service))
    monkeypatch.setenv("MODEL", "fixture")
    monkeypatch.setenv("MODEL_REASONING", "provider")
    monkeypatch.setenv("COMPILER_MODEL_FAILURE_THRESHOLD", "2")
    service.mode = (401, 0, 0)
    output = tmp_path / "app"
    Compiler(source, output).compile()
    report = json.loads((output / ".arc/compilation.json").read_text(encoding="utf-8"))
    assert report["status"] == "MODEL_CIRCUIT_OPEN"
    assert report["model_circuit"] == {"category": "authentication", "reason": "HTTP 401", "stage": "02",
        "threshold": 2, "consecutive_failures": 2}
    assert report["stages"]["02_build_db_schema"]["status"] == "MODEL_CIRCUIT_OPEN"
    assert report["stages"]["04_implement_db"]["status"] == "SKIPPED_MODEL_CIRCUIT_OPEN"
    assert len(service.requests) == 2
    assert report["budget"]["used"]["tokens"] == 0
    assert not (output / ".arc/db_schema.json").exists()


@pytest.fixture
def backend_design_input(tmp_path, monkeypatch, service):
    from infrastructure.utils.files import save_json

    arc = tmp_path / ".arc"
    ids = ("left", "right")
    leaves = [{"id": rid, "name": rid, "scenarios": [{"id": "C-" + rid, "name": rid,
        "steps": [{"id": "S-" + rid, "When": "Open", "Then": "Read note"}]}]} for rid in ids]
    save_json(arc / "requirements.json", {"id": "root", "name": "Fixture", "children": [
        {"id": "feature", "name": "Feature", "children": leaves}]})
    save_json(arc / "db_schema.json", {"entities": {"Note": {"fields": {"id": {}}}}, "requirements": {}})
    effects = {"read": ["Note.id"], "write": []}
    empty = {"read": [], "write": []}
    save_json(arc / "db_obligations.json", {
        "requirements": {"root": empty, "feature": empty, **dict.fromkeys(ids, effects)},
        "steps": {"S-" + rid: effects for rid in ids}})
    monkeypatch.setenv("OPENAI_API_KEY", "loopback-fixture")
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint(service))
    monkeypatch.setenv("MODEL", "deepseek-fixture")
    monkeypatch.setenv("MODEL_REASONING", "none")
    monkeypatch.setenv("MODEL_REPAIR_REASONING", "low")
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "12288")
    return arc


def contract_line(rid):
    return json.dumps({"requirement_id": rid, "api_ids": ["api-" + rid], "module_ids": [],
        "apis": {"api-" + rid: {"description": "Read the note", "signature": {
            "name": "read_" + rid, "method": "GET", "path": "/api/" + rid},
            "response": {"success": [200, {"fields": {"id": "integer", "label?": "string"}}]},
            "callees": ["mod-" + rid], "precondition": [],
            "postcondition": [{"id": "Q1", "description": "Returns the note", "status": 200}]}},
        "modules": {"mod-" + rid: {"description": "Read the note", "name": "find_" + rid,
            "input": {"fields": {}}, "output": {"fields": {"id": "integer"}},
            "direct_read": ["Note.id"], "direct_write": [], "callees": [],
            "precondition": [], "postcondition": []}}})


def wire_order(request):
    return json.loads(request["messages"][-1]["content"])["order"]


def respond_with_records(request, reply):
    reply["choices"][0]["message"]["content"] = "\n".join(map(contract_line, wire_order(request)))
    return reply


def test_backend_truncation_retains_only_validated_leaf_and_retries_gap(service, backend_design_input):
    from infrastructure.pipeline.backend_apis import design_backend_apis
    from infrastructure.utils.files import read_artifact

    def respond(request, reply):
        if len(service.requests) == 1:
            reply["choices"][0].update(finish_reason="length", message={"role": "assistant",
                "content": contract_line("left") + '\n{"requirement_id":"right",' })
            reply["usage"] = {"prompt_tokens": 11, "completion_tokens": 4096, "total_tokens": 4107,
                "completion_tokens_details": {"reasoning_tokens": 3500}}
            return reply
        assert "api-left" in read_artifact(backend_design_input, "backend_apis.json")["apis"]
        return respond_with_records(request, reply)

    service.reply = respond
    budget = RunBudget({"tokens": 50000})
    budget.select_stage(0, "05")
    with budget_scope(budget):
        design = design_backend_apis(backend_design_input)
    requests = [request for _, request in service.requests]
    assert [wire_order(request) for request in requests] == [["left", "right"], ["right"]]
    report = read_artifact(backend_design_input, "design_batches_05.json")
    assert report["attempts"][0]["retained"] == ["left"]
    assert design["apis"]["api-left"]["read"] == ["Note.id"]
    assert design["apis"]["api-right"]["response"]["success"]["body"]["required"] == ["id"]
    assert design["modules"]["mod-left"]["callers"] == ["api-left"]
    assert budget.snapshot()["used"]["tokens"] == 4127


def test_backend_reasoning_only_truncation_splits_and_correction_stays_disabled(service, backend_design_input):
    from infrastructure.pipeline.backend_apis import design_backend_apis

    def respond(request, reply):
        order = wire_order(request)
        if len(service.requests) == 1:
            cap = request["max_completion_tokens"]
            reply["choices"][0].update(finish_reason="length", message={"role": "assistant", "content": ""})
            reply["usage"] = {"prompt_tokens": 11, "completion_tokens": cap, "total_tokens": 11 + cap,
                "completion_tokens_details": {"reasoning_tokens": cap}}
            return reply
        if len(service.requests) == 2:
            reply["choices"][0]["message"]["content"] = '{"requirement_id":"left"}'
            return reply
        assert order in (["left"], ["right"])
        return respond_with_records(request, reply)

    service.reply = respond
    budget = RunBudget({"tokens": 100000})
    budget.select_stage(0, "05")
    with budget_scope(budget):
        design = design_backend_apis(backend_design_input)
    requests = [request for _, request in service.requests]
    assert [wire_order(request) for request in requests] == [["left", "right"], ["left"], ["left"], ["right"]]
    assert "correction" in json.loads(requests[2]["messages"][-1]["content"])
    assert all(request["thinking"] == {"type": "disabled"} and "reasoning_effort" not in request for request in requests)
    assert set(design["apis"]) == {"api-left", "api-right"}
    assert budget.snapshot()["used"]["tokens"] == 12288 + 11 + 3 * 20


def test_backend_estimate_splits_before_http(monkeypatch, service, backend_design_input):
    from infrastructure.pipeline.backend_apis import design_backend_apis
    from infrastructure.utils.files import read_artifact

    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "3000")
    service.reply = respond_with_records
    budget = RunBudget({"tokens": 50000})
    budget.select_stage(0, "05")
    with budget_scope(budget):
        design_backend_apis(backend_design_input)
    report = read_artifact(backend_design_input, "design_batches_05.json")
    assert report["attempts"][0]["split_reason"] == "estimated_output"
    assert report["attempts"][0]["estimated_output_tokens"] == 3050
    assert [wire_order(request) for _, request in service.requests] == [["left"], ["right"]]


def test_stage_token_ceiling_leaves_budget_to_implement_accepted_contract(monkeypatch, service, backend_design_input):
    from infrastructure.pipeline import backend_apis
    from infrastructure.shared.agent.tasks import StageIncomplete
    from infrastructure.utils.files import read_artifact

    budget = RunBudget({"tokens": 24000})
    budget.allocate_stages(["05", "06"])
    budget.select_stage(1, "05")
    assert budget.cap("tokens") == 24000 * 17 // 37
    monkeypatch.setattr(backend_apis, "MAX_LEAVES", 1)

    def respond(request, reply):
        reply = respond_with_records(request, reply)
        reply["usage"] = {"prompt_tokens": 8000, "completion_tokens": 100, "total_tokens": 8100}
        return reply

    service.reply = respond
    with budget_scope(budget), pytest.raises(StageIncomplete):
        backend_apis.design_backend_apis(backend_design_input)
    accepted = read_artifact(backend_design_input, "backend_apis.json")
    assert set(accepted["apis"]) == {"api-left"}
    assert len(service.requests) == 1

    # A subsequent model request consumes the actual published contract under 06.
    budget.select_stage(0, "06")
    service.reply = None
    model = TextModel()
    with closing(model.client), budget_scope(budget):
        assert model.generate_json("Implement the accepted contract.", {"api": accepted["apis"]["api-left"]}) == RESULT
    assert len(service.requests) == 2
    assert budget.snapshot()["used"]["tokens"] == 8120
