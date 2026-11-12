"""Score an already built app against an explicitly selected public Playwright suite."""

import argparse
import json
from pathlib import Path
import re
from shutil import copytree
import socket
from tempfile import TemporaryDirectory

from infrastructure.utils.files import save_json
from infrastructure.utils.processes import capture_process, npm_command


CONFIG = """
import { defineConfig } from '@playwright/test';
const baseURL = 'http://127.0.0.1:' + process.env.ARC_TEST_PORT;
export default defineConfig({
  testDir: '.', testMatch: '*.spec.ts', timeout: 6500, workers: Number(process.env.ARC_TEST_WORKERS), retries: 0,
  expect: { timeout: 2500 },
  reporter: 'json', use: { baseURL, actionTimeout: 2500 },
  webServer: {
    command: 'node dist/server.js', cwd: process.env.ARC_TEST_BACKEND,
    url: baseURL + '/api/health', timeout: 15000,
    env: { PORT: process.env.ARC_TEST_PORT, DATABASE_URL: ':memory:' },
  },
});
"""
def prepare_workspace(suite: Path, workspace: Path) -> None:
    copytree(suite, workspace, dirs_exist_ok=True)
    (workspace / 'playwright.config.mjs').write_text(CONFIG, encoding='utf-8')
    install = capture_process([*npm_command(), 'install', '--no-audit', '--no-fund',
        '--ignore-scripts', '@playwright/test@1.57.0'], cwd=workspace, timeout=45)
    if install['returncode']:
        raise RuntimeError(install['output'][-2000:])
    probe = capture_process(['node', '-e',
        "require('playwright').chromium.launch({timeout: 8000}).then(b=>b.close()).catch(e=>{console.error(e.message);process.exit(1)})"],
        cwd=workspace, timeout=12)
    if probe['returncode']:
        if "Executable doesn't exist" not in probe['output']:
            raise RuntimeError(probe['output'][-2000:])
        print('[acceptance] Installing the browser required by the bundled Playwright version.', flush=True)
        browser = capture_process(
            ['node', 'node_modules/@playwright/test/cli.js', 'install', 'chromium', '--only-shell'],
            cwd=workspace, timeout=90)
        if browser['returncode']:
            raise RuntimeError(browser['output'][-2000:])


def diagnostic_excerpt(value: str, head: int, tail: int) -> str:
    """Retain both the locator and the failing assertion when output is long."""
    if len(value) <= head + tail:
        return value
    return value[:head] + '\n[…]\n' + value[-tail:]


def run_suite(workspace: Path, output: Path, *, grep: str | None = None) -> dict:
    with socket.socket() as port:
        port.bind(('127.0.0.1', 0))
        number = port.getsockname()[1]
    spec_count = sum(1 for _ in workspace.rglob('*.spec.ts'))
    workers = 2 if spec_count > 35 else 1
    command = ['node', 'node_modules/@playwright/test/cli.js', 'test']
    if grep is not None:
        command.extend(['--grep', grep])
    result = capture_process(command,
        cwd=workspace, timeout=max(210, 30 + 15 * spec_count // workers),
        env={'ARC_TEST_PORT': str(number), 'ARC_TEST_BACKEND': str(output / 'backend'),
            'ARC_TEST_WORKERS': str(workers)})
    try:
        report = json.loads(result['stdout'])
    except ValueError as error:
        raise RuntimeError(result['output'][-3000:]) from error
    stats = report['stats']
    if report.get('errors') or not (stats['expected'] or stats['unexpected']):
        raise RuntimeError('Playwright could not evaluate the application: ' + result['output'][-3000:])

    failures = {}

    def visit(suite):
        for spec in suite.get('specs', []):
            for test in spec['tests']:
                for run in test['results']:
                    if run['status'] not in {'passed', 'skipped'}:
                        errors = '\n'.join(error.get('message', '') for error in run.get('errors', []))
                        if 'Executable doesn\'t exist' in errors or 'browserType.launch:' in errors:
                            raise RuntimeError(errors[:1400])
                        errors = re.sub(r'\x1b\[[0-9;]*m', '', errors)
                        failure = {'scenario': spec['title'], 'error': diagnostic_excerpt(errors, 800, 600)}
                        for attachment in run.get('attachments', []):
                            path = Path(attachment.get('path', '')).resolve()
                            if path.name == 'error-context.md' and path.is_file() and path.is_relative_to(workspace.resolve()):
                                snapshot = path.read_text(encoding='utf-8').partition('# Page snapshot')[2]
                                snapshot = snapshot.split('# Test source', 1)[0].strip()
                                failure['page_snapshot'] = diagnostic_excerpt(snapshot, 450, 1650)
                                break
                        failures[spec['id']] = failure
        for child in suite.get('suites', []):
            visit(child)

    for suite in report['suites']:
        visit(suite)
    return {'passed': stats['expected'], 'failed': stats['unexpected'],
        'skipped': stats['skipped'], 'failures': failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite', type=Path, help='Explicit directory of public Playwright specs')
    parser.add_argument('application', type=Path, help='Directory of an application after npm run build')
    parser.add_argument('--report', type=Path, help='Where to save the detailed public test report')
    parser.add_argument('--grep', help='Run only scenarios matching this Playwright title pattern in a fresh database')
    args = parser.parse_args()
    app = args.application.resolve()
    if not (app / 'backend/dist/server.js').is_file():
        parser.error('Build the application with npm run build before verification.')
    suite = args.suite.resolve()
    if not suite.is_dir() or not any(suite.glob('*.spec.ts')):
        parser.error('Supply a suite directory containing Playwright .spec.ts files.')

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
