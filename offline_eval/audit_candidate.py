"""Inspect a compiler ZIP, report pattern hits, and optionally extract to an empty directory."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
from zipfile import ZipFile


FORBIDDEN = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".cache", ".arc", "cache", "caches", "offline_eval", "tasks", "tests", "input",
    "outputs", "output", "docs", "slides", "acceptance_cases", "public"}
RULES = {
    "benchmark_or_task_name": r"(?i)book[ _-]*stack|presta[ _-]*shop|stack[ _-]*overflow|ctrip|携程|\b12306\b|google[ _-]*keep|keep[ _-]*notes|arc-bench-web--",
    "keep_literal_for_review": r"\bKeep\b",
    "public_case_route": r"(?i)bundled_suite|select_profile|suite_structure_key|acceptance_cases[/\\]|offline_eval[/\\]public|input[/\\]tests|repair_storefront_route_params",
    "business_literal_review": r"(?i)insert\s+into\s+[^\r\n]{1,120}?\s+values\s*\(|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:password|cookie|session_token)\s*[:=]\s*['\"][^'\"\r\n]+['\"]",
    "model_endpoint_review": r"(?i)https?://[^\s'\"<>]+",
    "secret_shape": r"(?i)\b(?:sk-(?:proj-|ant-)?[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9_]{20,}|github_pat_[a-z0-9_]{20,}|AKIA[A-Z0-9]{16}|xox[baprs]-[a-z0-9-]{12,})\b|\bBearer\s+[a-z0-9._-]{24,}|^[ \t]*OPENAI_API_KEY[ \t]*=[ \t]*[^\s#]+",
}


def inspect(archive, index, destination=None):
    """Never include matched secret values in the emitted evidence."""
    fingerprint_data = json.loads(index.read_text(encoding="utf-8"))
    fingerprints = {*(fingerprint_data.keys()), *(fingerprint_data.values())}
    rules = {**RULES, "known_requirement_or_suite_fingerprint":
        "(?i)" + "|".join(re.escape(value) for value in sorted(fingerprints))}
    compiled = {name: re.compile(pattern, re.MULTILINE) for name, pattern in rules.items()}
    hits = {name: [] for name in rules}
    forbidden, files, seen, directories = [], [], set(), 0
    with ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError("ZIP contains a corrupt entry")
        for entry in package.infolist():
            name = entry.filename
            parts = name.rstrip("/").split("/")
            key = name.rstrip("/").casefold()
            mode = entry.external_attr >> 16
            if (not name or "\\" in name or any(part in {"", ".", ".."} or ":" in part for part in parts)
                    or key in seen or stat.S_ISLNK(mode)):
                raise ValueError(f"Unsafe, duplicate or linked ZIP entry: {name}")
            seen.add(key)
            if any(part.casefold() in FORBIDDEN
                    or (part.casefold().startswith(".env") and part.casefold() != ".env.example")
                    or part.casefold().endswith((".pyc", ".pyo", ".db", ".sqlite", ".zip"))
                    or re.fullmatch(r"compact(?:_.*)?\.py", part, flags=re.I) for part in parts):
                forbidden.append(name)
            if entry.is_dir():
                directories += 1
                continue
            data = package.read(entry)
            text = data.decode("utf-8", errors="replace")
            if name == ".env.example":
                for line in text.splitlines():
                    if line.startswith(("OPENAI_API_KEY=", "OPENAI_BASE_URL=")) and line.split("=", 1)[1].strip():
                        forbidden.append(name + " (nonempty connection example)")
            files.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            for rule, pattern in compiled.items():
                lines = {text.count("\n", 0, match.start()) + 1 for match in pattern.finditer(text)}
                hits[rule].extend({"path": name, "line": line} for line in sorted(lines))
                if pattern.search(name):
                    hits[rule].append({"path": name, "line": None})
        roots = sorted({name.split("/")[0] for name in seen})
        required = {"main.py", "requirements.txt"}
        missing = required - {item["path"] for item in files}
        blocking = {"benchmark_or_task_name", "public_case_route", "secret_shape",
            "known_requirement_or_suite_fingerprint"}
        ok = not (forbidden or missing or any(hits[rule] for rule in blocking))
        if destination is not None and ok:
            destination.mkdir(parents=True, exist_ok=True)
            if any(destination.iterdir()):
                raise ValueError("Extract only into an empty directory")
            package.extractall(destination)
            for item in files:
                if hashlib.sha256((destination / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
                    raise ValueError("Extracted file hash mismatch: " + item["path"])
    return {"archive": archive.name, "size": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "root_entries": roots, "directories": directories, "file_count": len(files),
        "expanded_file_bytes": sum(item["bytes"] for item in files), "files": files,
        "forbidden_entries": forbidden, "missing_root_files": sorted(missing),
        "rules": {**RULES, "known_requirement_or_suite_fingerprint":
            f"Exact search for {len(fingerprints)} SHA-256 strings from the offline index"},
        "hits": hits, "passed": ok, "extracted": bool(destination is not None and ok)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--index", type=Path, default=Path(__file__).with_name("public") / "index.json")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--extract", type=Path)
    args = parser.parse_args()
    result = inspect(args.archive, args.index, args.extract)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    source = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    args.report.write_bytes(source.encode("utf-8"))
    assert args.report.read_text(encoding="utf-8") == source
    print(json.dumps({k: result[k] for k in ("size", "sha256", "file_count", "forbidden_entries",
        "missing_root_files", "passed", "extracted")}, ensure_ascii=False))
    print(json.dumps({key: len(values) for key, values in result["hits"].items()}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
