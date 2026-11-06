from pathlib import Path
import unittest
import yaml
from infrastructure.tasks.ctrip_context import prepare_context,expand_context

class CtripContext(unittest.TestCase):
    def test_full_requirement_roundtrip_and_seed_views(self):
        path=Path(__file__).resolve().parents[2]/'requirements/arc-bench-web--ctrip/requirements.yaml'
        if not path.is_file():self.skipTest('Full course requirements live outside standalone ZIP')
        source=path.read_text(encoding='utf-8');packet=prepare_context(source)
        self.assertEqual(expand_context(yaml.safe_load(packet['requirements_yaml'])),yaml.safe_load(source))
        self.assertLess(len(packet['requirements_yaml']),len(source)*.8)
        self.assertEqual(len(packet['declared_ctrip_world']['seed_records']['existing verified accounts']),39)
    def test_only_explicit_given_records_are_indexed(self):
        source=yaml.safe_dump({'Given':'- published booking inventory: {"flights":[{"number":"MU1","dataset":"booking"}]}\n- published booking inventory: {"flights":[{"number":"MU1","dataset":"status"}]}',
            'When':'- imaginary startup: {"name":"not startup"}'})
        packet=prepare_context(source);records=packet['declared_ctrip_world']['seed_records']
        self.assertEqual(len(records['published booking inventory']),2);self.assertNotIn('imaginary startup',records)
        self.assertEqual(expand_context(yaml.safe_load(packet['requirements_yaml'])),yaml.safe_load(source))

if __name__=='__main__':unittest.main()
