from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import unittest

from infrastructure import compact_acceptance as acceptance


def result(passed, blocker):
    failures = {key: {'scenario': key, 'error': blocker}
                for key in ('REQ-1', 'REQ-2')[passed:]}
    return {'passed': passed, 'failed': len(failures), 'skipped': 0, 'failures': failures}


class ZeroProgress(unittest.TestCase):
    def test_zero_pass_entry_fix_can_be_kept_then_regression_is_restored(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'app.tsx'
            path.write_text('const first=0; const second=0; const third=0;\n')
            replies = []
            for name in ('first', 'second', 'third'):
                replies.append({'tool_calls': [{
                    'tool': 'edit_file', 'path': 'app.tsx', 'operation': 'replace',
                    'old_content': name + '=0', 'new_content': name + '=1',
                }]})
            model = Mock(generate_json=Mock(side_effect=replies))
            scores = [result(0, 'missing entry'), result(0, 'missing sidebar'),
                      result(1, 'missing content'), result(0, 'missing entry')]
            with (patch.object(acceptance, 'prepare_workspace'),
                  patch.object(acceptance, 'run_suite', side_effect=scores)):
                report = acceptance.repair_with_acceptance(
                    root, root, 'id: ROOT\nname: Test\n', model, lambda: None,
                    ('app.tsx',), allow_zero_progress=True)
            self.assertEqual(report['best']['passed'], 1)
            self.assertTrue(report['attempts'][1]['zero_progress'])
            self.assertTrue(report['attempts'][1]['accepted'])
            self.assertFalse(report['attempts'][3]['accepted'])
            self.assertIn('first=1; const second=1; const third=0', path.read_text())

    def test_default_configuration_rejects_equal_zero_score(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'app.tsx'
            path.write_text('const first=0;\n')
            reply = {'tool_calls': [{'tool': 'edit_file', 'path': 'app.tsx', 'operation': 'replace',
                                    'old_content': 'first=0', 'new_content': 'first=1'}]}
            with (patch.object(acceptance, 'prepare_workspace'),
                  patch.object(acceptance, 'run_suite', side_effect=[
                      result(0, 'entry'), result(0, 'sidebar'), result(0, 'sidebar'), result(0, 'sidebar')])):
                report = acceptance.repair_with_acceptance(
                    root, root, 'id: ROOT\nname: Test\n', Mock(generate_json=Mock(return_value=reply)),
                    lambda: None, ('app.tsx',))
            self.assertEqual(report['best']['passed'], 0)
            self.assertEqual(path.read_text(), 'const first=0;\n')


if __name__ == '__main__':
    unittest.main()
