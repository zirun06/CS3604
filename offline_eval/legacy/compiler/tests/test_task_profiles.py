"""Verify task isolation and the compiler request trace against the v8 baseline."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from infrastructure import compact
from infrastructure.tasks.profile import DEFAULT
from infrastructure.tasks.registry import PROFILES, select_profile


FIXTURE = Path(__file__).with_name('fixtures') / 'v8_task_traces.json'


def request_trace(engine, profile, *, large=False, truncate=False, legacy=False, use_profile=False,
                  process_trace=None):
    """Observe the normal compile entry using a deterministic model and build runner."""
    requests = []
    proposals = []
    acceptance = []
    client = SimpleNamespace()
    client.with_options = lambda **kwargs: client
    client.close = lambda: None
    model = SimpleNamespace(max_output_tokens=320000, reasoning='none', client=client)
    joint_calls = 0

    def initialize(directory, **kwargs):
        for relative in (engine.BACKEND, *engine.FRONTEND):
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('baseline', encoding='utf-8')

    def generate(prompt, payload):
        nonlocal joint_calls
        requests.append({
            'prompt': sha256(prompt.encode()).hexdigest(),
            'payload': sha256(json.dumps(deepcopy(payload), sort_keys=True).encode()).hexdigest(),
            'budget': model.max_output_tokens, 'reasoning': model.reasoning,
        })
        if '"files":{"backend/src/api/register.ts"' in prompt:
            return {'files': {engine.BACKEND: 'backend code'}}
        if 'Style the supplied' in prompt:
            return {'files': {engine.FRONTEND[1]: 'CSS code'}}
        paths = engine.FRONTEND if '"frontend/src/style.css"' in prompt else engine.FRONTEND[:1]
        if truncate and len(paths) == 2 and joint_calls < 2:
            joint_calls += 1
            raise ValueError('Model output was truncated (finish_reason=length).')
        return {'files': {path: 'frontend code' for path in paths}}

    def propose(*args, **kwargs):
        from infrastructure.shared.agent.proposals import propose_json
        proposals.append(kwargs.get('max_attempts'))
        return propose_json(*args, **kwargs)

    def accept(*args, **kwargs):
        acceptance.append({'budget': model.max_output_tokens, **kwargs})
        return {'status': 'GREEN'}

    def process(command, **kwargs):
        if process_trace is not None:
            process_trace.append(command)
        return {'returncode': 0}

    model.generate_json = generate
    source = 'id: ROOT\nname: Test\n' + ('#' + 'a' * 100001 + '\n' if large else '')
    suite = Path(profile.suite) if profile.suite else None
    with TemporaryDirectory() as temporary, patch.dict(
        'os.environ', {'MODEL_REASONING': 'none', 'VISUAL_REASONING': 'none'}
    ):
        with patch.multiple(
            engine, TextModel=lambda: model, DemoConsole=Mock,
            initialize_project=initialize, bundled_suite=lambda _: suite,
            console_log=lambda *args, **kwargs: nullcontext(),
            install_dependencies=lambda *args, **kwargs: None,
            capture_process=process,
            import_module=lambda _: SimpleNamespace(collect_images=lambda _: []),
            repair_with_acceptance=accept, propose_json=propose,
            ensure_railway_navigation=lambda *a, **k: {'status': 'GREEN'},
            ensure_ctrip_navigation=lambda *a, **k: {'status': 'GREEN'},
            ensure_ctrip_services=lambda *a, **k: {'status': 'GREEN'},
        ):
            options = {'task_profile': profile} if use_profile else {}
            engine.compile_compact(Path(temporary), Path(temporary) / 'out', source,
                                   port=3000, model_log=False, bookstack_legacy=legacy, **options)
    return {'requests': requests, 'proposal_limits': proposals, 'acceptance': acceptance}


class TaskProfiles(unittest.TestCase):
    def test_unique_task_dispatch_and_unknown_input(self):
        self.assertEqual(len(PROFILES), 6)
        self.assertEqual(len({p.key for p in PROFILES}), 6)
        for profile in PROFILES:
            self.assertIs(select_profile(Path(profile.suite)), profile)
        self.assertIs(select_profile(None), DEFAULT)
        self.assertIs(select_profile(Path('unknown-suite')), DEFAULT)

    def test_configuration_is_immutable_and_can_be_tuned_in_isolation(self):
        original = DEFAULT
        with self.assertRaises(FrozenInstanceError):
            original.style_output_tokens = 123
        tuned = replace(original, frontend_prompt='task-specific prompt', style_output_tokens=123)
        self.assertNotEqual(tuned.frontend_prompt, original.frontend_prompt)
        self.assertEqual(tuned.style_output_tokens, 123)
        self.assertEqual(original.style_output_tokens, 6000)
        self.assertEqual(select_profile(None), original)

    def test_requests_match_v8(self):
        baseline = json.loads(FIXTURE.read_text(encoding='utf-8'))
        cases = [(p, p.key != 'bookstack', False, p.key == 'bookstack')
                 for p in PROFILES if p.key not in {'keep', 'prestashop', 'stackoverflow', 'railway12306', 'ctrip'}]
        cases += [(DEFAULT, False, False, False), (DEFAULT, True, False, False),
                  (PROFILES[1], False, False, False)]
        for profile, large, truncate, legacy in cases:
            key = f'{profile.key}:large={large}:truncate={truncate}:legacy={legacy}'
            with self.subTest(case=key):
                self.assertEqual(request_trace(compact, profile, large=large,
                                               truncate=truncate, legacy=legacy), baseline[key])

    def test_tuned_profile_changes_only_its_own_requests(self):
        keep = next(p for p in PROFILES if p.key == 'keep')
        before = request_trace(compact, keep, use_profile=True)
        tuned = replace(keep, frontend_prompt=keep.frontend_prompt + '\nTask-specific edit.',
                        small_output_tokens=12345, generation_attempts=2)
        changed = request_trace(compact, tuned, use_profile=True)
        self.assertEqual(changed['requests'][0]['budget'], 12345)
        self.assertNotEqual(changed['requests'][1]['prompt'], before['requests'][1]['prompt'])
        self.assertEqual(changed['proposal_limits'][1], 2)
        self.assertEqual(request_trace(compact, keep, use_profile=True), before)

    def test_tuned_tasks_always_split_with_separate_budgets(self):
        for key, large, budgets in (
            ('keep', False, [16000, 24000, 10000]),
            ('prestashop', True, [26000, 32000, 10000]),
            ('stackoverflow', True, [26000, 32000, 10000]),
        ):
            with self.subTest(task=key):
                profile = next(p for p in PROFILES if p.key == key)
                trace = request_trace(compact, profile, large=large, use_profile=True)
                self.assertEqual([r['budget'] for r in trace['requests']], budgets)
                self.assertEqual(trace['proposal_limits'], [3, 3, 2])
                self.assertEqual(profile.transient_retries, 2)
                self.assertTrue(profile.rollback_failed_candidates)

    def test_stackoverflow_repair_is_scoped_and_bounded(self):
        profile = next(p for p in PROFILES if p.key == 'stackoverflow')
        trace = request_trace(compact, profile, large=True, use_profile=True)
        acceptance = trace['acceptance'][0]
        self.assertEqual(acceptance['max_repairs'], 4)
        self.assertEqual(acceptance['failure_limit'], 1)
        self.assertEqual(acceptance['edit_retries'], 1)
        self.assertTrue(acceptance['retry_invalid_edits'])
        self.assertTrue(acceptance['adaptive_repairs'])
        self.assertEqual(acceptance['repair_dependencies']['composeQuestion'], 'REQ-3.3')

    def test_railway_preparation_is_scoped_and_requests_are_bounded(self):
        railway = next(p for p in PROFILES if p.key == 'railway12306')
        for profile in PROFILES:
            commands = []
            trace = request_trace(compact, profile, large=True, use_profile=True,
                                  process_trace=commands)
            preparation = [c for c in commands if len(c) > 1 and
                           str(c[1]).endswith('prepare_railway_source.mjs')]
            self.assertEqual(len(preparation), 3 if profile is railway else 0)
            if profile is railway:
                self.assertEqual([c[3] for c in preparation], ['backend', 'frontend', 'frontend'])
                self.assertEqual([r['budget'] for r in trace['requests']], [26000, 32000, 10000])
                self.assertEqual(trace['acceptance'][0]['max_repairs'], 3)
                self.assertEqual(trace['acceptance'][0]['failure_limit'], 2)
                self.assertTrue(trace['acceptance'][0]['adaptive_repairs'])
                self.assertEqual(trace['acceptance'][0]['repair_dependencies']['login'], 'REQ-2.2.2')

    def test_status_association_runs_only_for_stackoverflow_frontend_builds(self):
        for profile in PROFILES:
            with self.subTest(task=profile.key):
                commands = []
                request_trace(compact, profile, large=True, use_profile=True,
                              process_trace=commands)
                passes = [c for c in commands if len(c) > 1 and
                          str(c[1]).endswith('associate_status_labels.mjs')]
                self.assertEqual(len(passes), 2 if profile.key == 'stackoverflow' else 0)
                sql = [c for c in commands if len(c) > 1 and
                       str(c[1]).endswith('validate_sql_inserts.mjs')]
                self.assertEqual(len(sql), 3 if profile.key == 'stackoverflow' else 0)
                api = [c for c in commands if len(c) > 1 and
                       str(c[1]).endswith('probe_backend_contract.mjs')]
                self.assertEqual(len(api), 3 if profile.key == 'stackoverflow' else 0)

    def test_ctrip_contract_is_scoped_and_repairs_are_bounded(self):
        for profile in PROFILES:
            commands=[]
            trace=request_trace(compact,profile,large=True,use_profile=True,process_trace=commands)
            preparation=[c for c in commands if len(c)>1 and str(c[1]).endswith('prepare_ctrip_source.mjs')]
            probes=[c for c in commands if len(c)>1 and str(c[1]).endswith('probe_ctrip_backend.mjs')]
            self.assertEqual(len(preparation),3 if profile.key=='ctrip' else 0)
            self.assertEqual(len(probes),3 if profile.key=='ctrip' else 0)
            if profile.key=='ctrip':
                self.assertEqual([r['budget'] for r in trace['requests']],[26000,32000,10000])
                self.assertEqual(trace['acceptance'][0]['failure_limit'],2)
                self.assertEqual(trace['acceptance'][0]['max_repairs'],3)
                self.assertEqual(trace['acceptance'][0]['repair_dependencies']['registerToPassword'],'REQ-1.6')


if __name__ == '__main__':
    unittest.main()
