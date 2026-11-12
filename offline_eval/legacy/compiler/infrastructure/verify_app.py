"""Evaluate an already built application without a model or modifying its files."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from infrastructure.compact_acceptance import bundled_suite, prepare_workspace, run_suite
from infrastructure.utils.files import read_source, save_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('requirements', type=Path, help='Directory containing requirements.yaml')
    parser.add_argument('application', type=Path, help='Directory of an application after npm run build')
    parser.add_argument('--report', type=Path, help='Where to save the detailed public test report')
    parser.add_argument('--grep', help='Run only scenarios matching this Playwright title pattern in a fresh database')
    args = parser.parse_args()
    app = args.application.resolve()
    if not (app / 'backend/dist/server.js').is_file():
        parser.error('Build the application with npm run build before verification.')
    suite = bundled_suite(read_source(args.requirements / 'requirements.yaml'))
    if suite is None:
        parser.error('No public cases are bundled for this requirements revision.')

    with TemporaryDirectory(prefix='arc-verify-') as tmp:
        workspace = Path(tmp)
        prepare_workspace(suite, workspace)
        result = run_suite(workspace, app, grep=args.grep)
    if args.report:
        save_json(args.report, result)
    print(f"{result['passed']} passed, {result['failed']} failed, {result['skipped']} skipped")
    return int(bool(result['failed'] or result['skipped']))


if __name__ == '__main__':
    raise SystemExit(main())
