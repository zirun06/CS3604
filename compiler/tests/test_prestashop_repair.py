from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import unittest

from infrastructure import compact_acceptance as acceptance


class StorefrontRepair(unittest.TestCase):
    def test_failed_anchor_is_retried_without_rebuilding_or_retesting(self):
        failure = {'scenario': 'REQ-1', 'error': 'missing Country combobox'}
        initial = {'passed': 1, 'failed': 1, 'skipped': 0, 'failures': {'one': failure}}
        passed = {'passed': 2, 'failed': 0, 'skipped': 0, 'failures': {}}
        def edit(old):
            return {'tool_calls': [{'tool': 'edit_file', 'path': 'app.tsx', 'operation': 'replace',
                                    'old_content': old, 'new_content': 'select'}]}
        model = Mock(generate_json=Mock(side_effect=[edit('missing anchor'), edit('input')]))
        build = Mock()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.tsx').write_text('const field = "input";\n')
            with (patch.object(acceptance, 'prepare_workspace'),
                  patch.object(acceptance, 'run_suite', side_effect=[initial, passed]) as suite):
                result = acceptance.repair_with_acceptance(
                    root, root, 'id: ROOT\nname: Test\n', model, build, ('app.tsx',),
                    max_repairs=4, failure_limit=6, edit_retries=1)
            self.assertEqual(result['best']['passed'], 2)
            self.assertEqual(model.generate_json.call_count, 2)
            self.assertEqual(suite.call_count, 2)
            self.assertEqual(build.call_count, 1)
            feedback = model.generate_json.call_args.args[1]['previous_repair']
            self.assertTrue(feedback['unapplied_edits'])


if __name__ == '__main__':
    unittest.main()
