"""Lossless repeated-line factoring and startup evidence for the railway task."""

from collections import Counter
import json
import re

import yaml


SEED_ROW = re.compile(r'^\s*- ([^\n:]+): (\{[^\n]+\})[ \t]*$', re.MULTILINE)
CATEGORIES = {'verified account directory', 'station directory', 'published services',
              'published transfer segments', 'travel guidance content'}
MARKER = '{{ARC_SHARED_'


def map_strings(node, transform):
    if isinstance(node, dict):
        return {key: map_strings(value, transform) for key, value in node.items()}
    if isinstance(node, list):
        return [map_strings(value, transform) for value in node]
    return transform(node) if isinstance(node, str) else node


def prepare_context(source: str) -> dict:
    """Preserve every requirement/scenario while defining repeated long lines once."""
    root = yaml.safe_load(source)
    counts = Counter()

    def count(value):
        if MARKER in value:
            raise ValueError('Railway requirement text contains a reserved shared-text marker')
        counts.update(line for line in value.split('\n') if len(line) >= 160)
        return value

    map_strings(root, count)
    blocks = {f'{MARKER}{index:04d}}}}}': line for index, (line, count) in
              enumerate(((line, count) for line, count in counts.items() if count > 1), 1)}
    references = {line: token for token, line in blocks.items()}
    tree = map_strings(root, lambda value: '\n'.join(
        references.get(line, line) for line in value.split('\n')))
    packet = {'format': 'Expand shared_text_blocks tokens literally wherever they occur. '
              'They carry the full original constraints, including scenario seed data. '
              'All requirements and scenarios below are mandatory.',
              'shared_text_blocks': blocks, 'requirements': tree}
    return {'requirements_yaml': yaml.safe_dump(packet, allow_unicode=True, sort_keys=False,
                                                width=100000),
            'declared_railway_world': startup_world(root),
            'metrics': {'original_characters': len(source), 'shared_blocks': len(blocks)}}


def expand_context(packet: dict) -> dict:
    """Reconstruct the parsed source tree for audit/testing, without model inference."""
    blocks = packet['shared_text_blocks']
    return map_strings(packet['requirements'], lambda value: '\n'.join(
        blocks.get(line, line) for line in value.split('\n')))


def startup_world(root: dict) -> dict:
    """Index only explicit Given seed records, never UI-created passengers or orders."""
    records = {category: [] for category in sorted(CATEGORIES)}
    seen = {category: set() for category in CATEGORIES}

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'Given' and isinstance(value, str):
                    for category, raw in SEED_ROW.findall(value):
                        if category not in CATEGORIES:
                            continue
                        try:
                            record = json.loads(raw)
                        except ValueError:
                            continue
                        identity = json.dumps(record, sort_keys=True, ensure_ascii=False)
                        if identity not in seen[category]:
                            seen[category].add(identity)
                            records[category].append(record)
                else:
                    visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(root)
    return {'seed_records': records,
            'interpretation': 'These are overlapping views of one published world, not '
                'duplicate accounts or duplicate services. Merge identical business identities; '
                'retain the union of routes/dates and specific_identity attributes. '
                'Scenario UI-created passengers, registrations and current orders must NOT '
                'be preseeded. Only the declared verified accounts, published catalogs and '
                'explicit historical completed order belong to startup.'}
