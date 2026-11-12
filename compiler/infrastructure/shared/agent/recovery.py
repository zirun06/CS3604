"""Isolate failed implementation tasks and complete independent final checks."""

from contextlib import contextmanager
import re
from uuid import uuid4

from infrastructure.utils.budget import BudgetExhausted
from infrastructure.shared.agent.files import EXCLUDED
from infrastructure.utils.files import save_bytes, save_json
from infrastructure.shared.project.git import checkpoint
from infrastructure.utils.presentation.events import task_scope


class CandidateProgress(ValueError):
    """Retain an independently checked intermediate candidate and continue repair."""

    def __init__(self, feedback):
        self.feedback = feedback
        super().__init__(feedback["reason"])


def snapshot(output):
    paths = {path.relative_to(output).as_posix()
        for root in ("backend/src", "backend/tests", "frontend/src", "frontend/tests")
        for path in (output / root).rglob("*") if path.is_file() and not path.is_symlink()
        and not any(part in EXCLUDED or part.startswith(".") for part in path.relative_to(output).parts)}
    index = ".arc/requirement_files.json"
    if (output / index).is_file():
        paths.add(index)
    return {path: (output / path).read_bytes() for path in paths}


def _archive(output, label, before, after, status, details):
    changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    name = re.sub(r"[^\w.-]+", "_", label).strip("._")[:100] or "task"
    directory = output / ".arc/failures" / f"{name}.{uuid4().hex[:8]}"
    for path in sorted(changed):
        if path in after:
            save_bytes(directory / "files" / path, after[path])
    result = {**details, "status": status, "task": label, "changed_files": sorted(changed),
        "deleted_files": sorted(changed - after.keys()), "archive": directory.relative_to(output).as_posix()}
    save_json(directory / "failure.json", result)
    return result


def restore_snapshot(output, before, changed):
    for path in changed:
        if path in before:
            save_bytes(output / path, before[path])
        else:
            (output / path).unlink(missing_ok=True)


def reject_candidate(output, label, before, error):
    after = snapshot(output)
    if before == after:
        return None
    failure = _archive(output, label, before, after, "REJECTED_CANDIDATE", {
        "error": str(error), "feedback": getattr(error, "feedback", None)})
    restore_snapshot(output, before, failure["changed_files"])
    return failure["archive"]


def reject_paths(output, label, baseline, paths):
    """Archive and restore failed unit-owned paths without reverting shared accepted edits."""
    before = {path: baseline[path] for path in paths if path in baseline}
    after = {path: (output / path).read_bytes() for path in paths if (output / path).is_file()}
    if before == after:
        return None
    archive = _archive(output, label, before, after, "REJECTED_UNIT_FILES", {})
    restore_snapshot(output, before, archive["changed_files"])
    return archive["archive"]


@contextmanager
def implementation_task(output, entry, console, label, *, batch_id=None):
    """Archive rejected files, restore the task baseline, and continue on acceptance failure.

    Missing prerequisites are checked before this boundary. Disk errors, interrupts,
    and unexpected compiler exceptions propagate; they are not business failures.
    """
    with task_scope(label, entry.get("requirements"), result=entry, batch_id=batch_id):
        before = snapshot(output)
        try:
            yield
        except (ValueError, BudgetExhausted) as error:
            after = snapshot(output)
            status = "BUDGET_EXHAUSTED" if isinstance(error, BudgetExhausted) else "FAILED"
            failure = _archive(output, label, before, after, status, {
                "phase": entry.get("status"), "error": str(error), "error_type": type(error).__name__,
                "turns": getattr(error, "turns", 0), "feedback": getattr(error, "feedback", None)})
            restore_snapshot(output, before, failure["changed_files"])
            entry.update(failure)
            console.show(label + " | " + status, str(error) + "\nBaseline restored. Failure archive: " + failure["archive"])
            checkpoint(output, task=label, action="Archive failed attempt and restore task baseline",
                status=status, details=failure)
            if isinstance(error, BudgetExhausted) and error.time_limit:
                raise
        except BaseException as error:
            checkpoint(output, task=label, action="Record interrupted implementation task",
                status="INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAILED",
                details={"error": str(error), "error_type": type(error).__name__})
            raise
        else:
            if entry.get("status") == "PARTIAL":
                archive = _archive(output, label, before, snapshot(output), "PARTIAL", {
                    "accepted": entry["accepted"], "pending": entry["pending"],
                    "feedback": entry.get("rejected_checks", {})})
                entry["archive"] = archive["archive"]
            checkpoint(output, task=label, action="Publish accepted implementation task",
                status=entry.get("status", "GREEN"), details=entry)


def final_checks(console, **checks):
    """Attempt every final compiler/test/build check even if an earlier check fails."""
    results = {}
    for name, (action, accept) in checks.items():
        result = None
        try:
            result = action()
            if result.get("returncode"):
                raise ValueError(result.get("output", f"{name} failed"))
            if accept:
                accept(result)
            results[name] = {"status": "GREEN", "result": result}
        except (ValueError, RuntimeError) as error:
            results[name] = {"status": "FAILED", "result": result, "error": str(error)}
        console.show("Final verification | " + name + " | " + results[name]["status"],
            results[name].get("error") or (result or {}).get("output", "Passed"))
        checkpoint(task="final verification", action="Run " + name,
            status=results[name]["status"], details=results[name])
    return results


def complete_report(report, entries, verification):
    """Separate completion of the process from successful acceptance."""
    report["failures"] = [dict(entry) for entry in entries if entry.get("status") in {"FAILED", "BUDGET_EXHAUSTED"}]
    report["verification"] = verification
    report["status"] = ("COMPLETED_WITH_FAILURES" if report["failures"]
        or any(check["status"] == "FAILED" for check in verification.values()) else "GREEN")
    return report
