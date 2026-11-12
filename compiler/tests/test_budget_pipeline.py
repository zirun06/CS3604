"""Budget report continuation and real output-local Git rollback checks."""

import json
from unittest.mock import Mock

import pytest

import main
import infrastructure.compiler as compiler_module
from infrastructure.compiler import Compiler
from infrastructure.shared.project.git import GitError, GitRepository
from infrastructure.shared.project.provenance import CHECKPOINT
from infrastructure.utils.budget import RunBudget, active_budget
from infrastructure.utils.files import save_json
from infrastructure.utils.presentation.events import validation_event


STAGE0 = "00_project_initialization"
STAGE1 = "01_explore_requirement"
STAGE2 = "02_build_db_schema"
STAGE3 = "03_infer_db_obligations"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def fixture_pipeline(tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.mkdir()
    (source / "requirements.yaml").write_bytes(b"id: R\nname: Sample\n")
    (source / "reference.png").write_bytes(b"fixture reference bytes")
    output = tmp_path / "generated"

    def requirements(arc, **_):
        save_json(arc / "requirements.json", {"id": "R"})

    def schema(arc, **_):
        save_json(arc / "db_schema.json", {"requirements": read(arc / "requirements.json")})

    def obligations(arc, **_):
        save_json(arc / "db_obligations.json", read(arc / "db_schema.json"))

    passes = ((STAGE0, compiler_module.project_initialization, "project_files"),
        (STAGE1, requirements, "requirements"), (STAGE2, schema, "db_schema"),
        (STAGE3, obligations, "db_obligations"))
    monkeypatch.setattr(compiler_module, "PIPELINE", passes)
    monkeypatch.setattr(main, "PIPELINE", passes)
    return source, output


@pytest.mark.parametrize(("flag", "stages"), [("--stage", [STAGE2]), ("--from-stage", [STAGE2, STAGE3])])
def test_cli_resumes_verified_checkpoint(fixture_pipeline, flag, stages):
    source, output = fixture_pipeline
    argv = [str(source), "--output-dir", str(output)]
    main.main(argv)
    prior = read(output / ".arc/compilation.json")
    before = (output / ".arc/db_schema.json").read_bytes()
    main.main([*argv, flag, STAGE2])
    after = read(output / ".arc/compilation.json")
    assert list(after["stages"]) == stages and after["status"] == "GREEN"
    assert after["run_id"] != prior["run_id"] and after["workspace_id"] == prior["workspace_id"]
    assert (output / ".arc/db_schema.json").read_bytes() == before
    assert (output / ".arc/db_obligations.json").exists() == (flag == "--from-stage")


@pytest.mark.parametrize("change", ["input", "reference", "configuration", "source"])
def test_rollback_rejects_changed_provenance(fixture_pipeline, monkeypatch, change):
    source, output = fixture_pipeline
    Compiler(source, output).compile()
    repository = GitRepository(output)
    before = repository.run("rev-parse", "HEAD").stdout
    if change == "input":
        (source / "requirements.yaml").write_bytes(b"id: CHANGED\n")
    elif change == "reference":
        (source / "reference.png").write_bytes(b"different reference bytes")
    elif change == "configuration":
        monkeypatch.setenv("MODEL", "other-model")
    else:
        original = compiler_module.provenance
        monkeypatch.setattr(compiler_module, "provenance",
            lambda *args: {**original(*args), "source_sha256": "changed"})
    with pytest.raises(GitError, match="does not match"):
        Compiler(source, output).compile(stage=STAGE2)
    assert repository.run("rev-parse", "HEAD").stdout == before


def test_rollback_rejects_artifact_and_unowned_repository(fixture_pipeline, tmp_path):
    source, output = fixture_pipeline
    Compiler(source, output).compile(stage=STAGE0)
    Compiler(source, output).compile(stage=STAGE1)
    repository = GitRepository(output)
    path = output / ".arc/requirements.json"
    save_json(path, {"id": "tampered"})
    repository.add()
    revision = repository.commit(f"[{STAGE1}] stage report: Publish pass result (GREEN)")
    with pytest.raises(GitError, match="artifact mismatch"):
        Compiler(source, output).compile(stage=STAGE2)
    assert repository.run("rev-parse", "HEAD").stdout.strip() == revision

    foreign = tmp_path / "existing"
    GitRepository(foreign).initialize()
    with pytest.raises(GitError, match="recognized generated"):
        Compiler(source, foreign).compile(stage=STAGE1)
    with pytest.raises(ValueError, match="recognized generated"):
        Compiler(source, foreign).compile()


def test_exhausted_model_still_allows_deterministic_stages(fixture_pipeline, monkeypatch):
    source, output = fixture_pipeline
    stages = compiler_module.PIPELINE

    def model_stage(arc, **_):
        save_json(arc / "db_schema.json", {"retained": True})
        active_budget().start_call()

    def deterministic_stage(arc, **_):
        assert read(arc / "db_schema.json")["retained"]
        validation_event("database_check", 0.25, "passed")
        save_json(arc / "db_obligations.json", {"checked": True})

    monkeypatch.setattr(compiler_module, "PIPELINE", (*stages[:2],
        (STAGE2, model_stage, "db_schema"), (STAGE3, deterministic_stage, "db_obligations")))
    monkeypatch.setenv("COMPILER_BUDGET_CALLS", "0")
    Compiler(source, output).compile()
    report = read(output / ".arc/compilation.json")
    assert report["status"] == "COMPLETED_WITH_FAILURES"
    assert report["stages"][STAGE2]["status"] == "BUDGET_EXHAUSTED"
    assert report["stages"][STAGE3]["status"] == "GREEN"
    assert report["stages"][STAGE3]["validations"]["database_check"]["pass_rate"] == 1
    assert report["stages"][STAGE3]["first_validation_seconds"] >= 0
    assert read(output / ".arc/db_obligations.json")["checked"]
    with pytest.raises(GitError, match="did not complete"):
        Compiler(source, output).compile(stage=STAGE3)
    assert read(output / CHECKPOINT)["stage"] == STAGE1


def test_deadline_skips_remaining_passes_and_retains_report(fixture_pipeline, monkeypatch):
    source, output = fixture_pipeline
    stages = compiler_module.PIPELINE
    now = [0.0]
    budget = RunBudget({"seconds": 20}, clock=lambda: now[0], stages=len(stages))
    monkeypatch.setattr(RunBudget, "from_settings", lambda *_: budget)

    def time_out(arc, **_):
        save_json(arc / "requirements.json", {"retained": True})
        now[0] = 21
        budget.check_time()

    later = Mock()
    monkeypatch.setattr(compiler_module, "PIPELINE", (stages[0],
        (STAGE1, time_out, "requirements"), (STAGE2, later, "db_schema"),
        (STAGE3, later, "db_obligations")))
    Compiler(source, output).compile()
    later.assert_not_called()
    report = read(output / ".arc/compilation.json")
    assert [entry["status"] for entry in report["stages"].values()] == [
        "GREEN", "BUDGET_EXHAUSTED", "SKIPPED_TIME", "SKIPPED_TIME"]
    assert report["status"] == "COMPLETED_WITH_FAILURES"
    assert read(output / ".arc/requirements.json")["retained"]


def test_interrupt_retains_stage_and_run_status(fixture_pipeline, monkeypatch):
    source, output = fixture_pipeline
    initial = compiler_module.PIPELINE[0]

    def interrupt(arc, **_):
        save_json(arc / "requirements.json", {"retained": True})
        raise KeyboardInterrupt

    monkeypatch.setattr(compiler_module, "PIPELINE", (initial, (STAGE1, interrupt, "requirements")))
    with pytest.raises(KeyboardInterrupt):
        Compiler(source, output).compile()
    report = read(output / ".arc/compilation.json")
    assert report["status"] == report["stages"][STAGE1]["status"] == "INTERRUPTED"
    assert read(output / ".arc/requirements.json")["retained"]
