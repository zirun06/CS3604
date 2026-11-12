"""Repair only TypeScript diagnostics that identify an edited implicit-any parameter."""

import json
from pathlib import Path
import re
import shutil

from infrastructure.shared.project.git import checkpoint
from infrastructure.utils.processes import capture_process


TS7006 = re.compile(r"^([^\r\n]+?)\((\d+),(\d+)\): error TS7006:", re.MULTILINE)


def implicit_any_locations(workspace, output):
    locations = {}
    for path, line, column in TS7006.findall(output):
        candidate = Path(path.strip())
        resolved = (workspace.output / candidate).resolve()
        if not resolved.is_relative_to(workspace.output):
            continue
        relative = resolved.relative_to(workspace.output).as_posix()
        if (relative not in workspace.changed_paths or not workspace.can_write(relative)
                or not relative.startswith(("frontend/src/", "backend/src/"))
                or not relative.endswith((".ts", ".tsx")) or not workspace.path(relative).is_file()):
            continue
        locations.setdefault(relative, []).append([int(line), int(column)])
    return locations


def recheck_types(check, workspace):
    """Re-run the same gate after a narrowly scoped, diagnostic-backed source edit."""
    result = check()
    if not result.get("returncode") or workspace is None:
        return result
    locations = implicit_any_locations(workspace, result.get("output", ""))
    node = shutil.which("node") if locations else None
    if not node:
        return result
    script = Path(__file__).with_name("repair_implicit_any.mjs")
    attempt = capture_process([node, str(script), str(workspace.output), json.dumps(locations, ensure_ascii=False)],
        cwd=workspace.output, timeout=20)
    if attempt["returncode"]:
        return result
    try:
        edits = int(attempt["stdout"].strip())
    except (KeyError, ValueError):
        return result
    if not edits:
        return result
    checked = check()
    checkpoint(workspace.output, task="TS7006", action="Recheck explicit parameter annotation",
        status="FAILED" if checked["returncode"] else "GREEN",
        details={"locations": locations, "edits": edits, "returncode": checked["returncode"]})
    return checked
