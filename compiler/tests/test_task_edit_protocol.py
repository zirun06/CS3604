from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import unittest

from infrastructure import compact_acceptance as acceptance


class EditProtocolRecovery(unittest.TestCase):
    def test_opted_in_protocol_retry_does_not_build_or_test_invalid_edits(self):
        initial = {'passed': 1, 'failed': 1, 'skipped': 0,
                   'failures': {'one': {'scenario': 'REQ-1', 'error': 'missing action'}}}
        passed = {'passed': 2, 'failed': 0, 'skipped': 0, 'failures': {}}
        for enabled in (False, True):
            with self.subTest(enabled=enabled), TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'app.tsx').write_text('const action = "bad";\n')
                valid = {'tool_calls': [{'tool': 'edit_file', 'path': 'app.tsx',
                    'operation': 'replace', 'old_content': 'bad', 'new_content': 'good'}]}
                model = Mock(generate_json=Mock(side_effect=[{'tool_calls': ['invalid']}, valid]))
                build = Mock()
                with (patch.object(acceptance, 'prepare_workspace'),
                      patch.object(acceptance, 'run_suite', side_effect=[initial, passed]) as run):
                    result = acceptance.repair_with_acceptance(root, root, 'id: ROOT\nname: Test\n',
                        model, build, ('app.tsx',), max_repairs=1, edit_retries=1,
                        retry_invalid_edits=enabled)
                self.assertEqual(model.generate_json.call_count, 2 if enabled else 1)
                self.assertEqual(build.call_count, 1 if enabled else 0)
                self.assertEqual(run.call_count, 2 if enabled else 1)
                self.assertEqual(result['best']['passed'], 2 if enabled else 1)
                if enabled:
                    self.assertIn('invalid_edit_protocol', model.generate_json.call_args.args[1]['previous_repair'])


if __name__ == '__main__':
    unittest.main()
