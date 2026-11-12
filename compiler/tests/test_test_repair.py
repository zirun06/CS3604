"""Repair generated tests against requirements and keep UI smoke checks minimal."""
from tool_fixtures import propose_files

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.frontend.ui import implementation
from infrastructure.stages.frontend.ui.testing import existence_suite, parse_playwright_result
from infrastructure.utils.files import save_text


class TestRepair(unittest.TestCase):



    def test_environment_diagnostics_survive_playwright_report_parsing(self):
        import json
        report = {'stats': {}, 'errors': [{'message': 'webServer failed'}], 'suites': []}
        parsed = parse_playwright_result({'returncode': 1, 'stdout': json.dumps(report),
            'stderr': 'Error: listen EADDRINUSE 127.0.0.1:41234', 'output': 'full original output'})
        self.assertIn('EADDRINUSE', parsed['stderr'])
        self.assertIn('EADDRINUSE', parsed['output'])


if __name__ == '__main__':
    unittest.main()
