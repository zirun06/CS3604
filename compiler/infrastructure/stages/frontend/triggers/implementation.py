"""Generate and review grouped acceptance suites, then integrate their interactions."""

from infrastructure.shared.agent.files import editable_application_path
from infrastructure.shared.agent.loop import AgentExhausted, run_file_agent
from infrastructure.shared.agent.type_repair import recheck_types
from infrastructure.shared.agent.implementation_batches import ImplementationBatches, passing_checks, require_any
from infrastructure.stages.frontend.ui.implementation import page_layout_signals
from infrastructure.shared.agent.tools import FileTools
from infrastructure.stages.frontend.triggers.acceptance import INSTRUCTIONS as TEST_INSTRUCTIONS, REVIEW_INSTRUCTIONS
from infrastructure.shared.agent.recovery import CandidateProgress, implementation_task, reject_paths, final_checks, complete_report
from infrastructure.stages.frontend.triggers.e2e_runtime import CONFIG, FIXTURE, prepare_e2e
from infrastructure.stages.frontend.triggers.testing import E2EChecks, test_path
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS, prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, require_green, test_path as ui_test_path
from infrastructure.stages.backend.context import related_schema
from infrastructure.stages.backend.runtime import api_test_paths
from infrastructure.stages.backend.testing import BackendChecks, require_green as require_backend_green
from infrastructure.stages.frontend.triggers.design import api_ids, trigger_obligations
from infrastructure.stages.frontend.triggers.scope import TriggerCheckFailure, model_context
from infrastructure.stages.frontend.triggers.acceptance_gate import (
    coverage_matrix, FrozenAcceptance, snapshot_tests, write_revision,
)
from infrastructure.stages.requirements.batching import DesignPlan
from infrastructure.utils.files import read_artifact
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json
from infrastructure.stages.frontend.ui.design import page_context, page_elements
from infrastructure.shared.project.git import checkpoint


def scenario_context(ui, design, rid):
    """Reference this requirement's triggers and directly involved pages only."""
    triggers = {tid: design["triggers"][tid] for tid in design["requirements"].get(rid, [])}
    elements = set(ui["requirements"].get(rid, []))
    for trigger in triggers.values():
        elements.add(trigger["source"])
        for action in trigger["action"]:
            if action["kind"] == "ui":
                elements.add(action["ui"])
    pages = {}
    for pid in ui["pages"]:
        if elements.intersection(page_elements(ui, pid)):
            pages[pid] = page_context(ui, pid)
    return {"page_subtrees": pages, "triggers": triggers}


def editable_runtime_path(output, path):
    """Allow evidence-driven database runtime repairs alongside application repairs."""
    if "/tests/" in path or path.startswith("backend/src/db/seeds/") or path == "backend/src/db/seed.ts":
        return False
    if editable_application_path(output, path):
        return True
    return (path.startswith("backend/src/db/") and path.endswith((".ts", ".sql"))
        and (output / path).is_file())


def test_run_status(result):
    """Pass every real failure to repair; do not guess its cause from error text."""
    try:
        require_stable_acceptance(result)
        return "GREEN"
    except ValueError:
        return "REPAIR_REQUIRED"


def require_stable_acceptance(result):
    require_green(result)
    if result.get("skipped") or result.get("flaky"):
        raise ValueError("Requirement acceptance includes skipped or unstable tests")


IMPLEMENT_INSTRUCTIONS = """Implement the interactions of all active entries in task.scenarios in the actual application.
Step 09's triggers are a reference prototype: preserve their requirement-defined behavior,
not a fixed handler/context ABI, event dispatcher, store or routing implementation.
Read the actual entrypoints, relevant components and supplied package/configuration first.
Use the project's framework and installed dependencies. You own component events, lifecycle
hooks, routing, state, input conversion, request construction and response integration.
The compiler does not regenerate App, route tables, handlers, stores or API clients.

Implement the full path: UI event -> actual input/object identity -> request params/query/
body/headers -> real backend API -> success/rejection response -> updated state and visible UI.
Use ordinary framework code: closures/callbacks, hooks, services or shared functions as
appropriate. You may implement several related reference triggers together in components
or helpers. No one-file-per-trigger rule, forced handle export, UiTriggerContext or central
registry is required. Keep code reusable and incrementally preserve previous requirements.

Preserve explicit original UI naming contracts during implementation and every repair:
labels, action names, headings, region names, required placeholders and semantic roles.
Keep wording, language, spelling and case unchanged; do not add prefixes, translate or
concatenate aliases. A required "Name" field stays "Name". Keep the visible label and
computed accessible name consistent; aria-label/aria-labelledby must not replace or extend
the required name. Original explicit requirements take precedence over generated design,
reference examples and existing incorrect code. Fix a naming violation in the application,
not by weakening an otherwise correct test. Unspecified wording remains your choice;
dynamic business names and user input must still reflect real data.

Before adding an event or effect, read the existing component and follow its current
UI -> callback/effect -> service -> HTTP call chain. Extend or reuse the existing owner
of that business operation. A new reference trigger ID does not require a new listener.
For a form, choose one submission owner; do not send the same mutation from both a
button's onClick and the form's onSubmit. Check bubbling handlers, parent callbacks,
native listeners and effects as well. Preserve submit-by-Enter and nested-icon clicks.
Clean up subscriptions, avoid repeated effect-driven mutations, and use operation-local
pending protection for rapid repeated submission when appropriate. Never use a global
URL-based deduplication cache to hide duplicate wiring or suppress legitimate operations.

For dynamic routes, use the actual router or application routing code to construct and
parse concrete parameters. Support direct entry, reload, navigation and back/forward as
required. On a protected route, when the original behavior requires session restoration,
await the session query before redirecting; anonymous routes stay usable when required.
Validate the load response and wait for required saved values before enabling an editor
so an in-flight load cannot overwrite a user's edits. Identify a clicked row from that row's actual data/callback, not a shared global
example object or event.target.value from an arbitrary nested icon/span. Carry the selected
identity through the URL/request/state consistently; encode URL values correctly.

Use framework-native form bindings. An input updates only its actual value field; other
variables in element.data may be read dependencies. Choose appropriate types/conversions
for numbers, dates, booleans, arrays and other controls. State changes, asynchronous loads,
reset/cancel and object switches must update the displayed controls. Do not rely on an
automatic compiler input/change handler or require defaultValue/defaultChecked everywhere.

Call the canonical backend interfaces with real HTTP, using existing request helpers or
new shared application helpers as appropriate. Preserve previous API request cases.
Respect response status/body/headers, empty bodies and browser-managed cookies.
Type response collections and handle missing optional fields before using array methods.
Use the accepted result or reload affected data after saving; cancel returns to its specified
destination without persisting edits. Do not
manually set browser Cookie headers or read HttpOnly credentials. Register event handling
only once; preserve action ordering, guards, rejection behavior and failure-without-writes.
Keep actual loaded data associated with the requested object. Initialize safe unloaded
state and requirement defaults; never seed UI state from reference images/test records.
Build edit drafts from real loaded objects and cancel to their snapshots. Handle expected
errors visibly and prevent stale requests from overwriting a later selection/result.

Only each active scenario's target_trigger_ids belong to this implementation task. Other controls on supplied
pages are context, not a demand to build future workflows. Required entry/loading behavior
should be explicitly associated by step 09. Read missing designs/sources on demand; do not
recursively implement all mount/navigation behavior of every reachable page. Preserve any
previously working supporting behavior. If a necessary dependency is missing, implement
only the minimal behavior needed for this requirement and explain it in diagnosis.

Preserve selectors and the presentation-test adapter in frontend/src/ui-runtime.ts.
presentationData exposes declared values to display tests without owning application state;
isPresentationTest identifies explicit display-only previews. Keep their data/effects
isolated from real API loading. Normal browser E2E must use real APIs and state; never
recognize its fixtures, fabricate success or hardcode expected responses.

Use task.application_entrypoints for application integration and task.backend_entrypoints
when backend wiring repairs are necessary. Only application sources are writable during
implementation. All test suites, original designs and shared test tools are read-only. A test mismatch must be reported
with original requirement evidence for a separate test review.
When startup evidence points into existing database runtime/SQL, repair those files too.
Preserve the declared schema, constraints, previous tables and requirement-defined seed
data; correct their executable implementation rather than removing required guarantees.
Do not edit generated tests to repair application failures or change expected behavior.
The gate compiles and runs current/accepted browser scenarios, affected backend HTTP suites,
UI presence regression and final builds. Return ordinary edit_file calls; no path metadata
or placeholder files for reference trigger IDs are required.

For each failure, diagnose whether it comes from the requirement/test, application,
backend/database startup, wiring, or environment, using actual logs and relevant files.
Server startup, network and browser runtime failures are real repair targets, not invalid
tests or successful RED. Read the failing source and repair its cause within tool scope;
do not weaken assertions, replace real requests with mocks, or relabel failures as passes.
If a necessary correction is outside tool scope, explain the exact blocker in diagnosis.
"""


def run_trigger_tdd(arc_dir, tree, schema, backend, ui, design, images, contexts,
        model, console, report, max_turns=10):
    """Implement page- and capability-related requirements as real-app TDD groups."""
    output = arc_dir.parent.resolve()
    plan = DesignPlan(read_artifact(arc_dir, "requirements.json"))
    matrix = coverage_matrix(plan, tree, ui, design, {
        tid: trigger_obligations(trigger, backend) for tid, trigger in design["triggers"].items()},
        read_artifact(arc_dir, "db_obligations.json"))
    save_json(arc_dir / "acceptance" / "coverage.json", matrix)
    prepare_frontend(output)
    prepare_e2e(output, backend)
    console.show("E2E preparation | Dependencies", "Install workspace dependencies and Chromium. Each browser run owns a new real test database; production data is not used.")
    install_dependencies(output)
    checks = E2EChecks(output)
    checks.install_browser()
    checkpoint(output, stage="10", task="runtime", action="Prepare real-app browser tests and isolated database fixtures",
        details={"pages": list(ui["pages"]), "trigger_ids": list(design["triggers"])})
    ui_checks = FrontendChecks(output)
    report["status"] = "IMPLEMENTING"
    save_json(arc_dir / "frontend_e2e.json", report)
    baseline_files = [ui_test_path(pid) for pid in ui["pages"]
        if (output / ui_test_path(pid)).is_file()]

    def baseline_gate():
        """Check inherited sources independently of the next business requirement."""
        evidence = {"typecheck": checks.typecheck(baseline_files)}
        try:
            if evidence["typecheck"]["returncode"]:
                raise ValueError(evidence["typecheck"]["output"])
            if baseline_files:
                evidence["ui"] = ui_checks.tests(baseline_files)
                require_green(evidence["ui"])
        except (ValueError, RuntimeError) as error:
            raise TriggerCheckFailure("Application baseline failed: " + str(error), evidence) from error
        return evidence

    report["baseline"] = {"status": "CHECKING"}
    with implementation_task(output, report["baseline"], console, "12 / baseline"):
        try:
            baseline = baseline_gate()
        except (ValueError, RuntimeError) as error:
            workspace = FileTools(output, ["frontend", "backend"], requirements=tree.leaves,
                stage="frontend", files=[*APPLICATION_ENTRYPOINTS, "frontend/src/ui-runtime.ts"],
                allow_write=lambda path: editable_runtime_path(output, path))
            repair = run_file_agent(model,
                "Restore the existing application's compilation and display behavior before business work. "
                "Read the actual entrypoints and failing sources. Use native framework routing/state/events; "
                "do not recreate a compiler-owned dispatcher, global input capture or design interpreter. "
                "Preserve earlier pages, selectors and behavior. This is a shared baseline repair, not "
                "implementation of all future triggers. Use the supplied requirement/design evidence. "
                "Shared presentation/test infrastructure is read-only. Repair the actual application.",
                {"task": "application_baseline", "application_entrypoints": list(APPLICATION_ENTRYPOINTS),
                    "requirements": contexts, "ui_design": ui},
                workspace, baseline_gate, max_turns, console, "Application baseline repair",
                feedback=getattr(error, "feedback", {"error": str(error)}),
                feedback_filter=None)
            baseline = repair["checks"]
            report["baseline"]["repair_turns"] = repair["turns"]
        report["baseline"].update(status="GREEN", checks=baseline)
    save_json(arc_dir / "frontend_e2e.json", report)
    values, signals = {}, {}
    backend_report = arc_dir / "backend_tdd.json"
    implemented_apis = read_artifact(arc_dir, backend_report.name).get("apis", {}) if backend_report.is_file() else None
    for rid in tree.leaves:
        unavailable = design.get("unavailable", {}).get(rid)
        if unavailable:
            report["requirements"][rid] = {"status": "FAILED", "requirements": [rid], "error": unavailable}
            continue
        context = scenario_context(ui, design, rid)
        tids = set(context["triggers"])
        pages = context["page_subtrees"]
        if not pages:
            report["requirements"][rid] = {"status": "FAILED", "requirements": [rid], "triggers": sorted(tids),
                "error": "No UI interface available for requirement acceptance; not verified"}
            continue
        called = {aid for trigger in context["triggers"].values() for aid in api_ids(trigger)}
        blocked = sorted(aid for aid in called if implemented_apis is not None
            and implemented_apis.get(aid, {}).get("status") != "GREEN")
        if blocked:
            report["requirements"][rid] = {"status": "FAILED", "requirements": [rid],
                "error": "Missing accepted API implementation", "apis": blocked}
            continue
        context.update(requirement=contexts[rid], target_trigger_ids=sorted(tids),
            obligations={tid: trigger_obligations(trigger, backend) for tid, trigger in context["triggers"].items()},
            backend_apis={aid: backend["apis"][aid] for aid in sorted(called)})
        values[rid] = {**model_context(context), "test_path": test_path(rid),
            "schema": related_schema(schema, context["backend_apis"].values()), "acceptance_items": matrix[rid]["scenarios"]}
        signals[rid] = {*(f"page:{pid}" for pid in pages), *(f"trigger:{tid}" for tid in tids),
            *(f"api:{aid}" for aid in called),
            *(key for pid in pages for key in page_layout_signals(ui, pid))}
    batches = ImplementationBatches(arc_dir, "10", console).register(values, {rid: [rid] for rid in values}, signals)
    reference = ["frontend/src/ui-runtime.ts", CONFIG, FIXTURE, "backend/tests/support/context.ts",
        *APPLICATION_ENTRYPOINTS, "frontend/package.json", "frontend/tsconfig.json", "frontend/vite.config.ts",
        "backend/src/db/initialize.ts", "backend/src/db/seed.ts", "backend/src/db/client.ts",
        "backend/src/api/register.ts", "backend/src/api/types.ts", "backend/src/app.ts"]

    def process(batch, entry):
        regression = [test_path(rid) for rid in batches.accepted]
        paths = [test_path(rid) for rid in batch.units]
        previous = {path: (output / path).read_bytes() for path in paths if (output / path).is_file()}
        scenarios = {rid: values[rid] for rid in batch.units}
        pages = {pid for context in scenarios.values() for pid in context["page_subtrees"]}
        called = {aid for context in scenarios.values() for aid in context["backend_apis"]}
        ui_files = [ui_test_path(pid) for pid in sorted(pages) if (output / ui_test_path(pid)).is_file()]
        tables = {name for context in scenarios.values() for name in context["schema"]}
        db_files = [f"backend/src/db/tables/{name}.sql" for name in sorted(tables)] + [
            f"backend/src/db/seeds/{name}.sql" for name in sorted(tables)
            if (output / f"backend/src/db/seeds/{name}.sql").is_file()]
        task = batches.context(batch, {"scenarios": scenarios,
            "application_entrypoints": list(APPLICATION_ENTRYPOINTS),
            "backend_entrypoints": {"registry": "backend/src/api/register.ts",
                "app": "backend/src/app.ts", "server": "backend/src/server.ts"}})

        def authorship_gate(units):
            selected = [test_path(rid) for rid in units]
            compiled = checks.typecheck(selected, full_source=False)
            if compiled["returncode"]:
                raise TriggerCheckFailure("Acceptance test compilation failed", compiled)
            def observe(rid):
                if not (output / test_path(rid)).is_file():
                    raise ValueError(f"Missing canonical acceptance test for {rid}")
                try:
                    behavior = checks.tests([test_path(rid)])
                except (ValueError, RuntimeError) as error:
                    behavior = {"returncode": 1, "output": str(error), "errors": [str(error)]}
                return {"behavior": behavior, "status": test_run_status(behavior)}
            passed, rejected = passing_checks(units, observe, lambda _: None)
            require_any(passed, rejected)
            return {"typecheck": compiled, "passed": passed, "rejected": rejected}

        def author(units, instructions, phase, feedback=None):
            selected = [test_path(rid) for rid in units]
            workspace = FileTools(output, ["frontend", "backend"], requirements=batches.requirement_ids(units),
                stage="frontend", writable=selected, files=[*paths, *reference, *db_files])
            scoped = {**task, "units": list(units), "scenarios": {rid: scenarios[rid] for rid in units},
                "test_paths": selected}
            return run_file_agent(model, instructions, scoped, workspace, lambda: authorship_gate(units),
                max_turns, console, batch.id + " / " + phase, feedback=feedback, test_phase=phase, batch_limits=True)

        generated = author(batch.units, TEST_INSTRUCTIONS, "generation")
        candidate = dict(generated["checks"]["passed"])
        rejected = dict(generated["checks"]["rejected"])
        needs_review = tuple(rid for rid, record in candidate.items() if record["status"] != "GREEN")
        review = None
        if needs_review:
            reviewed_paths = [test_path(rid) for rid in needs_review]
            before = snapshot_tests(output, reviewed_paths)
            diagnostics = {rid: candidate[rid]["behavior"] for rid in needs_review}
            review = author(needs_review, REVIEW_INSTRUCTIONS, "review",
                diagnostics)
            write_revision(output, batch.id, before, snapshot_tests(output, reviewed_paths),
                {rid: matrix[rid] for rid in needs_review}, diagnostics)
            for rid in needs_review:
                candidate.pop(rid)
            candidate.update(review["checks"]["passed"])
            rejected.update(review["checks"]["rejected"])
        require_any(candidate, rejected)
        frozen = FrozenAcceptance(output, batch.id, [*regression, *[test_path(rid) for rid in candidate]],
            {rid: data["behavior"] for rid, data in candidate.items()})

        workspace = FileTools(output, ["frontend", "backend"], requirements=batches.requirement_ids(candidate),
            stage="frontend", files=[*paths, *ui_files, *reference, *db_files, *api_test_paths(output, called)],
            allow_write=lambda path: editable_runtime_path(output, path))

        def implementation_gate(*, existing=False):
            frozen.verify_files()
            compiled = recheck_types(lambda: checks.typecheck([*[test_path(rid) for rid in candidate], *regression]), workspace)
            if compiled["returncode"]:
                raise TriggerCheckFailure("Application compilation failed", compiled)
            if any(path.startswith("backend/src/") for path in workspace.changed_paths):
                api_checks = BackendChecks(output)
                checked = recheck_types(api_checks.typecheck, workspace)
                if checked["returncode"]:
                    raise TriggerCheckFailure("Backend compilation failed", checked)
                suites = api_test_paths(output, backend["apis"])
                if suites:
                    require_backend_green(api_checks.tests(suites))
            if regression:
                require_stable_acceptance(checks.tests(regression))
            if ui_files:
                require_green(ui_checks.tests(ui_files))
            observed = {rid: checks.tests([test_path(rid)]) for rid in candidate}
            decision = frozen.evaluate(observed, checks.build, existing=existing)
            passed, failed = passing_checks(candidate, observed.__getitem__, require_stable_acceptance)
            if not passed:
                raise CandidateProgress(decision)
            return {"typecheck": compiled, "passed": passed, "rejected": failed}

        implemented = None
        if all(record["status"] == "GREEN" for record in candidate.values()):
            try:
                implemented = {"turns": 0, "checks": implementation_gate(existing=True)}
            except (ValueError, RuntimeError):
                pass
        if implemented is None:
            scoped = {**task, "units": list(candidate), "scenarios": {rid: scenarios[rid] for rid in candidate}}
            try:
                implemented = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, scoped, workspace, implementation_gate,
                    max_turns, console, batch.id + " / interaction implementation",
                    feedback={rid: data["behavior"] for rid, data in candidate.items()},
                    batch_limits=True, protect_candidates=True)
            except AgentExhausted as error:
                # A failed repair must not discard requirements that were already green.
                if not any(record["status"] == "GREEN" for record in candidate.values()):
                    raise
                retained = implementation_gate(existing=True)
                implemented = {"turns": error.turns, "checks": retained}
        results = implemented["checks"]
        rejected.update(results["rejected"])
        for rid in rejected:
            relative = test_path(rid)
            rejected[rid]["test_archive"] = reject_paths(output, batch.id + " / " + rid, previous, [relative])
        entry["rejected_checks"] = rejected
        return {rid: {"requirements": [rid], "triggers": values[rid]["target_trigger_ids"],
            "target_triggers": values[rid]["target_trigger_ids"], "test_path": test_path(rid),
            "steps": tree.own_steps[rid], "passed": evidence["passed"],
            "test_turns": generated["turns"], "review_turns": review["turns"] if review and rid in needs_review else 0,
            "implementation_turns": implemented["turns"]} for rid, evidence in results["passed"].items()}

    report["requirements"].update(batches.run(process))
    return verify_frontend(arc_dir, tree, backend, ui, console, report)


def verify_frontend(arc_dir, tree, backend, ui, console, report):
    """Check current files after the requirement implementation pass."""
    output = arc_dir.parent.resolve()
    checks = E2EChecks(output)
    ui_checks = FrontendChecks(output)
    console.show("Final frontend verification", "Run requirement acceptance suites, UI regression, backend checks and builds against current sources.")
    files = [test_path(rid) for rid in tree.leaves
        if (output / test_path(rid)).is_file()]
    ui_files = [ui_test_path(pid) for pid in ui["pages"] if (output / ui_test_path(pid)).is_file()]
    api_checks = BackendChecks(output)
    api_files = api_test_paths(output, backend["apis"])
    verification = final_checks(console,
        typecheck=(lambda: checks.typecheck(files), None),
        e2e=(lambda: checks.tests(files), require_stable_acceptance)) if files else final_checks(console,
            typecheck=(lambda: checks.typecheck([]), None))
    if ui_files:
        verification.update(final_checks(console, ui=(lambda: ui_checks.tests(ui_files), require_green)))
    if ui["pages"]:
        verification.update(final_checks(console, render=(lambda: checks.render(ui["pages"]), require_green)))
    verification.update(final_checks(console,
        backend_typecheck=(api_checks.typecheck, None),
        backend_tests=(lambda: api_checks.tests(api_files), require_backend_green if api_files else None),
        build=(checks.build, None)))
    final = verification.get("e2e", {}).get("result") or {}
    ui_final = verification.get("ui", {}).get("result") or {}
    accepted = [rid for rid in tree.leaves if report["requirements"].get(rid, {}).get("status") == "GREEN"]
    implemented = {tid for rid in accepted for tid in report["requirements"][rid].get("target_triggers", [])}
    report["summary"] = {"requirements": len(accepted), "triggers": len(implemented),
        "e2e_tests": final.get("passed", 0), "ui_tests": ui_final.get("passed", 0),
        "failed": final.get("failed", 0) + ui_final.get("failed", 0)}
    complete_report(report, report["requirements"].values(), verification)
    save_json(arc_dir / "frontend_e2e.json", report)
    return report
