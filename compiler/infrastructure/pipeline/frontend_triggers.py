"""Step 09: Frontend trigger design."""

from pathlib import Path

from infrastructure.stages.frontend.context import load_frontend_context, load_ui_design, behavior_contexts
from infrastructure.stages.frontend.triggers.synthesis import synthesize_triggers
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole


def design_frontend_triggers(input_dir: Path, arc_dir: Path, pause: bool = False, max_attempts: int = 10) -> dict:
    if max_attempts < 1:
        raise ValueError("--max-attempts must be positive")
    tree, _, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    ui = load_ui_design(arc_dir, tree)
    console = DemoConsole(pause)
    model = TextModel() if ui["pages"] else None
    try:
        result = synthesize_triggers(arc_dir, ui, tree, backend,
            behavior_contexts(contexts), model, console, max_attempts)
    finally:
        if model is not None:
            model.client.close()
    console.show("Step 09 | Trigger design complete", f"Triggers: {len(result['triggers'])}\nSaved: {arc_dir / 'frontend_triggers.json'}\nApplication code and UI/data design were not changed. Step 10 implements triggers through E2E TDD.")
    return result
