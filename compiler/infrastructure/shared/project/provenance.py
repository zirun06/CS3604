"""Validate generated-workspace identity and checkpoint provenance."""

from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

from infrastructure.utils.budget import ENV
from infrastructure.utils.files import save_json


COMPILER_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ".arc/workspace.json"
CHECKPOINT = ".arc/checkpoint.json"
COMPLETE_STATES = frozenset({"GREEN", "NO_UI", "NO_APIS", "NO_TRIGGERS"})
CONTROL_FILES = {"workspace.json", "checkpoint.json", "compilation.json"}
MODEL_SETTINGS = ("MODEL", "VISUAL_MODEL", "MODEL_REASONING", "VISUAL_REASONING",
    "OPENAI_BASE_URL", "MAX_OUTPUT_TOKENS", "COMPILER_IMAGE_TOKEN_RESERVE",
    "COMPILER_PRICE_TABLE", *ENV.values())


def resolve_workspace(input_dir, output):
    source = Path(input_dir).expanduser().resolve()
    target = Path(output).expanduser().resolve()
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("Input and output directories must be disjoint")
    if COMPILER_ROOT.is_relative_to(target) or target.is_relative_to(COMPILER_ROOT / "infrastructure"):
        raise ValueError("Output must not contain the compiler source directory")
    return source, target


def effective_settings():
    return {**dotenv_values(COMPILER_ROOT / ".env", encoding="utf-8-sig"), **os.environ}


def _hash_file(path):
    return sha256(path.read_bytes()).hexdigest()


def _tree_hash(root, files):
    items = [(p.relative_to(root).as_posix(), _hash_file(p)) for p in sorted(files)]
    return _json_hash(items)


def _json_hash(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def provenance(input_dir, settings, port):
    """Bind all copied inputs, compiler sources and effective runtime settings."""
    ignored = {"tests", ".git", ".arc"}
    paths = [path for path in input_dir.rglob("*") if not ignored.intersection(path.relative_to(input_dir).parts)]
    if any(path.is_symlink() for path in paths):
        raise ValueError("Checkpoint inputs must not contain symbolic links")
    sources = [p for p in (COMPILER_ROOT / "infrastructure").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    sources.extend(COMPILER_ROOT / file for file in ("main.py", "requirements.txt", "pyproject.toml", "uv.lock")
        if (COMPILER_ROOT / file).is_file())
    config = {name: settings.get(name) or None for name in MODEL_SETTINGS}
    config["port"] = port
    if config["COMPILER_PRICE_TABLE"]:
        config["price_table_hash"] = _hash_file(Path(config["COMPILER_PRICE_TABLE"]).expanduser().resolve())
    return {"input_sha256": _tree_hash(input_dir, (p for p in paths if p.is_file())),
        "source_sha256": _tree_hash(COMPILER_ROOT, sources), "config_sha256": _json_hash(config)}


def read_workspace(output):
    marker = output / WORKSPACE
    if (output / ".arc").is_symlink() or marker.is_symlink():
        raise ValueError("Generated workspace metadata must not be symlinked")
    if not marker.is_file():
        return None
    data = json.loads(marker.read_text(encoding="utf-8"))
    if not data.get("workspace_id") or data.get("output") != str(output):
        raise ValueError("Generated workspace identity does not match the output path")
    return data


def prepare_workspace(output):
    marker = read_workspace(output)
    git = output / ".git"
    if marker is not None:
        if not git.is_dir() or git.is_symlink():
            raise ValueError("Existing output has no output-local generated Git repository")
        return marker
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Use an empty output directory or a recognized generated workspace")
    marker = {"workspace_id": uuid4().hex, "output": str(output)}
    save_json(output / WORKSPACE, marker)
    return marker


def checkpoint_artifacts(records, oid_field):
    """Select the real staged/committed Git blob IDs, respecting Git EOL filters."""
    hashes = {}
    for record in records.split("\0"):
        if not record:
            continue
        header, path = record.split("\t", 1)
        artifact = path.startswith(".arc/") and path.endswith(".json") and path.count("/") == 1
        app = path.startswith(("backend/", "frontend/")) or path in {"package.json", "deploy.sh"}
        if (artifact and Path(path).name not in CONTROL_FILES) or app:
            hashes[path] = header.split()[oid_field]
    return hashes


def stage_checkpoint(output, marker, source, stage, run_id, artifacts):
    save_json(output / CHECKPOINT, {"workspace_id": marker["workspace_id"], "source": source,
        "stage": stage, "run_id": run_id, "artifacts": artifacts})
