"""Run all compilation passes or one selected pass in the same pipeline."""

from pathlib import Path
import re
import traceback
from subprocess import TimeoutExpired

from infrastructure.pipeline.project_initialization import project_initialization
from infrastructure.pipeline.requirements import explore_requirement
from infrastructure.pipeline.db_schema import build_db_schema
from infrastructure.pipeline.db_obligations import infer_db_obligations
from infrastructure.pipeline.database import implement_db
from infrastructure.pipeline.backend_apis import design_backend_apis
from infrastructure.pipeline.backend_implementation import implement_backend_tdd
from infrastructure.pipeline.ui_design import design_frontend_ui
from infrastructure.pipeline.ui_implementation import implement_frontend_ui
from infrastructure.pipeline.frontend_triggers import design_frontend_triggers
from infrastructure.pipeline.frontend_implementation import implement_frontend_triggers
from infrastructure.utils.presentation.console import show_panel
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.files import save_json
from infrastructure.utils.processes import capture_process
from infrastructure.utils.budget import RunBudget, active_budget, budget_scope, BudgetExhausted
from infrastructure.shared.project.provenance import (
    COMPLETE_STATES, effective_settings, prepare_workspace, provenance, resolve_workspace,
)
from infrastructure.shared.project.git import checkpoint, rollback_before_stage
from infrastructure.utils.presentation.events import begin_run, finish_run, begin_stage, finish_stage, timestamp, validation_event


def node_preflight(output: Path) -> dict:
    """Record the template's Node compatibility without blocking compilation."""
    version = None
    warning = None
    try:
        result = capture_process(["node", "--version"], cwd=output, timeout=5)
        match = re.fullmatch(r"v(\d+)\.(\d+)\.\d+(?:[-+].*)?", result["stdout"].strip())
        if result["returncode"] != 0 or not match:
            warning = "Could not read the Node version from node --version."
        else:
            version = match[0]
            major, minor = map(int, match.groups())
            # Vite 7 and the locked better-sqlite3 12.2.0 must both support Node.
            if major not in (22, 23, 24) or (major == 22 and minor < 12):
                warning = (f"Node {version} is outside the template dependency range. "
                    "Use Node 22.12+ on major 22 (recommended) or Node 24; "
                    "native SQLite dependency installation may fail.")
    except (OSError, TimeoutExpired, BudgetExhausted) as error:
        warning = f"Could not run node --version ({type(error).__name__})."
    line = f"[PREFLIGHT] node --version: {version or 'unavailable'}"
    if warning:
        line += "\n[WARNING] " + warning
    print(line, flush=True)
    with (output / "compiler.log").open("a", encoding="utf-8") as log:
        log.write(line + "\n")
    return {"version": version, "warning": warning}


PIPELINE = (
    ("00_project_initialization", project_initialization, "project_files"),
    ("01_explore_requirement", explore_requirement, "requirements"),
    ("02_build_db_schema", build_db_schema, "db_schema"),
    ("03_infer_db_obligations", infer_db_obligations, "db_obligations"),
    ("04_implement_db", implement_db, "db_implementations"),
    ("05_design_backend_apis", design_backend_apis, "backend_apis"),
    ("06_implement_backend_tdd", implement_backend_tdd, "backend_checks"),
    ("07_design_ui", design_frontend_ui, "ui_design"),
    ("08_implement_ui", implement_frontend_ui, "ui_checks"),
    ("09_design_frontend_triggers", design_frontend_triggers, "frontend_triggers"),
    ("10_implement_frontend_tdd", implement_frontend_triggers, "frontend_e2e"),
)


REQUIRES = {
    "02": ("requirements.json",),
    "03": ("requirements.json", "db_schema.json"),
    "04": ("requirements.json", "db_schema.json"),
    "05": ("requirements.json", "db_schema.json", "db_obligations.json"),
    "06": ("requirements.json", "db_schema.json", "db_obligations.json", "backend_apis.json"),
    "07": ("requirements.json", "visual_analysis.json"),
    "08": ("requirements.json", "visual_analysis.json", "ui_design.json"),
    "09": ("requirements.json", "visual_analysis.json", "db_schema.json", "backend_apis.json",
        "db_obligations.json", "ui_design.json"),
    "10": ("requirements.json", "visual_analysis.json", "db_schema.json", "backend_apis.json",
        "ui_design.json", "frontend_triggers.json"),
}
VALIDATIONS = {
    "04": (("build", "deterministic"), ("database_check", "deterministic"), ("startup_check", "deterministic")),
    "06": (("typecheck", "deterministic"), ("http_test", "model"), ("build", "deterministic")),
    "08": (("typecheck", "deterministic"), ("ui_presence", "deterministic"), ("build", "deterministic")),
    "10": (("typecheck", "deterministic"), ("http_test", "model"), ("ui_presence", "deterministic"),
        ("browser_e2e", "model"), ("build", "deterministic")),
}

class Compiler:
    """Own shared paths, configuration, and results for one compilation."""

    def __init__(self, input_dir: Path, output_dir: Path, model_log: bool = False,
            port: int = 3000, pause: bool = False) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("Backend port must be between 1 and 65535")
        self.input_dir, self.output_dir = resolve_workspace(input_dir, output_dir)
        self.arc_dir = self.output_dir / ".arc"
        self.model_log = model_log
        self.port = port
        self.pause = pause
        self.artifacts: dict[str, object] = {}
        self.current_stage: str | None = None
        self.report = {"status": "NOT_STARTED", "stages": {}}

    def _run(self, stage: str, function, *arguments, **options):
        """Attempt every pass; keep failures explicit without aborting later passes."""
        self.current_stage = stage
        stage_event = begin_stage(stage)
        self.report["stages"][stage] = {"status": "RUNNING", "started_at": timestamp()}
        save_json(self.arc_dir / "compilation.json", self.report)
        budget = active_budget()
        denied_before = budget.denial_count if budget is not None else 0
        try:
            missing = [name for name in REQUIRES.get(stage[:2], ()) if not (self.arc_dir / name).is_file()]
            if budget is not None and budget.remaining_time(run_only=True) <= 0:
                result = {"status": "SKIPPED_TIME", "error": "Run deadline reached"}
            elif missing:
                result = {"status": "MISSING_PREREQUISITES", "missing": missing}
            else:
                if budget is not None:
                    budget.check_time()
                with console_log(self.output_dir, stage=stage,
                        model_log=self.model_log, debug_model_io=self.model_log):
                    result = function(*arguments, **options)
                if budget is not None:
                    budget.check_time()
        except BudgetExhausted as error:
            result = {"status": "BUDGET_EXHAUSTED", "error": str(error),
                "budget_resource": error.resource, "budget_scope": error.scope}
        except KeyboardInterrupt as error:
            self.report["status"] = "INTERRUPTED"
            self.report["stages"][stage] = {"status": "INTERRUPTED", "error": str(error),
                **finish_stage(stage_event, "INTERRUPTED")}
            save_json(self.arc_dir / "compilation.json", self.report)
            checkpoint(self.output_dir, stage=stage, task="stage report", action="Record interrupted pass",
                status="INTERRUPTED", details=self.report["stages"][stage])
            raise
        except Exception as error:
            result = {"status": "FAILED", "error": str(error),
                "error_type": type(error).__name__, "traceback": traceback.format_exc()}
            if getattr(error, "failures", None):
                result.update(status="COMPLETED_WITH_FAILURES", failures=error.failures)
            show_panel("[FAILED; continuing] " + stage,
                result["error"] + "\nAccepted artifacts remain available. Attempt the next pass.", tone="error")
        except BaseException:
            finish_stage(stage_event, "FAILED")
            raise
        status = result.get("status", "GREEN") if isinstance(result, dict) else "GREEN"
        if budget is not None and budget.denial_count > denied_before and status != "BUDGET_EXHAUSTED":
            status = "BUDGET_EXHAUSTED"
        if status in {"SKIPPED_TIME", "MISSING_PREREQUISITES", "NO_UI", "NO_APIS", "BUDGET_EXHAUSTED"}:
            for kind, source in VALIDATIONS.get(stage[:2], ()):
                validation_event(kind, 0, "not_run", source=source, reason=status, only_if_absent=True)
        self.report["stages"][stage] = {"status": status, **finish_stage(stage_event, status)}
        if isinstance(result, dict):
            for key in ("failures", "verification", "error", "error_type", "traceback", "budget_resource", "budget_scope", "missing"):
                if key in result:
                    self.report["stages"][stage][key] = result[key]
        save_json(self.arc_dir / "compilation.json", self.report)
        if status != "SKIPPED_TIME":
            checkpoint_source = None
            if all(item["status"] in COMPLETE_STATES for item in self.report["stages"].values()):
                checkpoint_source = (self.workspace, self.source, stage, self.report["run_id"])
            checkpoint(self.output_dir, stage=stage, task="stage report", action="Publish pass result",
                status=status, details=self.report["stages"][stage], provenance=checkpoint_source)
        return result

    def compile(self, stage: str | None = None, *, from_stage: str | None = None) -> Path:
        """Run all passes, or restore the previous checkpoint before selected passes."""
        passes = PIPELINE
        if stage is not None and from_stage is not None:
            raise ValueError("stage and from_stage are mutually exclusive")
        selected = stage if stage is not None else from_stage
        if selected is not None:
            passes = ()
            for index, entry in enumerate(PIPELINE):
                if entry[0] == selected:
                    passes = (entry,) if stage is not None else PIPELINE[index:]
                    break
            if not passes:
                raise ValueError(f"Unknown stage: {selected}. Use a full stage name such as 06_implement_backend_tdd.")
        resolve_workspace(self.input_dir, self.output_dir)
        settings = effective_settings()
        budget = RunBudget.from_settings(settings, len(passes))
        budget.reserve_final_checks = any(name.startswith("10_") for name, _, _ in passes)
        self.source = provenance(self.input_dir, settings, self.port)
        if selected is not None:
            names = [name for name, _, _ in PIPELINE]
            index = names.index(selected)
            if index > 0:
                rollback_before_stage(self.output_dir, names[index - 1], self.source)
        self.workspace = prepare_workspace(self.output_dir)
        with budget_scope(budget):
            return self._compile_passes(passes, stage, from_stage, settings)

    def _compile_passes(self, passes, stage, from_stage, settings):
        self.artifacts.clear()
        self.report = {"status": "RUNNING", "stages": {}}
        show_panel("Requirement compiler | Pipeline",
            f"Input: {self.input_dir}\nOutput: {self.output_dir}\nPasses: {len(passes)}\nDetailed model logs: {'enabled' if self.model_log else 'disabled'}")
        run_token, run_id = begin_run(self.output_dir, self.input_dir, stage or from_stage, settings)
        self.report["selection"] = {"stage": stage, "from_stage": from_stage}
        self.report.update(run_id=run_id, workspace_id=self.workspace["workspace_id"],
            provenance=self.source, started_at=timestamp())
        try:
            self.report["node_preflight"] = node_preflight(self.output_dir)
            # =========================================
            # main loop over all passes in the pipeline
            # =========================================
            for index, (name, function, artifact) in enumerate(passes):
                active_budget().select_stage(len(passes) - index - 1)
                if function is project_initialization:
                    result = self._run(name, function, self.input_dir, self.output_dir, port=self.port, pause=self.pause)
                elif function in (explore_requirement, design_frontend_ui, implement_frontend_ui,
                        design_frontend_triggers, implement_frontend_triggers):
                    result = self._run(name, function, self.input_dir, self.arc_dir, pause=self.pause)
                else:
                    result = self._run(name, function, self.arc_dir, pause=self.pause)
                self.artifacts[artifact] = result

            # ========================================
            #        final report and exit
            # ========================================
            self.current_stage = None
            incomplete = [name for name, result in self.report["stages"].items()
                if result["status"] not in COMPLETE_STATES]
            self.report["status"] = "COMPLETED_WITH_FAILURES" if incomplete else "GREEN"
            show_panel("[DONE] Requirement compilation | " + self.report["status"],
                f"Application: {self.output_dir}\nReport: {self.arc_dir / 'compilation.json'}"
                + ("\nIncomplete stages: " + ", ".join(incomplete) if incomplete else ""),
                tone="error" if incomplete else "success")
            return self.output_dir
        except BaseException as error:
            self.report["status"] = "INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAILED"
            raise
        finally:
            self.report.update(finish_run(run_token, self.report["status"]))
            save_json(self.arc_dir / "compilation.json", self.report)
            incomplete = [name for name, result in self.report["stages"].items()
                if result["status"] not in COMPLETE_STATES]
            checkpoint(self.output_dir, stage="compiler", task="pipeline", action="Publish final compilation report",
                status=self.report["status"], details={"stages": self.report["stages"], "incomplete_stages": incomplete})
