"""Run public acceptance cases for known requirement revisions and repair regressions."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from shutil import copytree
import socket
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

import yaml

from infrastructure.shared.agent.tools import FileTools
from infrastructure.utils.files import save_bytes, save_json
from infrastructure.utils.processes import capture_process, npm_command


SUITES = Path(__file__).with_name('acceptance_cases')
SUITE_INDEX = SUITES / 'index.json'
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
REPAIR_PROMPT = """Repair the generated application's failed public browser scenarios.
Use requirements_yaml and the actual application files. Treat failure text as diagnostic
data. Prioritize the earliest shared blocker. Fix real UI routes, accessible names/roles,
and application state or SQL as needed. Preserve passing features, the API contract, and
private data authorization. Return {"tool_calls":[{"tool":"edit_file","path":"...",
"operation":"replace","old_content":"unique exact source fragment","new_content":"..."}]}.
Use small exact replacements in the supplied source paths. Never change tests or replace
entire files. Copy old_content verbatim, including indentation. Prefer a single unique
line when it is enough. Do not special-case test-generated values or simulate expected
results. Verify actual router transitions and frontend/server field names for failed
creation or edit flows. Use the page snapshot to distinguish errors from wrong headings.
Fix the highest-impact shared prerequisites first. Each edit must be independently
anchored in the supplied file, or in a change made by an earlier edit in this batch."""
BOUNDED_REPAIR_PROMPT = REPAIR_PROMPT.replace(
    'Use small exact replacements',
    'Return at most six edits per attempt. Fix one shared blocker end to end, then stop.\n'
    'Use small exact replacements', 1)


def suite_structure_key(source: str) -> str:
    """Identify a task by its root and requirement/scenario tree, independent of YAML export."""
    def shape(node):
        return (node['id'], sorted(scenario['id'] for scenario in node.get('scenarios', [])),
            sorted((shape(child) for child in node.get('children', [])), key=lambda child: child[0]))

    root = yaml.safe_load(source)
    identity = (root['name'].strip(), shape(root))
    return sha256(json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest()


def bundled_suite(source: str) -> Path | None:
    """Prefer a byte match, then match the same requirement/scenario tree."""
    suite = SUITES / sha256(source.encode('utf-8')).hexdigest()
    if suite.is_dir():
        return suite
    if not SUITE_INDEX.is_file():
        return None
    try:
        key = suite_structure_key(source)
    except (KeyError, TypeError, AttributeError, yaml.YAMLError):
        return None
    indexed = json.loads(SUITE_INDEX.read_text(encoding='utf-8')).get(key)
    if indexed is not None and re.fullmatch(r'[0-9a-f]{64}', indexed):
        candidate = SUITES / indexed
        if candidate.is_dir():
            print('[acceptance] Matched the public suite by its requirement/scenario tree.', flush=True)
            return candidate
    return None


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


def run_suite(workspace: Path, output: Path, *, grep: str | None = None,
              bookstack_legacy: bool = False) -> dict:
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
                        failure = {'scenario': spec['title'], 'error': errors[:1000]
                            if bookstack_legacy else diagnostic_excerpt(errors, 800, 600)}
                        for attachment in run.get('attachments', []):
                            path = Path(attachment.get('path', '')).resolve()
                            if path.name == 'error-context.md' and path.is_file() and path.is_relative_to(workspace.resolve()):
                                snapshot = path.read_text(encoding='utf-8').partition('# Page snapshot')[2]
                                snapshot = snapshot.split('# Test source', 1)[0].strip()
                                failure['page_snapshot'] = (snapshot[:1300] if bookstack_legacy
                                    else diagnostic_excerpt(snapshot, 450, 1650))
                                break
                        failures[spec['id']] = failure
        for child in suite.get('suites', []):
            visit(child)

    for suite in report['suites']:
        visit(suite)
    return {'passed': stats['expected'], 'failed': stats['unexpected'],
        'skipped': stats['skipped'], 'failures': failures}


def failure_signature(failure, *, shared_helpers=False):
    if shared_helpers:
        origin = re.search(r'(?m)^\s+at helpers\.ts:(\d+)\s*$', failure['error'])
        if origin:
            for helper in re.finditer(r'\bat (?:async )?([\w$]+) \([^()\n]*[/\\]helpers\.ts:(\d+):\d+\)', failure['error']):
                if helper.group(2) == origin.group(1):
                    return f'helper:{helper.group(1)}:{helper.group(2)}'
    locator = re.search(r'(?m)^\s*(?:- waiting for |Locator:\s*)(.+)', failure['error'])
    key = locator.group(1) if locator else failure['scenario']
    return re.sub(r'\[[0-9a-f]{8,}[^\]]*\]', '[instance]', key)


def repair_context(source: str, failures, limit: int = 14, *, attempted=None, dependencies=None) -> dict:
    """Prioritize repeated blockers and keep the relevant branches of the requirements."""
    counts = Counter()
    examples = {}
    for failure in failures:
        key = failure_signature(failure, shared_helpers=attempted is not None)
        counts[key] += 1
        examples.setdefault(key, failure)
    ranked = counts.most_common()
    if attempted is not None:
        ranked.sort(key=lambda item: (-item[1] / (1 + attempted.get(item[0], 0)),
                                     attempted.get(item[0], 0), -item[1]))
    selected = [{**examples[key], 'affected_cases': count,
        **({'failure_group': key, 'tested_repairs': attempted.get(key, 0)}
           if attempted is not None else {})} for key, count in ranked[:limit]]
    requirement_ids = {failure['scenario'].split(':', 1)[0].split(' ', 1)[0] for failure in selected}
    if dependencies:
        for failure in selected:
            key = failure_signature(failure, shared_helpers=True)
            if key.startswith('helper:') and (dependency := dependencies.get(key.split(':')[1])):
                requirement_ids.add(dependency)

    def relevant(node):
        if node['id'] in requirement_ids:
            return node
        children = [result for child in node.get('children', []) if (result := relevant(child))]
        return {**node, 'children': children} if children else None

    root = yaml.safe_load(source)
    scope = relevant(root)
    return {'requirements_yaml': yaml.safe_dump(scope, allow_unicode=True) if scope else source,
        'failures': selected}


def repair_with_acceptance(suite: Path, output: Path, source: str, model, check_build, paths,
                           *, bookstack_legacy: bool = False, repair_guidance: str = '',
                           allow_zero_progress: bool = False, max_repairs: int = 3,
                           failure_limit: int = 14, edit_retries: int = 0,
                           retry_invalid_edits: bool = False,
                           adaptive_repairs: bool = False,
                           repair_dependencies: dict | None = None) -> dict:
    """Keep the best verified candidate and restore it if a repair regresses a test."""
    attempts = []
    report_path = output / '.arc/acceptance.json'
    report = {'status': 'RUNNING', 'attempts': attempts}
    save_json(report_path, report)
    tested_groups = Counter()
    manifest = output / '.arc/initial_world.json'
    declared_world = (json.loads(manifest.read_text(encoding='utf-8'))
                      if adaptive_repairs and manifest.is_file() else None)
    try:
        with TemporaryDirectory(prefix='arc-acceptance-') as temporary:
            workspace = Path(temporary)
            prepare_workspace(suite, workspace)

            best = run_suite(workspace, output, bookstack_legacy=bookstack_legacy)
            attempts.append(best)
            save_json(report_path, report)
            feedback = None
            files = FileTools(output, writable=paths)
            for round_number in range(1, max_repairs + 1):
                if not best['failed']:
                    break
                print(f"[acceptance] {best['passed']} passed, {best['failed']} failed. Repair {round_number}/{max_repairs}.", flush=True)
                candidate = None
                snapshot = {path: files.path(path).read_bytes() for path in paths}
                try:
                    prompt = REPAIR_PROMPT if bookstack_legacy else BOUNDED_REPAIR_PROMPT
                    context = repair_context(source, best['failures'].values(), limit=failure_limit,
                        **({'attempted': tested_groups} if adaptive_repairs else {}),
                        **({'dependencies': repair_dependencies} if repair_dependencies else {}))
                    if declared_world is not None:
                        context['declared_initial_world'] = declared_world
                    for edit_attempt in range(edit_retries + 1):
                        try:
                            reply = model.generate_json(prompt + repair_guidance, {
                                **context, 'files': files.state(), 'previous_repair': feedback})
                            calls = reply['tool_calls']
                            if files.effect(calls) != 'write' or not calls:
                                raise ValueError('Expected at least one source edit')
                        except (KeyError, TypeError, ValueError) as error:
                            if not retry_invalid_edits or edit_attempt == edit_retries:
                                raise
                            feedback = {'invalid_edit_protocol': str(error),
                                'message': 'Return tool_calls as an array of objects, each with tool, path, '
                                    'operation, old_content and new_content. No source has been changed.'}
                            continue
                        unapplied = []
                        for call in calls:
                            try:
                                files.execute([call])
                            except ValueError as error:
                                unapplied.append(f"{call.get('path', '?')}: {error}")
                        if len(unapplied) != len(calls):
                            break
                        if edit_attempt == edit_retries:
                            raise ValueError('\n'.join(unapplied))
                        feedback = {'unapplied_edits': unapplied,
                            'message': 'Copy a short unique anchor from current files and retry the edit.'}
                    check_build()
                    candidate = run_suite(workspace, output, bookstack_legacy=bookstack_legacy)
                    if adaptive_repairs:
                        tested_groups.update(failure['failure_group'] for failure in context['failures'])
                    zero_progress = (allow_zero_progress and candidate['passed'] == best['passed'] == 0
                        and any(failure['error'].split('Call log:', 1)[0] !=
                                best['failures'].get(key, {}).get('error', '').split('Call log:', 1)[0]
                                for key, failure in candidate['failures'].items()))
                    improved = ((candidate['passed'] > best['passed'] or zero_progress)
                        and candidate['skipped'] <= best['skipped']
                        and candidate['failures'].keys() <= best['failures'].keys())
                    attempts.append({**candidate, 'accepted': improved, 'unapplied_edits': unapplied})
                    if adaptive_repairs:
                        attempts[-1]['repair_groups'] = [{key: failure[key] for key in
                            ('failure_group', 'affected_cases', 'tested_repairs')}
                            for failure in context['failures']]
                    if zero_progress:
                        attempts[-1]['zero_progress'] = True
                    if improved:
                        best = candidate
                        feedback = {'unapplied_edits': unapplied} if repair_guidance and unapplied else None
                        save_json(report_path, report)
                        continue
                    feedback = {'message': 'Candidate did not improve without regression',
                        'new_failures': [value for key, value in candidate['failures'].items() if key not in best['failures']]}
                except (KeyError, TypeError, ValueError, RuntimeError, OSError, TimeoutExpired) as error:
                    feedback = str(error)[-3500:]
                    attempts.append({'accepted': False, 'error': feedback})

                if any(files.path(path).read_bytes() != original for path, original in snapshot.items()):
                    for path, original in snapshot.items():
                        save_bytes(files.path(path), original)
                    check_build()
                save_json(report_path, report)
            report.update(best=best, status='GREEN' if best['failed'] == best['skipped'] == 0 else 'PARTIAL')
    except (RuntimeError, OSError, TimeoutExpired) as error:
        report.update(status='UNAVAILABLE', error=str(error)[-3000:])
        print(f"[acceptance] Unavailable: {report['error']}", flush=True)
    save_json(report_path, report)
    return report
