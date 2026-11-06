from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from infrastructure import compact
from infrastructure.tasks.keep import PROFILE


class GenerationRepair(unittest.TestCase):
    def test_partial_repairs_get_fresh_diagnostics_and_failed_candidate_is_restored(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / 'out'
            diagnostics = []
            frontend_calls = 0
            repair_calls = 0
            client = SimpleNamespace()
            client.with_options = lambda **kwargs: client
            client.close = lambda: None
            model = SimpleNamespace(max_output_tokens=320000, client=client, reasoning='none')

            def initialize(directory, **kwargs):
                for relative in (compact.BACKEND, *compact.FRONTEND):
                    path = directory / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('baseline', encoding='utf-8')

            def generate(prompt, payload):
                nonlocal frontend_calls, repair_calls
                if 'Fix the shown compiler' in prompt:
                    repair_calls += 1
                    diagnostics.append(payload['diagnostics'])
                    # First edit succeeds but the second required repair has a bad anchor.
                    old = 'bad_one' if repair_calls == 1 else 'missing_anchor'
                    return {'tool_calls': [{'tool': 'edit_file', 'path': compact.FRONTEND[0],
                            'operation': 'replace', 'old_content': old, 'new_content': 'good_one'}]}
                if '"files":{"backend/src/api/register.ts"' in prompt:
                    return {'files': {compact.BACKEND: 'backend code'}}
                if 'Style the supplied' in prompt:
                    return {'files': {compact.FRONTEND[1]: 'CSS code'}}
                frontend_calls += 1
                if frontend_calls == 1:
                    return {'files': {compact.FRONTEND[0]: 'const value = bad_one + bad_two;\n'}}
                self.assertEqual((output / compact.FRONTEND[0]).read_text(), 'baseline')
                return {'files': {compact.FRONTEND[0]: 'valid frontend'}}

            def process(command, **kwargs):
                if 'build' in command:
                    content = (output / compact.FRONTEND[0]).read_text()
                    if 'bad_one' in content:
                        return {'returncode': 1, 'output': 'first syntax error'}
                    if 'bad_two' in content:
                        return {'returncode': 1, 'output': 'second syntax error'}
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
                    port=3000, model_log=False, task_profile=replace(PROFILE, generation_attempts=2))
            self.assertEqual(frontend_calls, 2)
            self.assertEqual(repair_calls, 2)
            self.assertEqual(diagnostics, ['first syntax error', 'second syntax error'])
            self.assertEqual((output / compact.FRONTEND[0]).read_text(), 'valid frontend')


if __name__ == '__main__':
    unittest.main()
