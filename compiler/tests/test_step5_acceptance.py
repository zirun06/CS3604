"""Offline checks for contract drift, page smoke, durable data and candidate recovery."""

import json
from pathlib import Path
import sqlite3
import subprocess
from unittest.mock import Mock

import pytest

from infrastructure.shared.agent.loop import AgentExhausted, run_file_agent
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.type_repair import implicit_any_locations, recheck_types
from infrastructure.stages.database.testing import PROBE_SOURCE
from infrastructure.stages.frontend.triggers import e2e_runtime
from infrastructure.stages.frontend.triggers.acceptance_gate import FrozenAcceptance, coverage_matrix, write_revision
from infrastructure.stages.frontend.ui.testing import FrontendChecks, require_green, render_spec
from infrastructure.stages.requirements.batching import DesignPlan
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import read_artifact, save_text


def node(source, *args):
    result = subprocess.run(["node", "--experimental-sqlite", "--input-type=module", "-", *args],
        input=source, text=True, encoding="utf-8", capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_wire_detects_wrong_api_path_missing_field_and_unresolved_route_context():
    module = Path(e2e_runtime.__file__).with_name("wire_contract.mjs").as_uri()
    node(f'import {{ wireError }} from {json.dumps(module)};\n' + """
import assert from "node:assert/strict";
const apis = {READ: { signature: {method: "GET", path: "/api/records/{id}"},
  request: {params: {properties: {id: {type: "integer"}}}},
  response: {success: {status: 200, body: {type: "object", required: ["items"],
    properties: {items: {type: "array", items: {type: "string"}}}}}, errors: []}}};
assert.equal(wireError(apis, "GET", "/api/records/7", 200, {items: []}), null);
assert.match(wireError(apis, "GET", "/api/wrong/7", 200, {}), /no matching/);
assert.match(wireError(apis, "GET", "/api/records/7", 200, {}), /items is missing/);
assert.match(wireError(apis, "GET", "/api/records/7", 200, {items: [3]}), /expected string/);
assert.match(wireError(apis, "GET", "/api/records/:id", 200, {}), /route context/);
assert.match(wireError(apis, "GET", "/api/records/undefined", 200, {}), /route context/);
assert.match(wireError(apis, "GET", "/api/records/7", 404, {}), /unexpected HTTP status/);
""")


@pytest.mark.parametrize("text, runtime_error, error", [
    ("", None, "no visible content"), ("App content", "load crashed", "Page runtime errors"),
    ("App content", None, None),
])
def test_render_probe_rejects_empty_dom_and_runtime_errors(text, runtime_error, error):
    # Execute the actual callback against a minimal DOM and Playwright assertion stub.
    spec = render_spec(["/"]).split("\n", 1)[1].replace(": string[]", "").replace(": Element", "")
    spec = spec.replace("(root as HTMLElement)", "root").replace("new Promise<void>", "new Promise")
    data = json.dumps([text, runtime_error, error])
    node(f'const [text, runtimeError, expectedError] = {data};\n' + """
import assert from "node:assert/strict";
const root = {innerText: text, querySelectorAll: () => [], getClientRects: () => [{}]};
globalThis.document = {querySelector: () => root};
globalThis.getComputedStyle = () => ({visibility: "visible", opacity: "1"});
globalThis.requestAnimationFrame = callback => queueMicrotask(callback);
const handlers = {};
const page = {
  on(name, callback) { handlers[name] = callback; },
  goto() {
    if (runtimeError) handlers.pageerror(new Error(runtimeError));
    return {ok: () => true};
  },
  evaluate(callback) { return callback(); }
};
let result;
function test(_title, callback) { result = callback({page}); }
function expect(value, message) {
  return {toBe: expected => assert.equal(value, expected, message),
    toEqual: expected => assert.deepEqual(value, expected, message)};
}
expect.poll = (action, {message}) => ({toBe: async expected => assert.equal(await action(), expected, message)});
""" + spec + """
if (expectedError) await assert.rejects(result, new RegExp(expectedError));
else await result;
""")


def test_render_check_defers_dynamic_routes_and_propagates_browser_failure(tmp_path, monkeypatch):
    checks = FrontendChecks(tmp_path)
    def failed(files):
        assert (tmp_path / files[0]).is_file()
        return {"returncode": 1, "failed": 1, "output": "empty page"}
    monkeypatch.setattr(checks, "_run_suites", failed)
    result = checks.render({"static": {"route": "/"}, "dynamic": {"route": "/records/:id"}})
    assert result["routes"] == ["/"]
    assert result["dynamic_routes_requiring_scenarios"] == ["/records/:id"]
    assert not (tmp_path / checks.render_path).exists()
    with pytest.raises(ValueError):
        require_green(result)


def test_persistence_probe_rejects_lost_rows_in_reopened_file(tmp_path):
    filename = tmp_path / "test.db"
    with sqlite3.connect(filename) as db:
        db.execute("CREATE TABLE records (id INTEGER, label TEXT)")
        db.execute("INSERT INTO records VALUES (7, 'existing')")
    source = PROBE_SOURCE[PROBE_SOURCE.index("function tableRows"):PROBE_SOURCE.index("function seedMarker")]
    node("""
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
const filename = process.argv[2];
class Database extends DatabaseSync {
  defaultSafeIntegers() {}
}
const plan = {tables: {records: ["id", "label"]}};
const quote = name => '"' + name + '"';
let phase;
const completed = [], validations = [];
function inspect() {}
function record(kind) { validations.push([kind, completed.includes(phase)]); }
""" + source + """
const expected = tableRows(filename);
verifyPersistence(filename, expected, "first reopen");
const changed = new Database(filename);
changed.exec("DELETE FROM records");
changed.close();
assert.throws(() => verifyPersistence(filename, expected, "restart"), /rows changed/);
assert.deepEqual(validations, [["persistence_check", true], ["persistence_check", false]]);
""", str(filename))


def results(*cases):
    return {"leaf": {"cases": {name: {"status": status, "failure": reason}
        for name, status, reason in cases}}}


def acceptance(tmp_path, baseline, *, zero_limit=2):
    path = "frontend/tests/e2e/leaf.spec.ts"
    save_text(tmp_path / path, "// frozen test")
    return FrozenAcceptance(tmp_path, "batch", [path], baseline, zero_limit=zero_limit), path


def test_candidate_rejects_session_regression_even_if_total_pass_count_improves(tmp_path):
    frozen, _ = acceptance(tmp_path, results(("session after reload", "passed", ""),
        ("create", "failed", "not visible"), ("save", "failed", "not saved")))
    candidate = results(("session after reload", "failed", "redirected to sign in"),
        ("create", "passed", ""), ("save", "passed", ""))
    build = Mock(return_value={"returncode": 0})
    with pytest.raises(ValueError, match="regressed"):
        frozen.evaluate(candidate, build)
    build.assert_not_called()
    assert read_artifact(tmp_path / ".arc/acceptance", "batch.json")["attempts"][0]["decision"] == "REJECTED"


def test_candidate_enforces_freeze_count_startup_and_zero_limit(tmp_path):
    frozen, path = acceptance(tmp_path, results(("create", "failed", "first")), zero_limit=1)
    build = Mock(return_value={"returncode": 0})
    assert frozen.evaluate(results(("create", "failed", "second")), build)["decision"] == "INTERMEDIATE"
    with pytest.raises(ValueError, match="No additional"):
        frozen.evaluate(results(("create", "failed", "third")), build)
    with pytest.raises(ValueError, match="inventory"):
        frozen.evaluate(results(("different test", "passed", "")), build)
    with pytest.raises(ValueError, match="skipped"):
        frozen.evaluate(results(("create", "skipped", "")), build)
    with pytest.raises(ValueError, match="missing execution"):
        frozen.evaluate({"leaf": {"errors": ["failed to start"]}}, build)
    with pytest.raises(ValueError, match="build failed"):
        frozen.evaluate(results(("create", "passed", "")), Mock(return_value={"returncode": 1, "output": "error"}))
    save_text(tmp_path / path, "// assertion removed")
    with pytest.raises(ValueError, match="Frozen acceptance"):
        frozen.evaluate(results(("create", "passed", "")), build)


def test_rejected_candidate_restores_deleted_files_and_removes_added_files(tmp_path):
    old = tmp_path / "frontend/src/old.ts"
    new = tmp_path / "frontend/src/new.ts"
    save_text(old, "export const stable = true;")
    files = FileTools(tmp_path, ["frontend"], stage="frontend")
    model = Mock()
    def respond(_instructions, _task):
        assert old.is_file() and not new.exists()
        return {"tool_calls": [{"tool": "edit_file", "path": "frontend/src/new.ts",
            "operation": "create", "new_content": "export const candidate = true;"}]}
    def reject():
        old.unlink()
        raise ValueError("candidate lost accepted behavior")
    model.generate_json.side_effect = respond
    with pytest.raises(AgentExhausted):
        run_file_agent(model, "Edit", {}, files, reject, 2, Mock(), "repair", protect_candidates=True)
    assert old.read_text(encoding="utf-8") == "export const stable = true;"
    assert not new.exists()
    failures = [json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / ".arc/failures").glob("*/failure.json")]
    assert len(failures) == 2
    assert all(row["deleted_files"] == ["frontend/src/old.ts"] for row in failures)


def test_coverage_and_test_revision_keep_original_given_when_then_and_diff(tmp_path):
    raw = {"id": "leaf", "description": "Preserve the Save name", "scenarios": [
        {"id": "s", "steps": [{"id": "x", "Given": "Record exists", "When": "Click Save", "Then": "Title is stored"}]}]}
    ui = {"steps": {"x": ["save"]}, "elements": {"save": {"type": "button", "prop": {"text": "Save"}}}}
    matrix = coverage_matrix(DesignPlan(raw), RequirementTree(raw), ui,
        {"steps": {"x": ["t"]}}, {"t": {"write": ["Record.title"]}})
    step = matrix["leaf"]["scenarios"]["s"]["steps"]["x"]
    assert (step["Given"], step["When"], step["Then"], step["db_writes"]) == (
        "Record exists", "Click Save", "Title is stored", ["Record.title"])
    assert step["ui_evidence"][0]["names"] == {"text": "Save"}
    path = matrix["leaf"]["suite"]
    write_revision(tmp_path, "batch", {path: b"before\n"}, {path: b"after\n"}, matrix, {"leaf": {"failed": 1}})
    recorded = json.loads((tmp_path / ".arc/acceptance/test_revisions.jsonl").read_text(encoding="utf-8"))
    assert "-before" in recorded["changes"][0]["diff"]
    assert "Click Save" in json.dumps(recorded["changes"][0]["source"])


def test_only_changed_app_ts7006_locations_are_repaired_and_rechecked(tmp_path, monkeypatch):
    relative = "frontend/src/App.tsx"
    save_text(tmp_path / relative, "const example = (value) => value;")
    files = FileTools(tmp_path, ["frontend"], stage="frontend")
    files.changed_paths.add(relative)
    diagnostic = "\n".join([relative + "(1,18): error TS7006: implicit any",
        relative + "(1,18): error TS1000: unrelated", "frontend/tests/spec.ts(1,3): error TS7006: test"])
    assert implicit_any_locations(files, diagnostic) == {relative: [[1, 18]]}
    invoke = Mock(return_value={"returncode": 0, "stdout": "1"})
    monkeypatch.setattr("infrastructure.shared.agent.type_repair.capture_process", invoke)
    check = Mock(side_effect=[{"returncode": 1, "output": diagnostic}, {"returncode": 0}])
    assert recheck_types(check, files)["returncode"] == 0
    assert check.call_count == 2 and invoke.call_count == 1
