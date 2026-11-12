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
E2E_TEST = """import { test, expect } from "./support/context.js";
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


def fixture_model(output, rid, sid, calls, *, other=None, artifacts=False):
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
    apis = {"API-COUNT": api}
    modules = {"MOD-COUNT": module}
    step_ids = {rid: sid, **(dict([other]) if other else {})}
    entry = other[0] if artifacts else None
    targets = {owner: "API-ENTRY" if owner == entry else "API-COUNT" for owner in step_ids}
    extra_path = "/api/note-count/entries"
    page_route = "/notes/entries"
    if artifacts:
        apis["API-ENTRY"] = {**api, "read": ["Entry.id"], "callees": ["MOD-ENTRY"],
            "signature": {"name": "countEntries", "method": "GET", "path": extra_path}}
        modules["MOD-ENTRY"] = {**module, "name": "selectEntryCount", "read": ["Entry.id"],
            "direct_read": ["Entry.id"]}
    field = {"description": "Identity", "type": "integer", "nullable": False, "primary_key": True,
        "unique": False, "references": None, "constraints": []}
    entities = {"Note": {"description": "Persisted note", "fields": {"id": field}},
        "Entry": {"description": "Persisted entry", "fields": {"id": field,
            "note_id": {**field, "primary_key": False, "nullable": True, "references": "Note.id"}}}}

    def labels(owner):
        return ("entries", "UI-entry", "UI-entry-button", "Count entries", "TR-ENTRY", page_route) if owner == entry else (
            "notes", "UI-count", "UI-button", "Count notes", "TR-COUNT", "/")

    page_body = PAGE_BODY
    interactive = INTERACTIVE_PAGE
    api_source = API_IMPLEMENTATION.rstrip()
    if artifacts:
        page_body = (
            '  if (location.pathname === "/notes/entries") {\n'
            '    presentationData("entries", {});\n'
            '    return <main data-testid="UI-entry"><h1>Entries</h1><button data-testid="UI-entry-button">Count entries</button><p role="status">Ready</p></main>;\n'
            '  }\n' + PAGE_BODY)
        interactive = """import { useState } from "react";
export function App() {
  const [status, setStatus] = useState("Ready");
  if (location.pathname === "/notes/entries") {
    presentationData("entries", {});
    return <main data-testid="UI-entry"><h1>Entries</h1><button data-testid="UI-entry-button" onClick={async () => {
      const result = await (await fetch("/api/note-count/entries")).json() as { count: number };
      setStatus(String(result.count));
    }}>Count entries</button><p role="status">{status}</p></main>;
  }
""" + INTERACTIVE_PAGE[INTERACTIVE_PAGE.index('  presentationData("notes"'):]
        api_source = api_source[:-1] + API_IMPLEMENTATION.split("\n", 1)[1].rstrip()[:-1].replace(
            '"/api/note-count"', '"' + extra_path + '"').replace("FROM Note", "FROM Entry") + "}"

    def reply(_client, args, **_):
        number = session_info()["stage"].split()[1]
        calls.append(number)
        request = json.loads(args["messages"][-1]["content"])
        if number in {"02", "03", "05", "07", "09"}:
            owners = request["order"]
            assert set(owners) <= set(step_ids)
            assert all(step_ids[owner] in args["messages"][-1]["content"] for owner in owners)
            assert {"identity", "session", "naming", "errors", "data"} == set(request["shared_catalog"]["policies"])
        if number == "02":
            if len(owners) > 1:
                return response(finish_reason="length")
            exists = request["shared_catalog"]["accepted_symbols"].get("entities", {})
            used = {field.split(".", 1)[0] for owner in owners for field in apis[targets[owner]]["read"]}
            return response({"entities": {name: entities[name] for name in sorted(used - exists.keys())},
                "requirements": {owner: {"related_fields": apis[targets[owner]]["read"]} for owner in owners}})
        if number == "03":
            effects = {owner: {"read": apis[targets[owner]]["read"], "write": []} for owner in owners}
            return response({"requirements": effects, "steps": {step_ids[owner]: effects[owner] for owner in owners}})
        if number == "04":
            if "prerequisites" in request:
                assert "requirement_evidence" not in request
                rows = {owner: {"rows": []} for owner in request["units"]}
                if artifacts and rid in rows:
                    rows[rid]["rows"].append({"table": "Note",
                        "sql": "INSERT INTO Note (id) SELECT 11 WHERE NOT EXISTS (SELECT 1 FROM Note WHERE id = 11);",
                        "evidence": {"source": sid, "quote": "Note 11 already exists", "identity": "11"}})
                if entry in rows:
                    rows[entry]["rows"].append({"table": "Entry",
                        "sql": "INSERT INTO Entry (id, note_id) SELECT 7, 11 WHERE NOT EXISTS (SELECT 1 FROM Entry WHERE id = 7);",
                        "evidence": {"source": step_ids[entry], "quote": "Entry 7 already exists", "identity": "7"}})
                return response({"requirements": rows})
            statements = {"Note": SQL,
                "Entry": "CREATE TABLE IF NOT EXISTS Entry (id INTEGER PRIMARY KEY, note_id INTEGER REFERENCES Note(id));\n"}
            return response(tools=[("edit_file", edit(output, record["output_path"], statements[name]))
                for name, record in request["tables"].items()])
        if number == "05":
            assert all(request["requirements"][owner]["required_obligations"]["read"] == apis[targets[owner]]["read"]
                for owner in owners)
            return response({"apis": apis, "modules": modules,
                "requirements": {owner: {"api_ids": [targets[owner]], "module_ids": [],
                    "conventions": {"count": "Use integer count for note counts."}} for owner in owners}})
        if number == "07":
            assert "One panel" in json.dumps(request)
            assert "count" in request["shared_catalog"]["shared_conventions"]
            result, seen = {}, set()
            for owner in owners:
                pid, root, button, caption, _, route = labels(owner)
                result[owner] = {"pages": {}, "elements": {}, "requirement_ui": [root, button],
                    "step_ui": {step_ids[owner]: [button]}}
                if pid not in seen:
                    seen.add(pid)
                    result[owner]["pages"][pid] = {"route": route, "name": pid.title(), "root": root,
                        "images": [], "layout": "notes"}
                    result[owner]["elements"].update({root: {"type": "page", "parent": None},
                        button: {"type": "button", "parent": root, "prop": {"text": caption}}})
            return response({"requirements": result})
        if number == "09":
            result, seen = {}, set()
            for owner in owners:
                _, _, button, _, tid, _ = labels(owner)
                assert button in request["requirements"][owner]["ui"]["elements"]
                result[owner] = {"triggers": {}, "requirement_triggers": [tid], "step_triggers": {step_ids[owner]: [tid]}}
                if tid not in seen:
                    seen.add(tid)
                    result[owner]["triggers"][tid] = {"source": button, "event": "click", "guard": None,
                        "read": [], "write": [], "action": [{"kind": "api", "api": targets[owner],
                            "description": "Fetch and display count"}]}
            return response({"requirements": result})
        task = request["task"]
        if number == "06":
            if "test_paths" in task:
                records = []
                for aid, record in task["apis"].items():
                    content = HTTP_TEST if aid == "API-COUNT" else HTTP_TEST.replace(
                        '"/api/note-count"', '"' + extra_path + '"').replace("{ count: 0 }", "{ count: 1 }")
                    if artifacts:
                        content = content.replace("{ count: 0 }", "{ count: 1 }")
                    records.append({"tool": "edit_file", **edit(output, record["test_path"], content)})
                return response({"tool_calls": records})
            return replace_once(output, REGISTER,
                "export function registerApis(_app: Express, _connection: Database.Database): void {}", api_source)
        if number == "08":
            assert "notes" in task["pages"]
            old = ('export function App() {\n'
                '  return <main><h1>Application</h1><p>The project is ready for requirement implementation.</p></main>;')
            new = 'import { presentationData } from "./ui-runtime";\nexport function App() {\n' + page_body
            return replace_once(output, APP, old, new)
        if number == "10":
            if "test_paths" in task:
                records = []
                for owner, scenario in task["scenarios"].items():
                    path = scenario["test_path"]
                    if (output / path).exists():
                        continue  # Review keeps the original business assertion.
                    content = E2E_TEST if owner != entry else E2E_TEST.replace('goto("/")', 'goto("' + page_route + '")').replace(
                        '"/api/note-count"', '"' + extra_path + '"').replace("UI-count", "UI-entry").replace(
                        "UI-button", "UI-entry-button").replace('toHaveText("0")', 'toHaveText("1")')
                    if artifacts:
                        content = content.replace('toHaveText("0")', 'toHaveText("1")')
                    records.append({"tool": "edit_file", **edit(output, path, content)})
                return response({"tool_calls": records})
            return replace_once(output, APP, "export function App() {\n" + page_body + "\n}", interactive.rstrip())
        raise AssertionError(f"Unexpected mock request in {number}")

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
    stack.enter_context(patch.object(FrontendChecks, "render", return_value={**ok, "passed": 1, "failed": 0}))

    def backend_test(checks, files):
        assert all((checks.output / path).is_file() for path in files)
        source = (checks.output / REGISTER).read_text(encoding="utf-8")
        suite = "\n".join((checks.output / path).read_text(encoding="utf-8") for path in files)
        endpoints = re.findall(r'ARC_API_BASE_URL \+ "([^"]+)"', suite)
        passed = not files or bool(endpoints) and all(f'app.get("{endpoint}"' in source for endpoint in endpoints)
        return {**ok, "returncode": int(not passed), "output": "mocked HTTP assertion" if passed else "ERR_ASSERTION",
            "tests": 1, "pass": int(passed), "fail": int(not passed)}

    def browser_test(checks, files):
        assert all((checks.output / path).is_file() for path in files)
        source = (checks.output / APP).read_text(encoding="utf-8")
        spec = "\n".join((checks.output / path).read_text(encoding="utf-8") for path in files)
        ids = re.findall(r'getByTestId\(["\']([^"\']+)', spec)
        passed = bool(ids) and all(f'data-testid="{element_id}"' in source for element_id in ids)
        if isinstance(checks, E2EChecks):
            endpoints = re.findall(r'pathname === "([^"]+)"', spec)
            passed &= bool(endpoints) and all(f'fetch("{endpoint}")' in source for endpoint in endpoints) and "onClick=" in source
        return {**ok, "returncode": int(not passed), "passed": int(passed), "failed": int(not passed),
            "skipped": 0, "flaky": 0, "errors": [],
            "failures": [] if passed else ["AssertionError: expect(button or count)"],
            "files": {path: {"passed": int(passed), "failed": int(not passed)} for path in files},
            "cases": {path: {"status": "passed" if passed else "failed", "failure": "Count not visible" if not passed else ""}
                for path in files}}

    stack.enter_context(patch.object(BackendChecks, "tests", backend_test))
    stack.enter_context(patch.object(FrontendChecks, "tests", browser_test))
    stack.enter_context(patch.object(E2EChecks, "tests", browser_test))


@pytest.mark.parametrize("root_id,rid,sid,dirname", [
    ("ROOT", "R-COUNT", "S-COUNT", "original"),
    ("NEW-ROOT", "RENAMED-REQ", "RENAMED-STEP", "unseen-project"),
    ("ROOT-BATCH", "R-COUNT", "S-COUNT", "multi-leaf"),
    ("ROOT-ARTIFACTS", "R-COUNT", "S-COUNT", "artifact-groups"),
    ("ROOT-PARTIAL", "R-COUNT", "S-COUNT", "partial-obligations"),
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
    artifacts = dirname == "artifact-groups"
    partial = dirname == "partial-obligations"
    if dirname in ("multi-leaf", "artifact-groups") or partial:
        from copy import deepcopy
        other = ("R-SECOND", "S-SECOND")
        first = raw["children"][0]
        second = deepcopy(first)
        second["id"], second["scenarios"][0]["steps"][0]["id"] = other
        second["scenarios"][0]["id"] = "scenario-" + other[0]
        second["description"]["text"] = r"Show the same count as \ref[requirement](R-COUNT)."
        if artifacts:
            first["scenarios"][0]["steps"][0].update(Given="Note 11 already exists", Then="Show 1")
            second["name"] = "Count entries"
            second["description"]["image"] = []
            second["scenarios"][0]["steps"][0].update(Given="Entry 7 already exists",
                When="Click Count entries", Then="Show 1")
        raw["children"] = [{"id": "module-notes", "name": "Notes", "children": [first, second]}]
    (source / "requirements.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "mock-only")
    calls = []
    fake = fixture_model(output, rid, sid, calls, other=other, artifacts=artifacts)
    with ExitStack() as stack:
        def invoke(client, args, **kwargs):
            number = session_info()["stage"].split()[1]
            if partial and number in {"03", "05", "09"}:
                request = json.loads(args["messages"][-1]["content"])
                if number == "03" and other[0] in request["order"]:
                    if correction := request.get("correction"):
                        assert "Top-level steps" in correction["error"]
                        assert "previous_response" not in correction
                    calls.append(number)
                    return response({"requirements": {owner: {"read": ["Note.id"], "write": []}
                        for owner in request["order"]}})
                if number in {"05", "09"}:
                    assert request["order"] == [rid]
            return fake(client, args, **kwargs)
        stack.enter_context(patch.object(text, "invoke", invoke))
        def fake_vision(_client, args):
            assert args["messages"][0]["content"][1]["type"] == "image_url"
            calls.append("01")
            return response({"layout": "One panel", "elements": ["Count notes"], "style": "plain"})
        stack.enter_context(patch.object(vision, "invoke", fake_vision))
        if os.getenv("STAGED11_REAL_CHECKS") != "1":
            mock_local_checks(stack)
        args = [str(source), "--output-dir", str(output)]
        if partial:
            with pytest.raises(SystemExit) as exit_status:
                main.main(args)
            assert exit_status.value.code == 0
        else:
            main.main(args)

    def read(name):
        return json.loads((output / ".arc" / (name + ".json")).read_text(encoding="utf-8"))

    report = read("compilation")
    assert "version" in report["node_preflight"]
    assert "[PREFLIGHT] node --version:" in (output / "compiler.log").read_text(encoding="utf-8")
    assert tuple(name for name, _, _ in PIPELINE) == STAGES
    assert tuple(report["stages"]) == STAGES
    if partial:
        assert report["status"] == "COMPLETED_WITH_FAILURES"
        assert [stage["status"] for stage in report["stages"].values()] == [
            "GREEN", "GREEN", "GREEN", "COMPLETED_WITH_FAILURES", "GREEN", "COMPLETED_WITH_FAILURES",
            "COMPLETED_WITH_FAILURES", "GREEN", "GREEN", "COMPLETED_WITH_FAILURES", "COMPLETED_WITH_FAILURES"]
        blocked, blocked_step = other
        obligations = read("db_obligations")
        assert blocked_step not in obligations["steps"]
        assert obligations["unavailable"][blocked]["missing_steps"] == [blocked_step]
        contracts = read("backend_apis")["requirements"]
        assert contracts[rid] == ["API-COUNT"] and blocked not in contracts
        assert read("backend_tdd")["apis"]["API-COUNT"]["status"] == "GREEN"
        assert blocked in read("frontend_triggers")["unavailable"]
        acceptance = read("frontend_e2e")["requirements"]
        assert {key: acceptance[key]["status"] for key in (rid, blocked)} == {rid: "GREEN", blocked: "FAILED"}
        return
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
    assert read("frontend_e2e")["summary"]["triggers"] == (2 if artifacts else 1)
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
        assert read("db_obligations")["steps"][second_step]["read"] == ["Entry.id" if artifacts else "Note.id"]
        assert read("backend_apis")["requirements"][second] == ["API-ENTRY" if artifacts else "API-COUNT"]
        assert read("ui_design")["steps"][second_step] == ["UI-entry-button" if artifacts else "UI-button"]
        assert read("frontend_triggers")["steps"][second_step] == ["TR-ENTRY" if artifacts else "TR-COUNT"]
    if artifacts:
        expected = {"04_ddl": {"Note", "Entry"}, "04_seed": {rid, other[0]},
            "06": {"API-COUNT", "API-ENTRY"}, "08": {"notes", "entries"}, "10": {rid, other[0]}}
        for stage, units in expected.items():
            grouped = read("implementation_batches_" + stage)
            assert len(grouped["attempts"]) == 1
            assert set(grouped["attempts"][0]["units"]) == units
            assert grouped["attempts"][0]["status"] == "GREEN"
            assert all(row["batches"] for row in grouped["coverage"]["steps"])
        seed = read("implementation_batches_04_seed")["results"][other[0]]["rows"]
        assert seed[0]["source"] == other[1] and seed[0]["quote"] == "Entry 7 already exists"
        assert {stage: calls.count(stage) for stage in ("04", "06", "08", "10")} == {
            "04": 2, "06": 2, "08": 1, "10": 3}
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
