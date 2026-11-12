"""Exercise an extracted compiler using its own runtime environment and an offline fixture."""

import argparse
import ast
from contextlib import ExitStack
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch


def load_fixture(path):
    # The fixture is copied into the external harness area. Reuse its assertions
    # and mocks without installing pytest into the candidate environment.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Import) and any(alias.name == "pytest" for alias in node.names))]
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    scope = {"__name__": "unpacked_fixture", "__file__": str(path)}
    exec(compile(tree, str(path), "exec"), scope)
    return scope


class Environment:
    def setenv(self, key, value):
        os.environ[key] = value


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    source = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(source.encode("utf-8"))
    assert path.read_text(encoding="utf-8") == source


def cli_case(args):
    root, work = args.compiler, args.work
    sys.path.insert(0, str(root))
    main = importlib.import_module("main")
    assert Path(main.__file__).resolve().parent == root
    if args.case == "imports":
        modules = []
        for path in sorted((root / "infrastructure").rglob("*.py")):
            parts = path.relative_to(root).with_suffix("").parts
            name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            loaded = importlib.import_module(name)
            assert Path(loaded.__file__).resolve() == path.resolve(), name
            modules.append(name)
        write(work / "imports.json", modules)
        print(f"Imported {len(modules)} infrastructure modules from the unpacked root")
        return
    if args.case == "interrupt":
        with patch.object(main.Compiler, "compile", side_effect=KeyboardInterrupt):
            main.main([str(work / "simple"), "--output-dir", str(work / "interrupted")])
        raise AssertionError("Interrupt returned instead of exiting")
    from httpx import AsyncClient, Client

    with ExitStack() as stack:
        for client in (Client, AsyncClient):
            stack.enter_context(patch.object(client, "send", side_effect=AssertionError("Network forbidden in mock")))
        fixture = load_fixture(work / "fixture.py")
        if args.case == "default":
            fixture["test_nonempty_pipeline_handoffs"](work, Environment(), "ROOT-ARTIFACTS",
                "R-COUNT", "S-COUNT", "artifact-groups")
            report = read(work / "application/.arc/compilation.json")
            write(work / "default-report.json", report)
        elif args.case == "resume":
            os.environ.update(OPENAI_BASE_URL="https://example.invalid/v1", OPENAI_API_KEY="mock-only")
            output = work / "application"
            calls = []
            stack.enter_context(patch.object(fixture["text"], "invoke",
                fixture["fixture_model"](output, "R-COUNT", "S-COUNT", calls,
                    other=("R-SECOND", "S-SECOND"), artifacts=True)))
            fixture["mock_local_checks"](stack)
            main.main([str(work / "artifact-groups"), "--output-dir", str(output),
                "--from-stage", "09_design_frontend_triggers"])
            report = read(output / ".arc/compilation.json")
            assert tuple(report["stages"]) == tuple(fixture["STAGES"][-2:])
            assert report["status"] == "GREEN" and set(calls) == {"09", "10"}
            write(work / "resume-report.json", report)


def verify(args):
    root, work = args.compiler, args.work
    if Path.cwd().resolve() != root:
        raise ValueError("Run this verifier from the unpacked compiler directory")
    if args.fixture is None or not (root / "main.py").is_file() or (root / ".env").exists():
        raise ValueError("Provide an unpacked compiler without .env and a synthetic fixture")
    work.mkdir(parents=True, exist_ok=False)
    copy = work / "fixture.py"
    copy.write_bytes(args.fixture.read_bytes())
    (work / "simple").mkdir()
    (work / "simple/requirements.yaml").write_text(
        "id: R-OFFLINE\nname: Offline probe\ndescription: Browse records.\n", encoding="utf-8")
    from PIL import Image

    connection = work / "connection"
    connection.mkdir()
    (connection / "requirements.yaml").write_text(
        "id: R-CONNECTION\nname: Connection probe\ndescription:\n"
        "  text: Inspect the supplied image.\n  image: [{id: IMAGE, reference: reference.png}]\n",
        encoding="utf-8")
    Image.new("RGB", (12, 12), "white").save(connection / "reference.png")
    records, assertions = {}, {}
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(
        ("OPENAI_", "COMPILER_", "PYTHONPATH", "PYTHONHOME", "GIT_DIR", "GIT_WORK_TREE"))}
    env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", STAGED11_REAL_CHECKS="0",
        GIT_CEILING_DIRECTORIES=str(root.parent))
    cli = [sys.executable, "-B", "-X", "utf8", "main.py"]
    worker = [sys.executable, "-I", "-B", "-X", "utf8", str(Path(__file__).resolve()),
        "--compiler", str(root), "--work", str(work)]
    input_dir = str(work / "simple")

    def run(name, command, expected, updates=None):
        result = subprocess.run(command, cwd=root, env={**env, **(updates or {})},
            encoding="utf-8", errors="replace", capture_output=True, timeout=240)
        log = work / f"{name}.log"
        log.write_bytes((result.stdout + result.stderr).encode("utf-8"))
        records[name] = {"command": command, "exit_code": result.returncode, "expected": expected, "log": log.name}
        print(f"{name}: {result.returncode} (expected {expected})", flush=True)
        if result.returncode != expected:
            raise ValueError(f"{name}: unexpected exit; see {log}")
        return result

    try:
        run("git_ceiling", ["git", "rev-parse", "--show-toplevel"], 128)
        from_help = run("help", [*cli, "--help"], 0)
        from_fixture = ast.parse(copy.read_text(encoding="utf-8"))
        stages, = [ast.literal_eval(node.value) for node in from_fixture.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "STAGES" for target in node.targets)]
        assert len(stages) == 11 and all("--stage " + name in from_help.stdout for name in stages)
        assertions["help_stages"] = stages
        run("imports", [*worker, "--case", "imports"], 0)
        selected = work / "stage-zero"
        run("stage", [*cli, input_dir, "--output-dir", str(selected), "--stage", stages[0]], 0)
        report = read(selected / ".arc/compilation.json")
        assert report["status"] == "GREEN" and list(report["stages"]) == [stages[0]]
        expected = ("deploy.sh", "frontend/src/App.tsx", "backend/src/server.ts", "backend/tests/support/context.ts")
        assert all((selected / path).is_file() for path in expected)
        assertions["templates"] = list(expected)
        run("bad_arguments", [*cli, input_dir, "--output-dir", str(work / "bad"),
            "--stage", "not-a-stage"], 2)
        for name, settings in (
                ("missing_api_key", {"OPENAI_BASE_URL": "https://example.invalid/v1"}),
                ("missing_base_url", {"OPENAI_API_KEY": "mock-only"})):
            target = work / name
            run(name + "_init", [*cli, str(connection), "--output-dir", str(target), "--stage", stages[0]],
                0, settings)
            failure = run(name, [*cli, str(connection), "--output-dir", str(target), "--stage", stages[1]],
                0, settings)
            assert "Set OPENAI_API_KEY and OPENAI_BASE_URL" in failure.stdout + failure.stderr
            report = read(target / ".arc/compilation.json")
            assert report["status"] != "GREEN" and report["stages"][stages[1]]["status"] == "FAILED"
        interrupted = run("interrupt", [*worker, "--case", "interrupt"], 130)
        assert "Compilation interrupted" in interrupted.stderr
        run("default_mock", [*worker, "--case", "default"], 0)
        run("from_stage_mock", [*worker, "--case", "resume"], 0)
        for case in ("default", "resume"):
            report = read(work / f"{case}-report.json")
            assertions[case] = {"status": report["status"],
                "stages": {name: record["status"] for name, record in report["stages"].items()},
                "source_sha256": report["provenance"]["source_sha256"]}
        assertions["import_count"] = len(read(work / "imports.json"))
        assertions["fixture_sha256"] = sha256(copy.read_bytes()).hexdigest()
    finally:
        write(work / "verify.json", {"compiler": str(root), "python": sys.version.split()[0],
            "commands": records, "assertions": assertions})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=lambda path: Path(path).resolve(), required=True)
    parser.add_argument("--work", type=lambda path: Path(path).resolve(), required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--case", choices=("imports", "interrupt", "default", "resume"))
    args = parser.parse_args()
    if args.case:
        cli_case(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
