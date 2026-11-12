"""Regression tests for launcher exit, Windows file sharing and result publication."""

import json
import os
from pathlib import Path
import sys
from tempfile import mkdtemp
from time import monotonic, sleep
from unittest.mock import Mock

import pytest

from offline_eval import check_deployment
from offline_eval.deployment_process import WindowsDeployment


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object regression")
def test_job_owns_sqlite_child_after_launcher_exit(tmp_path):
    import _winapi

    root = Path(mkdtemp(dir=tmp_path, prefix="arc-deploy-check-"))
    child = ("import sqlite3,time; from pathlib import Path; db=sqlite3.connect('app.db'); "
        "db.execute('CREATE TABLE records (id)'); Path('child-ready').touch(); time.sleep(30)")
    launcher = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',sys.argv[1]])"
    with (root / "deploy.log").open("wb") as log:
        process = WindowsDeployment([sys.executable, "-c", launcher, child], root, {}, log)
        try:
            assert _winapi.WaitForSingleObject(process.process, 10000) == 0
            deadline = monotonic() + 10
            while not (root / "child-ready").is_file() and monotonic() < deadline:
                sleep(0.05)
            assert (root / "app.db").is_file() and process.alive()
        finally:
            process.stop()
    assert check_deployment.remove_temporary(root) == {}
    assert not root.exists()


def test_cleanup_retries_and_emits_result_when_directory_stays_locked(tmp_path, monkeypatch, capsys):
    (tmp_path / "deploy.sh").touch()
    residual = tmp_path / "temporary-db"
    residual.mkdir()
    monkeypatch.setattr(check_deployment, "mkdtemp", lambda **_: str(residual))
    monkeypatch.setattr(check_deployment, "sleep", lambda _: None)
    process = Mock()
    process.alive.return_value = True
    monkeypatch.setattr(check_deployment, "launch", lambda *_: process)
    monkeypatch.setattr(check_deployment, "probe", lambda *_: "/assets/entry.js")
    retry = Mock(side_effect=[PermissionError("locked"), PermissionError("locked"), None])
    monkeypatch.setattr(check_deployment.shutil, "rmtree", retry)
    assert check_deployment.remove_temporary(residual) == {}
    assert retry.call_count == 3

    locked = Mock(side_effect=PermissionError("database remains open"))
    monkeypatch.setattr(check_deployment.shutil, "rmtree", locked)
    monkeypatch.setattr(sys, "argv", ["check_deployment.py", str(tmp_path)])
    assert check_deployment.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "GREEN"
    assert result["cleanup"]["status"] == "FAILED"
    assert Path(result["cleanup"]["residual_path"]) == residual
    assert locked.call_count == 5
    process.stop.assert_called_once()


def test_cli_publishes_failure_if_probe_cannot_create_workspace(tmp_path, monkeypatch, capsys):
    (tmp_path / "deploy.sh").touch()
    monkeypatch.setattr(check_deployment, "deployed", Mock(side_effect=OSError("cannot bind port")))
    monkeypatch.setattr(sys, "argv", ["check_deployment.py", str(tmp_path)])
    assert check_deployment.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "FAILED" and result["error"] == "cannot bind port"
