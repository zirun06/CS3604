import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from infrastructure.tasks import ctrip_services as stage


class ServiceRecovery(unittest.TestCase):
    def exercise(self, *, regression=False, broken_build=False, unavailable=False):
        with TemporaryDirectory() as directory:
            output=Path(directory); app=output/stage.APP
            app.parent.mkdir(parents=True); app.write_bytes(b'original')
            client=SimpleNamespace(with_options=lambda **kw: SimpleNamespace())
            model=SimpleNamespace(max_output_tokens=32000, reasoning='low', client=client,
                                  generate_json=Mock(return_value={'components':{'Airports':'new'}}))
            def process(command, **kw):
                if 'inspect-services' in command:
                    value={'replaceable_components':{} if unavailable else {'Airports':'old'}}
                else:
                    app.write_bytes(b'candidate');value={'replaced':1}
                return {'returncode':0,'stdout':json.dumps(value),'output':''}
            initial={'passed':1,'failed':2,'skipped':0,'failures':{'a':{},'b':{}}}
            candidate={'passed':2,'failed':1,'skipped':0,'failures':{'old-pass':{}}} if regression else {'passed':3,'failed':0,'skipped':0,'failures':{}}
            def build():
                if broken_build and app.read_bytes()==b'candidate':raise ValueError('type error')
            with patch.object(stage,'prepare_workspace'),patch.object(stage,'capture_process',side_effect=process),patch.object(stage,'run_suite',side_effect=[initial,candidate,candidate]):
                report=stage.ensure_services(Path('suite'),output,model,build)
            self.assertEqual(model.max_output_tokens,32000);self.assertEqual(model.reasoning,'low');self.assertIs(model.client,client)
            return report,app.read_bytes(),model.generate_json.call_count

    def test_accepts_verified_gain(self):
        report,source,calls=self.exercise()
        self.assertEqual(report['status'],'GREEN');self.assertEqual(source,b'candidate');self.assertEqual(calls,1)

    def test_rejects_higher_score_with_prior_case_regression(self):
        report,source,calls=self.exercise(regression=True)
        self.assertEqual(report['best']['passed'],1);self.assertEqual(source,b'original');self.assertEqual(calls,2)

    def test_build_failure_rolls_back_and_continues(self):
        report,source,calls=self.exercise(broken_build=True)
        self.assertEqual(report['status'],'PARTIAL');self.assertEqual(source,b'original');self.assertEqual(calls,2)

    def test_no_named_service_owner_skips_without_spending_model_budget(self):
        report,source,calls=self.exercise(unavailable=True)
        self.assertEqual(report['status'],'UNAVAILABLE');self.assertEqual(source,b'original');self.assertEqual(calls,0)


if __name__=='__main__':unittest.main()
