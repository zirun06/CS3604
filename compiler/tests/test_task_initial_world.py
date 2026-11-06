import json
import unittest

import yaml

from infrastructure.tasks.initial_world import initial_world


class InitialWorld(unittest.TestCase):
    def test_only_explicit_given_prerequisites_are_indexed_without_losing_variants(self):
        record = {'title': 'Historical question', 'score': 3,
                  'comments': [{'body': 'Existing comment', 'author': 'owner'}]}
        row = '- public historical question index: ' + json.dumps({'questions': [record]})
        changed = {**record, 'score': 4}
        source = yaml.safe_dump({'id': 'ROOT', 'name': 'Test',
            'description': {'text': '- public historical question index: ' +
                json.dumps({'questions': [{'title': 'Not a Given prerequisite'}]})},
            'scenarios': [{'steps': [{'Given': row}, {'Given': row + '\n' +
                '- public historical question index: ' + json.dumps({'questions': [changed]}) + '\n' +
                '- UI-created examples: ' + json.dumps({'questions': [{'title': 'Runtime only'}]}) + '\n' +
                '- tag catalog: ' + json.dumps({'tags': [{'name': 'python', 'question_count': 10}]})}]}]})
        world = initial_world(source)
        self.assertEqual(world['historical_questions'], [record, changed])
        self.assertEqual(world['tag_catalog'], [{'name': 'python', 'question_count': 10}])
        self.assertEqual(world['other_prerequisites'], {})


if __name__ == '__main__':
    unittest.main()
