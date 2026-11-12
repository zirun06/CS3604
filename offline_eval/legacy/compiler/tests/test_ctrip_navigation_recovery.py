from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import unittest

from infrastructure.tasks import ctrip_navigation as stage


class NavigationRecovery(unittest.TestCase):
    def run_stage(self, *, session_blocked=False, reject_build=False, entry_blocked=False):
        with TemporaryDirectory() as directory:
            output=Path(directory); app=output/stage.APP
            app.parent.mkdir(parents=True); app.write_bytes(b'original app')
            old_client=SimpleNamespace(with_options=lambda **kwargs: SimpleNamespace())
            model=SimpleNamespace(max_output_tokens=32000, reasoning='low', client=old_client,
                                  generate_json=Mock(return_value={'components':{'App':'candidate'}}))
            probes=0
            def process(command, **kwargs):
                nonlocal probes
                if 'inspect' in command: value={'replaceable_components':{'App':'original'}}
                elif 'apply' in command:
                    app.write_bytes(b'candidate');value={'replaced':1}
                else:
                    probes+=1
                    value={'status':'FAILED','step':'password login' if session_blocked else 'entry Log in link' if entry_blocked else 'personal center'} if probes==1 else {'status':'GREEN'}
                return {'returncode':0,'stdout':json.dumps(value),'output':''}
            def build():
                if reject_build and app.read_bytes()==b'candidate': raise ValueError('candidate type error')
            with patch.object(stage,'prepare_workspace'), patch.object(stage,'capture_process',side_effect=process):
                result=stage.ensure_navigation(Path('suite'),output,model,build)
            self.assertEqual(model.max_output_tokens,32000);self.assertEqual(model.reasoning,'low');self.assertIs(model.client,old_client)
            return result,app.read_bytes(),model.generate_json.call_count

    def test_green_gate_accepts_component_candidate_and_restores_model_settings(self):
        result,content,calls=self.run_stage()
        self.assertEqual(result['status'],'GREEN');self.assertEqual(content,b'candidate');self.assertEqual(calls,1)

    def test_failed_candidates_restore_original_and_do_not_abort_compilation(self):
        result,content,calls=self.run_stage(reject_build=True)
        self.assertEqual(result['status'],'FAILED');self.assertEqual(content,b'original app');self.assertEqual(calls,2)

    def test_session_failure_does_not_spend_layout_repair_budget(self):
        result,content,calls=self.run_stage(session_blocked=True)
        self.assertEqual(result['status'],'BLOCKED_BY_SESSION');self.assertEqual(content,b'original app');self.assertEqual(calls,0)

    def test_entry_click_failure_is_not_misclassified_as_backend_authentication(self):
        result,content,calls=self.run_stage(entry_blocked=True)
        self.assertEqual(result['status'],'GREEN');self.assertEqual(content,b'candidate');self.assertEqual(calls,1)


if __name__=='__main__':unittest.main()
