from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import unittest
import yaml

from infrastructure import compact_acceptance as acceptance


SOURCE = 'id: ROOT\nname: Test\n'


class AdaptiveRepair(unittest.TestCase):
    def test_setup_failure_receives_the_prerequisite_spec_and_omits_unrelated_branches(self):
        source = yaml.safe_dump({'id': 'ROOT', 'name': 'Test', 'children': [
            {'id': 'REQ-3.3', 'name': 'Publish a question', 'children': []},
            {'id': 'REQ-3.10', 'name': 'Protect ownership', 'children': []},
            {'id': 'REQ-7.1', 'name': 'Unrelated history', 'children': []}]})
        failure = {'scenario': 'REQ-3.10: Protect ownership',
            'error': 'Locator: Title\n   at helpers.ts:83\n'
                     '    at composeQuestion (C:\\tests\\helpers.ts:83:20)'}
        before = acceptance.repair_context(source, [failure], attempted={})
        self.assertNotIn('REQ-3.3', before['requirements_yaml'])
        after = acceptance.repair_context(source, [failure], attempted={},
                    dependencies={'composeQuestion': 'REQ-3.3'})
        ids = [n['id'] for n in yaml.safe_load(after['requirements_yaml'])['children']]
        self.assertEqual(ids, ['REQ-3.3', 'REQ-3.10'])

    def test_shared_action_origin_groups_varying_records_but_not_context_wrappers(self):
        def error(title, origin='helpers.ts:61'):
            return {'scenario': title, 'error': f"Locator: heading {title}\n   at {origin}\n"
                    '    at openQuestion (C:\\tests\\helpers.ts:61:30)\n'
                    '    at asUser (C:\\tests\\helpers.ts:105:10)'}
        failures = [error('first record'), error('second record')]
        old = acceptance.repair_context(SOURCE, failures)
        self.assertEqual(len(old['failures']), 2)
        new = acceptance.repair_context(SOURCE, failures, attempted={})
        self.assertEqual(new['failures'][0]['affected_cases'], 2)
        self.assertEqual(new['failures'][0]['failure_group'], 'helper:openQuestion:61')
        wrapped = acceptance.repair_context(SOURCE, [error('one', 'REQ-1.spec.ts:4'),
                                                    error('two', 'REQ-2.spec.ts:9')], attempted={})
        self.assertEqual(len(wrapped['failures']), 2)

    def test_tested_no_progress_cluster_is_deprioritized_and_legacy_order_is_unchanged(self):
        failures = [{'scenario': str(i), 'error': 'Locator: revisions'} for i in range(3)]
        failures += [{'scenario': str(i), 'error': 'Locator: search'} for i in range(2)]
        initial = acceptance.repair_context(SOURCE, failures, 1, attempted={})['failures'][0]
        usage = {initial['failure_group']: 1}
        next_item = acceptance.repair_context(SOURCE, failures, 1, attempted=usage)['failures'][0]
        self.assertEqual(next_item['error'], 'Locator: search')
        self.assertEqual(acceptance.repair_context(SOURCE, failures, 1)['failures'][0]['error'],
                         'Locator: revisions')

    def test_rotation_is_applied_after_a_real_candidate_test_and_keeps_rollback(self):
        failures = {str(i): {'scenario': str(i), 'error': 'Locator: ' + ('revisions' if i < 3 else 'search')}
                    for i in range(5)}
        initial = {'passed': 1, 'failed': 5, 'skipped': 0, 'failures': failures}
        passed = {'passed': 6, 'failed': 0, 'skipped': 0, 'failures': {}}
        edit = {'tool_calls': [{'tool': 'edit_file', 'path': 'app.tsx', 'operation': 'replace',
                                'old_content': 'bad', 'new_content': 'good'}]}
        model = Mock(generate_json=Mock(return_value=edit))
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'app.tsx').write_text('const action = "bad";\n')
            with (patch.object(acceptance, 'prepare_workspace'),
                  patch.object(acceptance, 'run_suite', side_effect=[initial, initial, passed])):
                result = acceptance.repair_with_acceptance(root, root, SOURCE, model, Mock(),
                    ('app.tsx',), max_repairs=2, failure_limit=1, adaptive_repairs=True)
            contexts = [call.args[1]['failures'][0]['error'] for call in model.generate_json.call_args_list]
            self.assertEqual(contexts, ['Locator: revisions', 'Locator: search'])
            self.assertFalse(result['attempts'][1]['accepted'])
            self.assertTrue(result['attempts'][2]['accepted'])
            self.assertEqual(result['best']['passed'], 6)


if __name__ == '__main__':
    unittest.main()
