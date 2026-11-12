"""Step 10: connect frontend triggers to backend APIs through grouped requirement acceptance tests."""

from pathlib import Path

from infrastructure.stages.frontend.triggers.context import load_e2e_context
from infrastructure.stages.frontend.triggers.implementation import run_trigger_tdd
from infrastructure.stages.frontend.triggers.acceptance_gate import coverage_matrix
from infrastructure.stages.requirements.batching import DesignPlan
from infrastructure.utils.files import read_artifact
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.agent.implementation_batches import ImplementationBatches
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.files import save_json


def implement_frontend_triggers(input_dir: Path, arc_dir: Path, pause: bool = False,
        max_turns: int = 10) -> dict:
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    tree, schema, backend, ui, interactions, images, contexts = load_e2e_context(arc_dir, input_dir)
    report = {"status": "PREPARING", "requirements": {
        rid: {"status": "NO_DIRECT_TRIGGERS" if tree.children[rid] else "PENDING", "triggers": []}
        for rid in tree.requirements}}
    save_json(arc_dir / "frontend_e2e.json", report)
    try:
        if not ui["pages"]:
            plan = DesignPlan(read_artifact(arc_dir, "requirements.json"))
            save_json(arc_dir / "acceptance" / "coverage.json", coverage_matrix(plan, tree, ui, interactions, {},
                read_artifact(arc_dir, "db_obligations.json")))
            ImplementationBatches(arc_dir, "10", DemoConsole(pause)).register({}, {}, {}).publish()
            report.update({"status": "NO_UI", "summary": {"requirements": 0, "triggers": 0, "e2e_tests": 0, "ui_tests": 0, "failed": 0}})
            save_json(arc_dir / "frontend_e2e.json", report)
            return report
        model = TextModel()
        try:
            result = run_trigger_tdd(arc_dir, tree, schema, backend, ui, interactions, images,
                contexts, model, DemoConsole(pause), report, max_turns)
        finally:
            model.client.close()
        save_json(arc_dir / "frontend_e2e.json", result)
        print(f"Frontend requirement acceptance {result['status']}: {result['summary']}\nReport: {arc_dir / 'frontend_e2e.json'}", flush=True)
        return result
    except BaseException as error:
        report.update({"status": "FAILED", "error": str(error)})
        for requirement in report["requirements"].values():
            if requirement["status"] not in {"GREEN", "NO_TRIGGERS", "NO_DIRECT_TRIGGERS"}:
                requirement["status"] = "FAILED"
        save_json(arc_dir / "frontend_e2e.json", report)
        raise
