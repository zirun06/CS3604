"""Index only startup prerequisites explicitly embedded in scenario Given text."""

import json
import re

import yaml


COLLECTIONS = {
    'public historical question index': ('questions', 'historical_questions'),
    'tag catalog': ('tags', 'tag_catalog'),
}
OTHER = {'badge catalog and earned event', 'owner activity and reputation history'}
ROW = re.compile(r'^\s*- ([^\n:]+): (\{[^\n]+\})[ \t]*$', re.MULTILINE)


def initial_world(source: str) -> dict:
    """Deduplicate complete records without merging conflicting declared variants."""
    result = {'historical_questions': [], 'tag_catalog': [], 'other_prerequisites': {}}
    seen = {}

    def add(collection, value):
        identity = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if identity not in seen.setdefault(collection, set()):
            seen[collection].add(identity)
            return True
        return False

    def given(text):
        for match in ROW.finditer(text):
            category, raw = match.groups()
            if category not in COLLECTIONS and category not in OTHER:
                continue
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if category in COLLECTIONS:
                field, target = COLLECTIONS[category]
                values = data.get(field)
                if isinstance(values, list):
                    for record in values:
                        if isinstance(record, dict) and add(target, record):
                            result[target].append(record)
            elif add(category, data):
                result['other_prerequisites'].setdefault(category, []).append(data)

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'Given' and isinstance(value, str):
                    given(value)
                else:
                    visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(yaml.safe_load(source))
    return result
