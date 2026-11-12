import json
from pathlib import Path
import unittest

import yaml

from infrastructure.tasks.railway_context import prepare_context, expand_context


class RailwayContext(unittest.TestCase):
    def test_real_requirements_roundtrip_preserves_every_field_and_seed(self):
        root = Path(__file__).resolve().parents[2]
        path = root / 'requirements/arc-bench-web--12306/requirements.yaml'
        if not path.is_file():
            self.skipTest('Course requirements live outside the standalone compiler ZIP')
        source = path.read_text(encoding='utf-8')
        prepared = prepare_context(source)
        self.assertEqual(expand_context(yaml.safe_load(prepared['requirements_yaml'])), yaml.safe_load(source))
        self.assertLess(len(prepared['requirements_yaml']), len(source) * .75)
        records = prepared['declared_railway_world']['seed_records']
        self.assertEqual(len(records['verified account directory']), 27)
        self.assertEqual(len(records['published services']), 9)

    def test_only_given_catalog_records_are_indexed_and_variants_are_retained(self):
        seed = '- published services: {"route":{"date":[{"number":"G7"}]}}'
        variant = '- published services: {"route":{"date":[{"number":"G8"}]}}'
        ignored = '- frequent passengers: {"name":"UI-created person"}'
        long = 'Text with unicode 上海 and punctuation: ' * 9
        root = {'id': 'ROOT', 'name': 'Railway', 'description': {'text': long + '\n\n' + long},
                'scenarios': [{'steps': [{'Given': seed + '\n' + seed + '\n' + variant + '\n' + ignored,
                                         'When': '- station directory: {"locations":["Not startup"]}'}]}],
                'children': []}
        prepared = prepare_context(yaml.safe_dump(root, allow_unicode=True))
        self.assertEqual(expand_context(yaml.safe_load(prepared['requirements_yaml'])), root)
        records = prepared['declared_railway_world']['seed_records']
        self.assertEqual(len(records['published services']), 2)
        self.assertEqual(records['station directory'], [])
        self.assertNotIn('frequent passengers', records)

    def test_reserved_marker_cannot_silently_change_original_text(self):
        with self.assertRaises(ValueError):
            prepare_context('name: "{{ARC_SHARED_0001}}"')


if __name__ == '__main__':
    unittest.main()
