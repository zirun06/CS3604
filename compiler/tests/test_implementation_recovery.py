"""Failed tasks leave evidence, restore sources, and do not stop independent work."""
from tool_fixtures import propose_files

from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from infrastructure.compiler import Compiler
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.loop import AgentExhausted, run_file_agent
from infrastructure.shared.agent.recovery import implementation_task, final_checks
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.frontend.ui import implementation as ui_implementation
from infrastructure.utils.files import save_bytes, save_text


class ImplementationRecovery(unittest.TestCase):

    def test_fatal_io_and_interrupts_are_not_suppressed(self):
        with TemporaryDirectory() as temporary:
            for error in (OSError('Disk unavailable'), KeyboardInterrupt(), KeyError('compiler defect')):
                with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                    with implementation_task(Path(temporary), {}, Mock(), 'task'):
                        raise error

    def test_final_tests_and_build_run_even_after_compilation_and_test_failure(self):
        compile_check = Mock(return_value={'returncode': 1, 'output': 'Compilation failed'})
        tests = Mock(return_value={'returncode': 0, 'tests': 0})
        build = Mock(return_value={'returncode': 0, 'output': 'Built'})
        from infrastructure.stages.backend.testing import require_green
        result = final_checks(Mock(), compile=(compile_check, None), tests=(tests, require_green), build=(build, None))
        self.assertEqual([value['status'] for value in result.values()], ['FAILED', 'FAILED', 'GREEN'])
        for action in (compile_check, tests, build):
            action.assert_called_once_with()






if __name__ == '__main__':
    unittest.main()
