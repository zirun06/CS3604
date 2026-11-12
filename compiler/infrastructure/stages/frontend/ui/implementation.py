"""Implement complete page groups and retain independently verified pages."""

from pathlib import Path

from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.implementation_batches import ImplementationBatches, passing_checks, require_any
from infrastructure.shared.agent.feedback import CheckFailure
from infrastructure.shared.agent.recovery import reject_paths, final_checks, complete_report
from infrastructure.shared.agent.files import editable_application_path
from infrastructure.stages.frontend.ui.design import owners, page_context, page_elements
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS, prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, existence_suite, require_green, test_path
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import read_artifact, save_json, save_text
from infrastructure.shared.project.git import checkpoint

INSTRUCTIONS = """Implement every complete page in task.pages, including the UI of all its owning requirements.
Use task.requirement_evidence for exact names and behavior. Implement shared layouts once.
Read existing related components before editing and preserve all previously accepted UI and data bindings.
Read the supplied package/configuration and actual source to use the project's technology
stack. Read related files and incrementally edit or create components inside the frontend scope, using exports, props and
state appropriate to the actual components. The design is a
reference prototype, not a fixed executable host or mandatory component API.

You own the application entrypoints, routing, component composition and state bindings.
Read task.application_entrypoints as needed and incrementally connect these pages to the
existing application. Preserve all earlier routes/pages/exports and their behavior; never
rebuild the application with only this page. Support parameterized routes using the actual
router/framework or appropriate application code. Do not require a dynamic route pattern
to equal the literal browser pathname. Route metadata describes intended navigation.

Choose component-local state, a shared store or another appropriate mechanism. Initialize
safe unloaded values and explicit requirement defaults in application code; never manufacture
loaded business objects from reference images. element.data declares variables, types and
constraints, not a global store or an instruction to write one input value into every variable.
Use framework-native bindings/events. Controlled or uncontrolled fields are implementation
choices, but actual state changes must reliably update displayed/editable values, including
asynchronous loading and cancel/reset. Keep the input's value separate from visibility,
validation and other dependent state. Do not rely on compiler event capture or automatic
input synchronization; no such host is generated.

Render real layout, labels, controls and conditional content with original text and stable
data-testid=ELEMENT_ID selectors. Use the installed dependencies and configured styles.
Preserve every explicitly required UI name and role verbatim, including language, spelling
and case. Do not rename "Name" to "Shelf name", translate captions, or combine aliases.
Keep visible labels and computed accessible names consistent: associate labels correctly,
and do not override them with a different aria-label or concatenate unrelated text through
aria-labelledby. Use exact placeholders only when the requirement specifies placeholders;
an accessible field name alone does not prescribe a placeholder or HTML implementation.
Apply this to buttons, links, headings and named regions as well as form fields. If the
generated design or reference image conflicts with an explicit original UI contract, follow
the original requirement and explain the discrepancy. Unspecified wording is an implementation
choice; business object names still come from actual data, not reference examples.
This stage builds presentation, native editing and navigation, not business API operations,
session restoration or later requirements' workflows. Step 10 adds those interactions.
Keep one clear owner for each native form/navigation action. Later implementation must
extend that existing handler, not add another independently firing click/submit listener.

Preserve the presentation-test adapter in frontend/src/ui-runtime.ts. Call presentationData
with this page ID and a projection of the actual declared frontend values when rendering.
It supplies display-test overrides and exposes actual data keys; it does not own your state.
Do not copy display-test records into production initial values. If representative records
are needed, use the compiler-owned presence suite's __ARC_UI_TEST_DATA__ setup as reference.

The compiler generates immutable presence suites for complete pages and checks already
accepted related pages. Repair writable sources without removing existing behavior.
Presence tests, shared test adapters and build infrastructure are read-only.
"""



def page_layout_signals(design, pid):
    page = design["pages"][pid]
    route = page["route"].strip("/").split("/")[0]
    return {*(f"owner:{rid}" for rid in owners(design, pid)),
        *(f"element:{uid}" for uid in page_elements(design, pid)),
        *([f"layout:{page['layout']}"] if page.get("layout") else []),
        *([f"route:{route}"] if route and not route.startswith(("{", ":")) else [])}


def implement_ui(arc_dir: Path, design: dict, model, console, report: dict, max_turns: int = 10,
        images: dict | None = None, requirement_contexts: dict | None = None) -> dict:
    """Generate a deterministic suite once per page; implement by page group."""
    output = arc_dir.parent.resolve()
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    pages = {pid: page_context(design, pid) for pid in design["pages"]}
    page_owners = {pid: owners(design, pid) for pid in pages}
    signals = {pid: page_layout_signals(design, pid) for pid in pages}
    batches = ImplementationBatches(arc_dir, "08", console).register(pages, page_owners, signals)
    report.update(status="IMPLEMENTING", requirements={}, pages={})
    path = arc_dir / "ui_checks.json"
    save_json(path, report)
    prepare_frontend(output)
    install_dependencies(output)
    checks = FrontendChecks(output)
    checks.install_browser()
    checkpoint(output, stage="08", task="runtime", action="Prepare grouped page implementation",
        details={"requirements": tree.leaves, "pages": list(pages)})

    def process(batch, entry):
        selected = {pid: pages[pid] for pid in batch.units}
        relatives = {pid: test_path(pid) for pid in selected}
        reg = [test_path(pid) for pid in batches.accepted]
        baseline = {path: (output / path).read_bytes() for path in relatives.values() if (output / path).is_file()}
        for pid, relative in relatives.items():
            save_text(output / relative, existence_suite(design, pid))

        def gate():
            compiled = checks.typecheck([*relatives.values(), *reg])
            if compiled["returncode"]:
                raise CheckFailure("Frontend TypeScript failed", compiled)
            if reg:
                require_green(checks.tests(reg))
            passed, rejected = passing_checks(batch.units, lambda pid: checks.tests([relatives[pid]]), require_green)
            require_any(passed, rejected)
            return {"typecheck": compiled, "passed": passed, "rejected": rejected}

        # Observe the real starting point, but still implement a multi-page group
        # if any page in it lacks acceptance.
        try:
            before = gate()
        except (ValueError, RuntimeError) as error:
            before = {"error": str(error), "feedback": getattr(error, "feedback", None)}
        if len(before.get("passed", {})) == len(batch.units):
            agent = {"turns": 0, "files": [], "checks": before}
        elif before.get("passed"):
            # Preserve pages already green and retry only pages still missing.
            agent = {"turns": 0, "files": [], "checks": before}
        else:
            context = batches.context(batch, {"pages": selected,
                "application_entrypoints": list(APPLICATION_ENTRYPOINTS),
                "visual_references": {iid: image for iid, image in (images or {}).items()
                    if any(iid in design["pages"][pid]["images"] for pid in selected)}})
            workspace = FileTools(output, ["frontend"], requirements=entry["requirements"], stage="ui",
                files=["frontend/src/ui-runtime.ts", *relatives.values(), *reg, "frontend/package.json",
                    "frontend/tsconfig.json", "frontend/playwright.ui.config.ts", *APPLICATION_ENTRYPOINTS],
                allow_write=lambda name: "/tests/" not in name and editable_application_path(output, name))
            agent = run_file_agent(model, INSTRUCTIONS, context, workspace, gate,
                max_turns, console, batch.id + " / page group", feedback=before, batch_limits=True)
        result = agent["checks"]
        for pid, evidence in result["rejected"].items():
            evidence["test_archive"] = reject_paths(output, batch.id + " / " + pid, baseline, [relatives[pid]])
        entry["rejected_checks"] = result["rejected"]
        return {pid: {"requirements": page_owners[pid], "test_path": relatives[pid],
            "files": agent["files"], "turns": agent["turns"], "checks": evidence}
            for pid, evidence in result["passed"].items()}

    report["pages"] = batches.run(process)
    for rid in tree.requirements:
        used = [pid for pid in pages if rid in page_owners[pid]]
        report["requirements"][rid] = {"requirement": rid, "requirements": [rid], "pages": used,
            "test_paths": [test_path(pid) for pid in used if pid in batches.accepted],
            "status": ("NO_DIRECT_UI" if tree.children[rid] else "NO_UI") if not used
                else "GREEN" if all(pid in batches.accepted for pid in used) else "FAILED",
            "page_results": {pid: report["pages"][pid] for pid in used}}
    files = [test_path(pid) for pid in batches.accepted]
    commands = {"typecheck": (lambda: checks.typecheck(files), None), "build": (checks.build, None)}
    if files:
        commands["tests"] = (lambda: checks.tests(files), require_green)
    verification = final_checks(console, **commands)
    final = verification.get("tests", {}).get("result") or {}
    report["summary"] = {"requirements": len(tree.leaves),
        "accepted_requirements": sum(entry["status"] == "GREEN" for entry in report["requirements"].values()),
        "failed_requirements": sum(entry["status"] == "FAILED" for entry in report["requirements"].values()),
        "pages": len(batches.accepted), "tests": final.get("passed", 0), "failed": final.get("failed", 0)}
    complete_report(report, report["pages"].values(), verification)
    save_json(path, report)
    return report
