"""Install the generated workspace's npm dependencies before each TDD run."""

from pathlib import Path
import subprocess
from threading import Thread
from time import monotonic

from infrastructure.utils.budget import budget_timeout
from infrastructure.utils.processes import check_process_deadline, npm_command, start_process, stop_process
from infrastructure.utils.presentation.events import model_metric, validation_event


def install_dependencies(output_dir: Path) -> None:
    """Run npm install in the generated workspace, stream its output, and fail on timeout or nonzero exit."""
    if not (output_dir / "package.json").is_file():
        raise ValueError("Run main.py --stage 00 before installing project dependencies")
    started = monotonic()
    result = "not_run"
    try:
        _install(output_dir)
        result = "passed"
    except BaseException as error:
        result = "failed" if getattr(error, "process_started", True) else "not_run"
        raise
    finally:
        elapsed = monotonic() - started
        if result != "not_run":
            model_metric("local_check_seconds", elapsed)
        validation_event("dependency_install", elapsed, result, feedback=False)


def _install(output_dir):
    timeout = budget_timeout(600)
    command = npm_command()
    print(f"Installing dependencies in {output_dir}: npm install --include=dev --no-audit --no-fund", flush=True)
    with start_process(
        [*command, "install", "--include=dev", "--no-audit", "--no-fund"],
        cwd=output_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    ) as process:
        # Forward child output through Python so the console log also receives it.
        def forward_output():
            """Forward npm output through Python so both the terminal and compiler.log receive it."""
            for line in process.stdout:
                print(line, end="", flush=True)

        reader = Thread(target=forward_output, daemon=True)
        reader.start()
        try:
            process.wait(timeout=budget_timeout(timeout))
            check_process_deadline()
        except subprocess.TimeoutExpired as error:
            try:
                stop_process(process)
            finally:
                if timeout < 600:
                    check_process_deadline(expired=True)
            raise RuntimeError("npm install timed out after 600 seconds") from error
        except BaseException:
            stop_process(process)
            raise
        finally:
            reader.join()
        if process.returncode:
            raise RuntimeError(f"npm install failed with exit code {process.returncode}; see the npm output above")
