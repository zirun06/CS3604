"""Portable I/O and process regressions; run with unittest on Linux or Windows."""
from tool_fixtures import propose_files

import json
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path, PureWindowsPath
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.utils.files import read_artifact, read_source, save_json, save_text
from infrastructure.utils.paths import relative_path
from infrastructure.utils import processes


class PortableFiles(unittest.TestCase):
    """Exercise real edits and rollback with Windows-created source and Unicode paths."""

    def setUp(self):
        """Create an output root whose name requires correct Unicode/space handling."""
        self.temporary = TemporaryDirectory(prefix="arc portable ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "Workspace \u793a\u4f8b"
        self.root.mkdir()

    def test_lf_publication_and_bom_input(self):
        """Prevent CRCRLF growth without collapsing intentional blank lines."""
        source = self.root / "sample.ts"
        save_text(source, "first\r\r\n\r\nsecond\r\n")
        self.assertEqual(source.read_bytes(), b"first\n\nsecond\n")
        source.write_bytes(b"\xef\xbb\xbfhello\r\n")
        self.assertEqual(read_source(source), "hello\n")
        artifact = self.root / "data.json"
        artifact.write_bytes(b"\xef\xbb\xbf" + '{"name":"\u793a\u4f8b"}'.encode())
        self.assertEqual(read_artifact(self.root, "data.json"), {"name": "\u793a\u4f8b"})
        save_json(artifact, {"name": "\u793a\u4f8b"})
        self.assertNotIn(b"\r", artifact.read_bytes())





    def test_initialization_preserves_existing_sources(self):
        """Use portable LF templates under a path containing spaces and Unicode."""
        created = initialize_project(self.root)
        self.assertTrue(created)
        target = self.root / "frontend/src/App.tsx"
        self.assertNotIn(b"\r", target.read_bytes())
        target.write_bytes(b"// user code\r\n")
        self.assertEqual(initialize_project(self.root), [])
        self.assertEqual(target.read_bytes(), b"// user code\r\n")



class PortableProcesses(unittest.TestCase):
    """Test actual command arguments and mocked Windows process control without a shell."""

    def test_npm_cmd_resolves_to_node_cli(self):
        """Spaces in npm's Windows installation directory must not become shell syntax."""
        with TemporaryDirectory(prefix="Program Files ") as temporary:
            directory = Path(temporary)
            node = directory / "node.exe"
            launcher = directory / "npm.cmd"
            cli = directory / "node_modules/npm/bin/npm-cli.js"
            node.touch(); launcher.touch(); cli.parent.mkdir(parents=True); cli.touch()
            with patch.object(processes.shutil, "which", side_effect=lambda name: str(node if name == "node" else launcher)):
                self.assertEqual(processes.npm_command(), [str(node), str(cli)])

    def test_windows_group_and_owned_tree_cleanup(self):
        """Windows uses CREATE_NEW_PROCESS_GROUP/taskkill rather than POSIX signals."""
        self.assertEqual(processes.child_environment({"PYTHONUTF8": "0"})["PYTHONUTF8"], "1")
        process = Mock(pid=321)
        process.poll.return_value = 0
        with patch.object(processes, "WINDOWS", True), patch.object(processes.subprocess, "run") as run, patch.object(processes.shutil, "which", return_value="taskkill.exe"):
            self.assertIn("creationflags", processes.process_options())
            self.assertNotIn("start_new_session", processes.process_options())
            processes.stop_process(process)
            self.assertEqual(run.call_args.args[0], ["taskkill.exe", "/PID", "321", "/T", "/F"])

    def test_utf8_arguments_environment_and_cwd(self):
        """Capture real Unicode child output and arguments with shell metacharacters intact."""
        with TemporaryDirectory(prefix="arc cwd ") as temporary:
            directory = Path(temporary) / "\u793a\u4f8b & space"
            directory.mkdir()
            value = "space & percent% \u793a\u4f8b"
            result = processes.capture_process([sys.executable, "-c",
                "import json,os,sys;print(json.dumps([sys.argv[1],os.getcwd(),os.environ['PYTHONIOENCODING']],ensure_ascii=False))", value], cwd=directory, timeout=10)
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(json.loads(result["stdout"]), [value, str(directory), "utf-8"])

    def test_timeout_stops_descendants(self):
        """A timed-out parent must not leave a heartbeat-writing child alive."""
        if processes.WINDOWS:
            # Some sandboxed hosts deny taskkill even on a child owned by this test.
            probe = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
            try:
                result = subprocess.run(["taskkill", "/PID", str(probe.pid), "/T", "/F"],
                    capture_output=True, timeout=6)
                if result.returncode and b"access denied" in result.stderr.lower():
                    self.skipTest("Windows host denies taskkill on a test-owned child")
            finally:
                if probe.poll() is None:
                    probe.kill()
                probe.wait(timeout=6)
        with TemporaryDirectory(prefix="arc process ") as temporary:
            directory = Path(temporary)
            marker = directory / "heartbeat"
            child = "import time,pathlib; p=pathlib.Path('heartbeat'); end=time.monotonic()+5;\nwhile time.monotonic()<end:\n p.open('a').write('x'); time.sleep(.03)"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(60)"
            with self.assertRaises(subprocess.TimeoutExpired):
                processes.capture_process([sys.executable, "-c", parent, child], cwd=directory, timeout=2)
            self.assertTrue(marker.is_file())
            before = marker.read_bytes()
            time.sleep(.2)
            after = marker.read_bytes()
            if before != after:
                # Wait for the bounded test child to release cwd before removing it.
                time.sleep(5)
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
