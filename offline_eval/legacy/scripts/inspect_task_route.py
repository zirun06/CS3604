"""Read-only diagnosis of the current auto task router; no model calls."""
import argparse
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'compiler'))
from infrastructure.compact import load_requirements
from infrastructure.compact_acceptance import bundled_suite, suite_structure_key
from infrastructure.tasks.registry import PROFILES, select_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('requirements', type=Path)
    parser.add_argument('--expected-task', choices=[p.key for p in PROFILES])
    args = parser.parse_args()
    directory = args.requirements.resolve()
    source, _ = load_requirements(directory)
    messages = io.StringIO()
    with redirect_stdout(messages):
        suite = bundled_suite(source)
    task = select_profile(suite)
    try:
        structure = suite_structure_key(source)
    except (KeyError, TypeError, AttributeError):
        structure = None
    result = {
        'requirements': str(directory), 'source_sha256': sha256(source.encode()).hexdigest(),
        'structure_sha256': structure, 'suite': suite.name if suite else None,
        'selected_task': task.key, 'frontend_mode': task.frontend_mode,
        'acceptance_repairs': task.acceptance_attempts,
        'stackoverflow_backend_checks': task.probe_backend_contract,
        'ctrip_steps_enabled': task.ctrip_contract,
        'expected_task': args.expected_task,
        'expected_task_matches': args.expected_task is None or task.key == args.expected_task,
        'warning': 'Unknown identity silently selects generic in the current production router.' if task.key == 'generic' else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['expected_task_matches'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
