"""Nonempty offline pipeline regression with fake model responses and local check boundaries."""

from contextlib import ExitStack
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openai.types.chat import ChatCompletionMessage
from PIL import Image
import pytest
import yaml

import main
from infrastructure.compiler import PIPELINE
from infrastructure.pipeline import backend_implementation
from infrastructure.shared.models import text, vision
from infrastructure.stages.backend.testing import BackendChecks
from infrastructure.stages.database import implementation as database
from infrastructure.stages.database.testing import DatabaseChecks
from infrastructure.stages.frontend.triggers import implementation as interactions
from infrastructure.stages.frontend.triggers.testing import E2EChecks
from infrastructure.stages.frontend.ui import implementation as ui
from infrastructure.stages.frontend.ui.testing import FrontendChecks
from infrastructure.utils.presentation.logging import session_info


STAGES = (
    "00_project_initialization", "01_explore_requirement", "02_build_db_schema",
    "03_infer_db_obligations", "04_implement_db", "05_design_backend_apis",
    "06_implement_backend_tdd", "07_design_ui", "08_implement_ui",
    "09_design_frontend_triggers", "10_implement_frontend_tdd",
)
SQL_PATH = "backend/src/db/tables/Note.sql"
SQL = "CREATE TABLE IF NOT EXISTS Note (id INTEGER PRIMARY KEY);\n"
REGISTER = "backend/src/api/register.ts"
APP = "frontend/src/App.tsx"
PAGE_BODY = '''  presentationData("notes", {});
  return <main data-testid="UI-count"><h1>Notes</h1><button data-testid="UI-button">Count notes</button><p role="status">Ready</p></main>;'''
INTERACTIVE_PAGE = """import { useState } from "react";
export function App() {
  const [status, setStatus] = useState("Ready");
  presentationData("notes", {});
  return <main data-testid="UI-count"><h1>Notes</h1><button data-testid="UI-button" onClick={async () => {
    const response = await fetch("/api/note-count");
    const result = await response.json() as { count: number };
    setStatus(String(result.count));
  }}>Count notes</button><p role="status">{status}</p></main>;
}
"""
API_IMPLEMENTATION = """export function registerApis(app: Express, connection: Database.Database): void {
  app.get("/api/note-count", (_request, response) => {
    const result = connection.prepare("SELECT count(id) AS count FROM Note").get();
    response.json(result);
  });
}
"""
HTTP_TEST = """import { test } from "node:test";
import assert from "node:assert/strict";
test("counts persisted notes", async () => {
  const response = await fetch(process.env.ARC_API_BASE_URL + "/api/note-count");
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { count: 0 });
});
"""
E2E_TEST = """import { test, expect } from "@playwright/test";
test("count notes", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("UI-count")).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Ready");
  const [response] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === "/api/note-count"),
    page.getByTestId("UI-button").click(),
  ]);
  expect(response.status()).toBe(200);
  await expect(page.getByRole("status")).toHaveText("0");
});
"""


def response(payload=None, *, tools=(), finish_reason=None):
    message = ChatCompletionMessage(role="assistant",
        content=json.dumps(payload) if payload is not None else None,
        tool_calls=[{"id": f"call-{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}
            for i, (name, arguments) in enumerate(tools)] or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message,
        finish_reason=finish_reason or ("tool_calls" if tools else "stop"))])


def edit(output, path, content):
    assert not (output / path).exists()
    return {"path": path, "operation": "create", "new_content": content}


def replace_once(output, path, old, new):
    source = (output / path).read_text(encoding="utf-8")
    if new in source:
        return response({"tool_calls": []})
    assert source.count(old) == 1, path
    return response({"tool_calls": [{"tool": "edit_file", "path": path, "operation": "replace",
        "old_content": old, "new_content": new}]})


def fixture_model(output, rid, sid, calls, *, other=None):
    object_schema = {"type": "object", "properties": {}}
    api = {"description": "Read the note count", "read": ["Note.id"], "write": [],
        "signature": {"name": "countNotes", "method": "GET", "path": "/api/note-count"},
        "request": dict.fromkeys(("params", "query", "body", "headers"), object_schema),
        "response": {"success": {"status": 200, "body": {"type": "object",
            "properties": {"count": {"type": "integer"}}, "required": ["count"]},
            "headers": object_schema}, "errors": []},
        "precondition": [], "postcondition": [{"id": "Q-1", "description": "Return count", "status": 200}],
        "callees": ["MOD-COUNT"]}
    module = {"description": "Count notes in SQLite", "name": "selectNoteCount", "input": object_schema,
        "output": api["response"]["success"]["body"], "direct_read": ["Note.id"], "direct_write": [],
        "read": ["Note.id"], "write": [], "callees": [], "precondition": [], "postcondition": []}
    obligations = {"read": ["Note.id"], "write": []}

    def reply(_client, args, **_):
        number = session_info()["stage"].split()[1]
        calls.append(number)
        prompt = args["messages"][-1]["content"]
        if number in {"02", "03", "05", "07", "09"}:
            request = json.loads(prompt)
            owners = request["order"]
            known_steps = {rid: sid, **(dict([other]) if other else {})}
            assert set(owners) <= set(known_steps)
            assert all(known_steps[owner] in prompt for owner in owners)
            assert {"identity", "session", "naming", "errors", "data"} == set(request["shared_catalog"]["policies"])
        if number == "02":
            if len(owners) > 1:
                return response(finish_reason="length")
            exists = "Note" in request["shared_catalog"]["accepted_symbols"].get("entities", {})
            return response({"entities": {} if exists else {"Note": {"description": "Persisted note", "fields": {"id": {
                "description": "Note identity", "type": "integer", "nullable": False,
                "primary_key": True, "unique": False, "references": None, "constraints": []}}}},
                "requirements": {owner: {"related_fields": ["Note.id"]} for owner in owners}})
        if number == "03":
            assert "Note.id" in request["shared_catalog"]["accepted_symbols"]["fields"]
            return response({"requirements": {owner: {"requirement": obligations,
                "steps": {known_steps[owner]: obligations}} for owner in owners}})
        if number == "04":
            if SQL_PATH in prompt and not (output / SQL_PATH).exists():
                return response(tools=[("edit_file", edit(output, SQL_PATH, SQL))])
            assert (output / SQL_PATH).is_file()
            return response()
        if number == "05":
            assert all(request["requirements"][owner]["required_obligations"]["read"] == ["Note.id"] for owner in owners)
            return response({"apis": {"API-COUNT": api}, "modules": {"MOD-COUNT": module},
                "requirements": {owner: {"api_ids": ["API-COUNT"], "module_ids": [],
                    "conventions": {"count": "Use integer count for note counts."}} for owner in owners}})
        if number == "07":
            assert "One panel" in json.dumps(request)
            assert "count" in request["shared_catalog"]["shared_conventions"]
            root = "UI-count"
            return response({"requirements": {owner: {
                "pages": {"notes": {"route": "/", "name": "Notes", "root": root, "images": []}} if i == 0 else {},
                "elements": {
                    root: {"type": "page", "parent": None},
                    "UI-button": {"type": "button", "parent": root, "prop": {"text": "Count notes"}},
                } if i == 0 else {}, "requirement_ui": [root, "UI-button"], "step_ui": {known_steps[owner]: ["UI-button"]}}
                for i, owner in enumerate(owners)}})
        if number == "09":
            assert request["backend_apis"]["API-COUNT"]["read"] == ["Note.id"]
            assert all("UI-button" in request["requirements"][owner]["ui"]["elements"] for owner in owners)
            return response({"requirements": {owner: {
                "triggers": {"TR-COUNT": {"source": "UI-button", "event": "click",
                    "guard": None, "read": [], "write": [], "action": [{"kind": "api",
                        "api": "API-COUNT", "description": "Fetch and display count"}]}} if i == 0 else {},
                "requirement_triggers": ["TR-COUNT"], "step_triggers": {known_steps[owner]: ["TR-COUNT"]}}
                for i, owner in enumerate(owners)}})
        request = json.loads(prompt)
        task = request["task"]
        if number == "06":
            assert task["api_id"] == "API-COUNT"
            if "test_path" in task:
                return response({"tool_calls": [{"tool": "edit_file", **edit(output, task["test_path"], HTTP_TEST)}]})
            return replace_once(output, REGISTER,
                "export function registerApis(_app: Express, _connection: Database.Database): void {}",
                API_IMPLEMENTATION.rstrip())
        elif number == "08":
            assert task["page"]["root"] == "UI-count"
            old = ('export function App() {\n'
                '  return <main><h1>Application</h1><p>The project is ready for requirement implementation.</p></main>;')
            new = 'import { presentationData } from "./ui-runtime";\nexport function App() {\n' + PAGE_BODY
            return replace_once(output, APP, old, new)
        elif number == "10":
            assert "TR-COUNT" in task["triggers"]
            if "test_path" in task:
                path = task["test_path"]
                if (output / path).exists():
                    return response({"tool_calls": []})  # Review keeps the original business assertion.
                content = E2E_TEST
            else:
                return replace_once(output, APP, "export function App() {\n" + PAGE_BODY + "\n}",
                    INTERACTIVE_PAGE.rstrip())
        else:
            raise AssertionError(f"Unexpected mock request in {number}")
        return response({"tool_calls": [{"tool": "edit_file", **edit(output, path, content)}]})

    return reply


def mock_local_checks(stack):
    """Simulate process outcomes from actual file changes, exercising real acceptance gates."""
    ok = {"returncode": 0, "output": "mocked local process"}

    def backend_init(checks, output):
        checks.output = output.resolve()

    stack.enter_context(patch.object(BackendChecks, "__init__", backend_init))
    for module in (database, backend_implementation, ui, interactions):
        stack.enter_context(patch.object(module, "install_dependencies", return_value=None))
    stack.enter_context(patch.object(DatabaseChecks, "run", return_value=ok))
    for cls in (BackendChecks, FrontendChecks, E2EChecks):
        for method in ("typecheck", "build"):
            stack.enter_context(patch.object(cls, method, return_value=ok))
    stack.enter_context(patch.object(FrontendChecks, "install_browser", return_value=None))

    def backend_test(checks, files):
        assert all((checks.output / path).is_file() for path in files)
        passed = "SELECT count(id)" in (checks.output / REGISTER).read_text(encoding="utf-8")
        return {**ok, "returncode": int(not passed), "output": "mocked HTTP assertion" if passed else "ERR_ASSERTION",
            "tests": 1, "pass": int(passed), "fail": int(not passed)}

    def browser_test(checks, files):
        assert all((checks.output / path).is_file() for path in files)
        source = (checks.output / APP).read_text(encoding="utf-8")
        spec = "\n".join((checks.output / path).read_text(encoding="utf-8") for path in files)
        ids = re.findall(r'getByTestId\(["\']([^"\']+)', spec)
        passed = bool(ids) and all(f'data-testid="{element_id}"' in source for element_id in ids)
        if isinstance(checks, E2EChecks):
            passed &= 'fetch("/api/note-count")' in source and "onClick=" in source
        return {**ok, "returncode": int(not passed), "passed": int(passed), "failed": int(not passed),
            "skipped": 0, "flaky": 0, "errors": [],
            "failures": [] if passed else ["AssertionError: expect(button or count)"],
            "files": {path: {"passed": int(passed), "failed": int(not passed)} for path in files}}

    stack.enter_context(patch.object(BackendChecks, "tests", backend_test))
    stack.enter_context(patch.object(FrontendChecks, "tests", browser_test))
    stack.enter_context(patch.object(E2EChecks, "tests", browser_test))


@pytest.mark.parametrize("root_id,rid,sid,dirname", [
    ("ROOT", "R-COUNT", "S-COUNT", "original"),
    ("NEW-ROOT", "RENAMED-REQ", "RENAMED-STEP", "unseen-project"),
    ("ROOT-BATCH", "R-COUNT", "S-COUNT", "multi-leaf"),
])
def test_nonempty_pipeline_handoffs(tmp_path, monkeypatch, root_id, rid, sid, dirname):
    source, output = tmp_path / dirname, tmp_path / "application"
    source.mkdir()
    Image.new("RGB", (12, 12), "white").save(source / "reference.png")
    raw = {"id": root_id, "name": dirname, "children": [{"id": rid, "name": "Notes",
        "description": {"text": "On the Notes page, count records on request.", "image": [{"id": "IMG-notes", "reference": "reference.png", "page": "notes"}]},
        "scenarios": [{"id": "scenario-" + rid, "name": "Count notes", "steps": [{"id": sid,
            "Given": "There are no notes", "When": "Click Count notes", "Then": "Show 0"}]}]}]}
    other = None
    if dirname == "multi-leaf":
        from copy import deepcopy
        other = ("R-SECOND", "S-SECOND")
        first = raw["children"][0]
        second = deepcopy(first)
        second["id"], second["scenarios"][0]["steps"][0]["id"] = other
        second["scenarios"][0]["id"] = "scenario-" + other[0]
        second["description"]["text"] = r"Show the same count as \ref[requirement](R-COUNT)."
        raw["children"] = [{"id": "module-notes", "name": "Notes", "children": [first, second]}]
    (source / "requirements.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "mock-only")
    calls = []
    fake = fixture_model(output, rid, sid, calls, other=other)
    with ExitStack() as stack:
        stack.enter_context(patch.object(text, "invoke", fake))
        def fake_vision(_client, args):
            assert args["messages"][0]["content"][1]["type"] == "image_url"
            calls.append("01")
            return response({"layout": "One panel", "elements": ["Count notes"], "style": "plain"})
        stack.enter_context(patch.object(vision, "invoke", fake_vision))
        if os.getenv("STAGED11_REAL_CHECKS") != "1":
            mock_local_checks(stack)
        main.main([str(source), "--output-dir", str(output)])

    def read(name):
        return json.loads((output / ".arc" / (name + ".json")).read_text(encoding="utf-8"))

    report = read("compilation")
    assert "version" in report["node_preflight"]
    assert "[PREFLIGHT] node --version:" in (output / "compiler.log").read_text(encoding="utf-8")
    assert tuple(name for name, _, _ in PIPELINE) == STAGES
    assert tuple(report["stages"]) == STAGES
    assert report["status"] == "GREEN", {k: v for k, v in report["stages"].items() if v["status"] != "GREEN"}
    assert all(stage["status"] == "GREEN" for stage in report["stages"].values())
    assert read("requirements")["id"] == root_id
    assert "One panel" in json.dumps(read("visual_analysis"))
    assert read("db_schema")["requirements"][rid] == ["Note.id"]
    assert read("db_obligations")["steps"][sid]["read"] == ["Note.id"]
    assert (output / SQL_PATH).read_text(encoding="utf-8") == SQL
    assert "Note.sql" in (output / "backend/src/db/initialize.ts").read_text(encoding="utf-8")
    assert read("db_checks")["status"] == "GREEN"
    assert read("backend_apis")["requirements"][rid] == ["API-COUNT"]
    assert read("backend_tdd")["apis"]["API-COUNT"]["status"] == "GREEN"
    assert read("ui_design")["steps"][sid] == ["UI-button"]
    assert read("ui_checks")["requirements"][rid]["status"] == "GREEN"
    assert read("frontend_triggers")["steps"][sid] == ["TR-COUNT"]
    assert read("frontend_e2e")["requirements"][rid]["status"] == "GREEN"
    assert read("frontend_e2e")["summary"]["triggers"] == 1
    if other:
        second, second_step = other
        attempts = read("design_batches_02")["attempts"]
        assert [(entry["id"], entry["status"]) for entry in attempts] == [
            ("B001", "SPLIT"), ("B001.a", "GREEN"), ("B001.b", "GREEN")]
        assert attempts[0]["split_reason"] == "output_truncated"
        assert {entry["batch"] for entry in read("design_batches_02")["coverage"]["steps"]} == {"B001.a", "B001.b"}
        assert calls.count("02") == 3
        for stage in ("03", "05", "07", "09"):
            assert calls.count(stage) == 1
            assert read("design_batches_" + stage)["attempts"][0]["leaves"] == [rid, second]
        assert read("db_obligations")["steps"][second_step]["read"] == ["Note.id"]
        assert read("backend_apis")["requirements"][second] == ["API-COUNT"]
        assert read("ui_design")["steps"][second_step] == ["UI-button"]
        assert read("frontend_triggers")["steps"][second_step] == ["TR-COUNT"]
    assert set(calls) == {"01", "02", "03", "04", "05", "06", "07", "08", "09", "10"}
    assert "fetch(" in (output / APP).read_text(encoding="utf-8")
    assert (output / "deploy.sh").is_file()

@pytest.mark.parametrize("version, warning", [("v26.13.0", True), ("v22.23.5", False), ("v22.11.0", True)])
def test_node_preflight_records_version_and_compatibility(tmp_path, version, warning):
    from infrastructure.compiler import node_preflight

    with patch("infrastructure.compiler.capture_process",
            return_value={"returncode": 0, "stdout": version + "\n"}) as probe:
        result = node_preflight(tmp_path)
    probe.assert_called_once_with(["node", "--version"], cwd=tmp_path, timeout=5)
    assert result["version"] == version
    assert bool(result["warning"]) == warning
    log = (tmp_path / "compiler.log").read_text(encoding="utf-8")
    assert version in log
    assert ("[WARNING]" in log) == warning
