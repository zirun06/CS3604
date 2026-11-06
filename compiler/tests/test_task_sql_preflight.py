from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from infrastructure import compact
from infrastructure.tasks.stackoverflow import PROFILE


class SqlPreflightRecovery(unittest.TestCase):
    def test_invalid_insert_is_repaired_before_frontend_without_backend_regeneration(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / 'out'
            events = []
            client = SimpleNamespace(close=lambda: None)
            client.with_options = lambda **kwargs: client
            model = SimpleNamespace(max_output_tokens=320000, reasoning='none', client=client)

            def initialize(directory, **kwargs):
                for relative in (compact.BACKEND, *compact.FRONTEND):
                    file = directory / relative
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text('baseline', encoding='utf-8')

            def generate(prompt, payload):
                if 'Fix the shown compiler' in prompt:
                    self.assertIn('6 values for 7 columns', payload['diagnostics'])
                    events.append('repair')
                    return {'tool_calls': [{'tool': 'edit_file', 'path': compact.BACKEND,
                        'operation': 'replace', 'old_content': 'bad_insert', 'new_content': 'valid_insert'}]}
                if '"files":{"backend/src/api/register.ts"' in prompt:
                    events.append('backend')
                    return {'files': {compact.BACKEND: 'const sql = "bad_insert";\nexport const registered = true;\n'}}
                if 'Style the supplied' in prompt:
                    return {'files': {compact.FRONTEND[1]: 'style'}}
                events.append('frontend')
                self.assertIn('valid_insert', (output / compact.BACKEND).read_text())
                return {'files': {compact.FRONTEND[0]: 'frontend'}}

            def process(command, **kwargs):
                if len(command) > 1 and str(command[1]).endswith('validate_sql_inserts.mjs'):
                    if 'bad_insert' in (output / compact.BACKEND).read_text():
                        return {'returncode': 1, 'output': 'register.ts:42: 6 values for 7 columns'}
                return {'returncode': 0}

            model.generate_json = generate
            with patch.multiple(
                compact, TextModel=lambda: model, DemoConsole=Mock,
                initialize_project=initialize, console_log=lambda *a, **k: nullcontext(),
                install_dependencies=lambda *a, **k: None, bundled_suite=lambda _: Path(PROFILE.suite),
                capture_process=process, import_module=lambda _: SimpleNamespace(collect_images=lambda _: []),
                repair_with_acceptance=lambda *a, **k: {'status': 'GREEN'},
            ):
                compact.compile_compact(Path(temporary), output, 'id: ROOT\nname: Test\n',
                    port=3000, model_log=False, task_profile=PROFILE)
            self.assertEqual(events, ['backend', 'repair', 'frontend'])


if __name__ == '__main__':
    unittest.main()
