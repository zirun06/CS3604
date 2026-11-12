"""Frontend representation, publication, lifecycle dependencies and acceptance regressions."""
from tool_fixtures import propose_files

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import Mock

from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.frontend.context import load_ui_context
from infrastructure.stages.frontend.ui.design import apply_proposal, empty_design, page_context, normalize_design
from infrastructure.stages.frontend.ui.synthesis import synthesize_ui
from infrastructure.stages.frontend.ui.testing import presentation_run_status
from infrastructure.stages.frontend.triggers.design import empty_triggers, trigger_obligations
from infrastructure.stages.frontend.triggers.implementation import scenario_context, test_run_status as e2e_run_status
from infrastructure.utils.files import save_json, save_text


def node(kind, parent, data=(), mode=(), **props):
    return {"type": kind, "parent": parent, "data": list(data), "mode": list(mode), "prop": props}


def binding(dtype, initial, source):
    return {"dtype": dtype, "constraints": [], "initial": initial, "source": source}


def frontend_fixture():
    """A shared editor navigates to a later requirement's read-only summary page."""
    raw = {"id": "ROOT", "name": "Notes", "children": [
        {"id": rid, "name": rid, "description": description, "scenarios": [{"id": "SCN-" + rid,
            "steps": [{"id": "STEP-" + rid, "Given": "Existing notes in the database", "When": behavior, "Then": outcome}]}]}
        for rid, description, behavior, outcome in (
            ("REQ-A", "Save a note then navigate to /summary; empty text is rejected without writes.", "Enter text and submit the editor", "Show the updated count after navigation and refresh; show an error on rejection"),
            ("REQ-B", "Use the same editor and API to save another note.", "Enter another note and save", "Persist it and display the summary"),
            ("REQ-C", "The /summary page displays the count on every entry and refresh without writes.", "Open or refresh /summary", "Display the persisted count and allow returning to the editor"))]}
    tree = RequirementTree(raw)
    ui = {"pages": {
        "editor": {"name": "Editor", "route": "/", "root": "UI-EDITOR", "images": [], "fixtures": {"default": {}, "rejected": {"form.errorVisible": True, "form.error": "Text required"}}},
        "summary": {"name": "Summary", "route": "/summary", "root": "UI-SUMMARY", "images": [], "fixtures": {"default": {}, "loaded": {"summary.count": "2"}}}},
        "elements": {
            "UI-EDITOR": node("page", None), "UI-FORM": node("form", "UI-EDITOR"),
            "UI-TEXT": node("input", "UI-FORM", ["form.text"], ["user_write"], label="Note", input_type="text"),
            "UI-SAVE": node("button", "UI-FORM", text="Save"),
            "UI-ERROR": node("alert", "UI-EDITOR", ["form.error"], visible={"var": "form.errorVisible", "equals": True}),
            "UI-SUMMARY": node("page", None), "UI-COUNT": node("text", "UI-SUMMARY", ["summary.count"]),
            "UI-BACK": node("link", "UI-SUMMARY", text="Back", href="/")},
        "bindings": {"form.text": binding("string", "", "Native note input"), "form.error": binding("string", "", "API rejection message"),
            "form.errorVisible": binding("boolean", False, "Whether to show rejection"), "summary.count": binding("string", "Loading", "Count API response")},
        "requirements": {"ROOT": [], "REQ-A": ["UI-EDITOR", "UI-FORM", "UI-TEXT", "UI-SAVE", "UI-ERROR"],
            "REQ-B": ["UI-EDITOR", "UI-FORM", "UI-TEXT", "UI-SAVE", "UI-ERROR"], "REQ-C": ["UI-SUMMARY", "UI-COUNT", "UI-BACK"]},
        "steps": {"STEP-REQ-A": ["UI-TEXT", "UI-SAVE", "UI-ERROR"], "STEP-REQ-B": ["UI-TEXT", "UI-SAVE"], "STEP-REQ-C": ["UI-COUNT", "UI-BACK"]}}
    interactions = {'triggers': {'TR-INPUT': {'source': 'UI-TEXT',
                               'event': 'change',
                               'guard': None,
                               'read': [],
                               'action': [{'kind': 'ui',
                                           'description': 'Write input.value into form.text',
                                           'ui': 'UI-TEXT'}],
                               'write': ['form.text']},
                  'TR-SAVE': {'source': 'UI-FORM',
                              'event': 'submit',
                              'guard': None,
                              'read': ['form.text'],
                              'action': [{'kind': 'api',
                                          'api': 'API-SAVE',
                                          'description': 'POST form.text as body.text'},
                                         {'kind': 'ui',
                                          'description': 'On SAVE status 400 show its error message and set '
                                                         'form.errorVisible=true',
                                          'ui': 'UI-FORM'},
                                         {'kind': 'ui',
                                          'description': 'On SAVE status 200 navigate to summary',
                                          'ui': 'UI-SUMMARY'}],
                              'write': ['form.error', 'form.errorVisible']},
                  'TR-COUNT': {'source': 'UI-SUMMARY',
                               'event': 'mount',
                               'guard': None,
                               'read': [],
                               'action': [{'kind': 'api',
                                           'api': 'API-COUNT',
                                           'description': 'GET the current count'},
                                          {'kind': 'ui',
                                           'description': 'Write String(COUNT response.body.count) to '
                                                          'summary.count',
                                           'ui': 'UI-SUMMARY'}],
                               'write': ['summary.count']}},
     'requirements': {'ROOT': [],
                      'REQ-A': ['TR-INPUT', 'TR-SAVE'],
                      'REQ-B': ['TR-INPUT', 'TR-SAVE'],
                      'REQ-C': ['TR-COUNT']},
     'steps': {'STEP-REQ-A': ['TR-INPUT', 'TR-SAVE'],
               'STEP-REQ-B': ['TR-INPUT', 'TR-SAVE'],
               'STEP-REQ-C': ['TR-COUNT']}}
    backend = {"requirements": {"ROOT": [], "REQ-A": ["API-SAVE"], "REQ-B": ["API-SAVE"], "REQ-C": ["API-COUNT"]},
        "apis": {"API-SAVE": {"read": [], "write": ["Note.id", "Note.text"]}, "API-COUNT": {"read": ["Note.id", "Note.text"], "write": []}}}
    obligations = {"requirements": {rid: {"read": [] if rid != "REQ-C" else ["Note.id", "Note.text"],
        "write": ["Note.id", "Note.text"] if rid in {"REQ-A", "REQ-B"} else []} for rid in tree.requirements}}
    return raw, tree, ui, interactions, backend, obligations


class FrontendFlow(unittest.TestCase):
    def setUp(self):
        self.raw, self.tree, self.ui, self.interactions, self.backend, self.obligations = frontend_fixture()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.arc = self.output / ".arc"

    def test_ui_design_accepts_model_metadata_without_type_or_semantic_gates(self):
        ui = deepcopy(self.ui)
        ui["bindings"]["form.text"]["dtype"] = "custom"
        ui["bindings"]["form.text"]["source"] = 123
        ui["pages"]["summary"]["route"] = "/"
        normalize_design(ui, self.tree)
        self.assertEqual(ui["bindings"]["form.text"]["source"], 123)









    def check_event_creation(self, early_green=False, needs_repair=False, partial_batch=False, preexisting=False, backend_repair=False, backend_fails_once=False):
        """Run the real orchestration with fake browser reports and model edits."""
        from unittest.mock import patch
        from infrastructure.shared.agent.tools import FileTools
        from infrastructure.shared.project.entrypoints import selected_path, remember_path
        from infrastructure.shared.project.initialize import initialize_project
        from infrastructure.stages.frontend.triggers import implementation
        initialize_project(self.output)
        existing_path = "frontend/src/custom/input.ts"
        if preexisting:
            remember_path(self.output, "trigger", "TR-INPUT", existing_path)
            save_text(self.output / existing_path, "export function handle() { /* existing */ }")
        api_paths = {}
        backend_suites = []
        for aid in self.backend["apis"]:
            api_paths[aid] = f"backend/src/handlers/{aid}.ts"
            remember_path(self.output, "api", aid, api_paths[aid])
            save_text(self.output / api_paths[aid], "export function handle() {}")
            suite = f"backend/tests/{aid}.test.ts"
            remember_path(self.output, "backend_test", aid, suite)
            save_text(self.output / suite, "frozen API assertions")
            backend_suites.append(suite)
        save_text(self.output / "frontend/src/features/other-page-helper.ts", "export const helper = 1;")
        save_text(self.output / "backend/src/features/other-api-helper.ts", "export const helper = 2;")
        for pid in self.ui["pages"]:
            workspace = FileTools.for_target(self.output, "page", pid)
            workspace.state()
            workspace.execute(propose_files(self.output, [{"path": f"frontend/src/screens/{pid}.tsx",
                "content": "export function Page() {return null;}"}])["tool_calls"])
        implementation_calls = []
        repaired = False
        def generate(instructions, payload):
            nonlocal repaired
            task = payload["task"]
            if "file_target" not in task:
                implementation_calls.append(deepcopy(payload))
                self.assertEqual(set(task["triggers"]), set(self.interactions["triggers"]))
                for eid in self.interactions["triggers"]:
                    path = selected_path(self.output, "trigger", eid)
                    self.assertTrue(payload["files"][path]["writable"], eid)
                self.assertNotIn("frontend/tests/ui/editor.spec.ts", payload["files"])
                for pid in ("editor", "summary"):
                    self.assertTrue(payload["files"][f"frontend/src/screens/{pid}.tsx"]["writable"])
                for path in api_paths.values():
                    self.assertTrue(payload["files"][path]["writable"])
                for path in ("frontend/src/features/other-page-helper.ts", "backend/src/features/other-api-helper.ts", "backend/src/server.ts"):
                    self.assertNotIn(path, payload["files"])
                self.assertTrue(payload["files"]["frontend/src/style.css"]["writable"])
                if len(implementation_calls) == 1:
                    ids = sorted(tid for tid, path in task["implementation_paths"].items()
                        if payload["files"][path]["content"] is None)
                    self.assertEqual(set(ids), set(self.interactions["triggers"]) - ({"TR-INPUT"} if preexisting else set()))
                    if partial_batch:
                        ids = ids[:-1]
                    edits = [{"path": task["implementation_paths"][tid],
                        "content": "export function handle() {}"} for tid in ids]
                    if backend_repair:
                        edits.append({"path": api_paths["API-SAVE"], "content": "export function handle() { /* fixed integration */ }"})
                    return propose_files(self.output, edits)
                if partial_batch:
                    self.assertIn("Create all supplied trigger files", payload["feedback"][0]["error"])
                    missing = [path for path in task["implementation_paths"].values()
                        if payload["files"][path]["content"] is None]
                    self.assertEqual(len(missing), 1)
                    return propose_files(self.output, [{"path": missing[0], "content": "export function handle() {}"}])
                if backend_fails_once:
                    self.assertEqual(payload["feedback"][0]["checks"]["backend_tests"]["returncode"], 1)
                    self.assertTrue(payload["files"][backend_suites[0]]["writable"])
                    return propose_files(self.output, [{"path": api_paths["API-SAVE"], "content": "export function handle() { /* API regression repaired */ }"}])
                repaired = True
                return propose_files(self.output, [{"path": selected_path(self.output, "trigger", "TR-INPUT"),
                    "content": "export function handle() { /* repaired */ }"}])
            creation = task["file_target"]
            self.assertEqual(creation["kind"], "e2e_test")
            for pid in task["page_subtrees"]:
                self.assertTrue(payload["files"][f"frontend/src/screens/{pid}.tsx"]["writable"])
            self.assertEqual(task["max_tests"], 2)
            for aid in task["backend_apis"]:
                self.assertTrue(payload["files"][api_paths[aid]]["writable"])
            self.assertFalse(payload["files"]["frontend/src/ui-runtime.ts"]["writable"])
            utilities = payload["files"]["backend/tests/support/context.ts"]
            self.assertFalse(utilities["writable"])
            self.assertIn("export function fixturePasswordHash(password: string): string", utilities["content"])
            path = f"{creation['directory']}/chosen/{creation['id']}.spec.ts"
            return propose_files(self.output, [{"path": path, "content": "export function handle() {}"}])
        checks, api_checks = Mock(), Mock()
        checks.typecheck.return_value = {"returncode": 0, "output": "compiled"}
        checks.build.return_value = {"returncode": 0, "output": "built"}
        green = {"returncode": 0, "output": "passed", "passed": 1, "failed": 0,
            "skipped": 0, "flaky": 0, "errors": [], "failures": []}
        api_checks.typecheck.return_value = {"returncode": 0, "output": "compiled backend"}
        api_checks.tests.return_value = {"returncode": 0, "tests": 2, "pass": 2, "fail": 0, "output": "API regression passed"}
        if backend_fails_once:
            api_checks.tests.side_effect = [
                {"returncode": 1, "tests": 2, "pass": 1, "fail": 1, "output": "Assertion failed: " + backend_suites[0]},
                api_checks.tests.return_value, api_checks.tests.return_value]
        def test_events(files):
            if early_green or (all(selected_path(self.output, "trigger", eid) for eid in self.interactions["triggers"])
                    and (not needs_repair or repaired)):
                return green
            return {**green, "returncode": 1, "passed": 0, "failed": 1,
                "failures": ["expect(received).toBe(expected)"]}
        checks.tests.side_effect = test_events
        backend = deepcopy(self.backend)
        for aid, api in backend["apis"].items():
            api["signature"] = {"method": "POST", "path": "/api/" + aid, "name": aid}
        with patch.object(implementation, "install_dependencies"), \
                patch.object(implementation, "E2EChecks", return_value=checks), \
                patch.object(implementation, "BackendChecks", return_value=api_checks) as backend_checks:
            report = implementation.run_trigger_tdd(self.arc, self.tree, {"entities": {}},
                backend, self.ui, self.interactions, {},
                {rid: {"id": rid} for rid in self.tree.leaves}, Mock(generate_json=generate),
                Mock(), {"requirements": {}}, max_turns=2)
        self.assertEqual(report["status"], "GREEN")
        self.assertEqual(set(implementation_calls[0]["task"]["implementation_paths"]),
            {"TR-COUNT", "TR-INPUT", "TR-SAVE"})
        self.assertEqual(len(implementation_calls), 2 if needs_repair or partial_batch or backend_fails_once else 1)
        self.assertEqual(report["requirements"]["REQ-A"]["implementation_turns"],
            2 if needs_repair or partial_batch or backend_fails_once else 1)
        if early_green:
            self.assertEqual(selected_path(self.output, "trigger", "TR-COUNT"), "frontend/src/deleted.ts")
        if preexisting:
            self.assertEqual(selected_path(self.output, "trigger", "TR-INPUT"), existing_path)
            self.assertEqual((self.output / existing_path).read_text(), "export function handle() { /* existing */ }")
        self.assertEqual(report["requirements"]["REQ-B"]["implementation_turns"], 0)
        self.assertIn("chosen/REQ-A.spec.ts", report["requirements"]["REQ-A"]["test_path"])
        # Three test-generation runs, one batch acceptance, final full regression;
        # failed batch acceptance adds exactly one repair regression.
        self.assertEqual(checks.tests.call_count, 6 if needs_repair else 5)
        self.assertEqual(checks.typecheck.call_count, 6 if needs_repair or backend_fails_once else 5)
        if backend_repair:
            self.assertEqual(backend_checks.call_count, 3 if backend_fails_once else 2)
            self.assertTrue(all(call.args == (self.output.resolve(),) for call in backend_checks.call_args_list))
            self.assertTrue(all(call.args == (backend_suites,) for call in api_checks.tests.call_args_list))
            self.assertEqual((self.output / "frontend/src/features/other-page-helper.ts").read_text(), "export const helper = 1;")
            self.assertEqual((self.output / "backend/src/features/other-api-helper.ts").read_text(), "export const helper = 2;")
        else:
            backend_checks.assert_called_once_with(self.output.resolve())
        self.assertEqual(report["summary"]["ui_tests"], 0)
        self.assertEqual(checks.tests.call_args.args[0],
            [report["requirements"][rid]["test_path"] for rid in self.tree.leaves])










    def test_presentation_loader_has_no_report_policy(self):
        save_json(self.arc / "requirements.json", self.raw)
        save_json(self.arc / "visual_analysis.json", {})
        tree, images, contexts = load_ui_context(self.arc, self.output)
        self.assertEqual(tree.leaves, self.tree.leaves)
        self.assertEqual(images, {})
        self.assertNotIn("concatenated_steps", contexts["REQ-A"])


    def test_trigger_db_effects_are_derived_without_frontend_coverage_validation(self):
        from infrastructure.stages.frontend.triggers.design import apply_decomposition
        trigger = deepcopy(self.interactions["triggers"]["TR-SAVE"])
        trigger["action"] = [{"kind": "api", "api": "API-COUNT", "description": "Read count"}]
        result = apply_decomposition(empty_triggers(self.tree),
            {"triggers": {"T": trigger}, "requirement_triggers": ["T"], "step_triggers": {}}, "REQ-A")
        self.assertEqual(trigger_obligations(result["triggers"]["T"], self.backend),
            {"read": ["Note.id", "Note.text"], "write": []})
        self.assertEqual(result["triggers"]["T"]["read"], ["form.text"])





    def test_backend_only_requirements_need_no_frontend_triggers(self):
        ui = normalize_design(empty_design(), self.tree)
        triggers = empty_triggers(self.tree)
        self.assertEqual(scenario_context(ui, triggers, "REQ-A")["triggers"], {})




if __name__ == "__main__":
    unittest.main()
