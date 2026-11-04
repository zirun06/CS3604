"""Bounded compiler for large web requirements using the shared application template."""

from contextlib import ExitStack
from importlib import import_module
import json
import os
from pathlib import Path
import re
from shutil import copyfile
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
from time import monotonic

import yaml

from infrastructure import prestashop_profile
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.tools import FileTools
from infrastructure.compact_acceptance import bundled_suite, prepare_workspace, repair_with_acceptance, run_suite
from infrastructure.shared.models.text import TextModel
from infrastructure.shared.models.vision import VisualModel
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import read_source, save_bytes, save_json, save_text
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.logging import console_log
from infrastructure.utils.processes import capture_process, npm_command


BACKEND = 'backend/src/api/register.ts'
FRONTEND = ('frontend/src/App.tsx', 'frontend/src/style.css')
TYPE_SCRIPT = Path(__file__).with_name('repair_implicit_any.mjs')
PARAMETER_DIAGNOSTIC = re.compile(
    r'^([^\r\n]+?)\((\d+),(\d+)\): error TS7006:', re.MULTILINE,
)
PARSE_INT_DIAGNOSTIC = re.compile(
    r"""^(?:backend[/\\])?src[/\\]api[/\\]register\.ts\((\d+),(\d+)\): error TS2345: Argument of type 'string \| string\[\]' is not assignable to parameter of type 'string'""",
    re.MULTILINE,
)
BUILD_REPAIR_PROMPT = """Fix the shown compiler/build diagnostics in the existing generated source.
Return {"tool_calls":[{"tool":"edit_file","path":"relative source path","operation":"replace",
"old_content":"exact unique fragment","new_content":"corrected fragment"}]}.
Edit only the generated files provided. Keep the application's routes, features and API
behavior. Use at most six small edits. Do not disable type checks or rewrite entire files."""
BACKEND_PROMPT = '''Implement the backend for the complete supplied web requirement. Return
{"files":{"backend/src/api/register.ts":"complete TypeScript source"}}.
The template calls registerApis(app: Express, connection: Database.Database) once during
app creation. Export that function, create SQLite schema with foreign keys and seed any
explicitly required startup data idempotently inside it, and register real JSON routes
under /api. Use only Express and better-sqlite3, with strict TypeScript. Honor all flows,
relationships, stable identities, access controls, session isolation, persistence,
cancellation and ordering described by the input. Use bound parameters. Provide enough
API operations for each scenario and document payload shapes in code. The extracted
account fixtures are initial state explicitly declared by the requirements. Initialize
each listed account with its specified attributes and credentials, without allowing
arbitrary unregistered accounts to log in. Prefer ordinary
HTTP cookies for sessions and use HttpOnly for auth credentials. Use node:crypto for
password hashing (scrypt) and cryptographically random session tokens. Session bootstrap
must reuse a valid cookie, including when product or other public routes initialize a
guest session. Compare order expirations and compute remaining time against the same
clock used when the expiration was created. Preserve valid public
flows if the requirement explicitly permits anonymous access. For screens with both public
content and private lists, allow anonymous access to the public data and restrict private
data to its owner. If a record has sensitive fields, mask them in lists and only return
them from the authorized detail endpoint when the specification requires them.
Keep the implementation
compact. The YAML is the product specification. Build real behavior for arbitrary valid
input values. Use scenario-specific literal data only when the spec requires initial data.'''

FRONTEND_PROMPT = '''Implement the complete web UI against the supplied backend source.
Return {"files":{"frontend/src/App.tsx":"complete React TSX source",
"frontend/src/style.css":"complete CSS source"}}. App.tsx must export App. Imports may
use React, React Router DOM v6, or local source files. Use same-origin /api calls with the exact paths and response
shapes in backend_source. Use real links and stable, reloadable routes for navigation.
Type API response arrays before chaining filter, map or sort. If a response is typed as
any, TypeScript cannot infer callback parameter types. Use explicit record interfaces.
Cover every specified behavior, including initial, error, cancel and reload states.
Use exact names and roles from the original scenarios. Render every role=button as a
native <button type="button"> (or type="submit" for form submission), even when its
action navigates to another screen. Use links for role=link. Use alternative roles
only where the requirement allows them. Render each global navigation entry exactly
once per screen, including the landing screen. Use exact business names for list
entries, without suffixes or status labels in their accessible names. Preserve
required wording and spelling even if the navigation link, page heading, and named
list region have different names. Name regions with aria-label or aria-labelledby.
Associate form labels with inputs and preserve exact placeholder prompts. For editor
textboxes specified by display text, use that exact text as label and placeholder.
Keep public lists visible to anonymous users if required. Render controls where the
workflow needs them. For editing saved records, wait for initial field values before
rendering editable inputs so the load response cannot overwrite user edits. After
successful mutations, use the saved response or reload the affected data. Check
each create/cancel destination separately and ensure each route target exists.
Store applied search and saved filter criteria in the destination URL where appropriate,
and use those criteria to fetch results and restore form controls on reload.
Carry parent IDs through nested creation using the same field names the API expects,
and show the new item's detail when the requirement calls for it. Ensure public
recent-content lists refresh after anonymous writes even if personal lists require
a session. Wait for session lookup before redirecting a protected route on reload.
Verify successful login reaches the required destination, and make
dropdowns open by keyboard and pointer. Keep every modal usable on short viewports
with a scrollable content area. Keep transient overlays from blocking unrelated
navigation. For a calendar button whose name is a date, expose any fare or status
separately from that button's accessible name. Follow
reference evidence for layout and the YAML for behavior. Share React components and CSS
classes across similar screens. Keep the response within its output budget and finish
both files and the closing JSON object.'''

STARTUP_CHECK = '''
import { createApp } from './backend/dist/app.js';
import { createDatabaseClient } from './backend/dist/db/client.js';
import { initializeDatabase } from './backend/dist/db/initialize.js';
const db = createDatabaseClient(':memory:');
try {
  initializeDatabase(db);
  const server = createApp(db).listen(0, '127.0.0.1');
  try {
    await new Promise((resolve, reject) => server.once('listening', resolve).once('error', reject));
    const base = `http://127.0.0.1:${server.address().port}`;
    const health = await fetch(base + '/api/health', { signal: AbortSignal.timeout(4000) });
    if (!health.ok) throw new Error(`Health endpoint returned ${health.status}`);
    if (process.env.ARC_CHECK_FRONTEND === '1') {
      const page = await fetch(base, { signal: AbortSignal.timeout(4000) });
      if (!page.ok || !(await page.text()).includes('id="root"')) throw new Error('Frontend did not load');
    }
  } finally {
    server.closeAllConnections();
    server.close();
  }
} finally {
  db.close();
}
'''


def load_requirements(input_dir: Path):
    source = read_source(input_dir / 'requirements.yaml')
    return source, RequirementTree(yaml.safe_load(source))


def account_fixtures(source: str) -> list[dict]:
    """Index explicitly declared login fixtures so they are not missed in large YAML inputs."""
    accounts = {}

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            identity = node.get('email') or node.get('username') or node.get('mobile') or node.get('phone')
            if isinstance(identity, str) and identity and isinstance(node.get('password'), str):
                # Preserve differing fixture attributes instead of merging conflicting rows.
                accounts[json.dumps(node, sort_keys=True, ensure_ascii=False)] = node
            for child in node.values():
                visit(child)

    for raw in re.findall(r'^\s*- [^\n:]+: (\{[^\n]+\})[ \t]*$', source, re.MULTILINE):
        try:
            visit(json.loads(raw))
        except ValueError:
            continue
    return list(accounts.values())


def repair_implicit_parameters(output_dir: Path, diagnostics: str) -> bool:
    """Use TypeScript source positions to recover generated TS7006 parameters."""
    generated = (BACKEND, FRONTEND[0])
    positions = {}
    for reported, line, column in PARAMETER_DIAGNOSTIC.findall(diagnostics):
        reported = reported.strip().replace('\\', '/')
        matches = [path for path in generated if reported == path.split('/', 1)[1]
            or reported == path or reported.endswith('/' + path)]
        if len(matches) == 1:
            positions.setdefault(matches[0], []).append((int(line), int(column)))
    if not positions:
        return False
    fix = capture_process(
        ['node', str(TYPE_SCRIPT.resolve()), str(output_dir.resolve()), json.dumps(positions)],
        cwd=output_dir, timeout=15,
    )
    if fix['returncode'] != 0:
        print('[compact] Could not apply the local TypeScript repair.', flush=True)
        return False
    count = int(fix['stdout'].strip() or '0')
    if count:
        print(f'[compact] Added explicit types to {count} generated parameters; rebuilding.', flush=True)
    return count > 0


def repair_storefront_route_params(output_dir: Path, diagnostics: str) -> bool:
    """Make parseInt's existing string coercion explicit for reported Express 5 parameters."""
    positions = set(PARSE_INT_DIAGNOSTIC.findall(diagnostics))
    if not positions:
        return False
    path = output_dir / BACKEND
    lines = read_source(path).splitlines(keepends=True)
    changed = 0
    for line, column in sorted(positions, key=lambda pos: (int(pos[0]), int(pos[1])), reverse=True):
        index, start = int(line) - 1, int(column) - 1
        if not 0 <= index < len(lines):
            continue
        content = lines[index]
        if not re.search(r'\bparseInt\(\s*$', content[:start]):
            continue
        arg = re.match(r'req\.params\.\w+(?=\s*[,\)])', content[start:])
        if arg is None:
            continue
        end = start + arg.end()
        lines[index] = content[:start] + f'String({arg.group()})' + content[end:]
        changed += 1
    if changed:
        save_text(path, ''.join(lines))
        print(f'[compact] Normalized {changed} Express route parameters passed to parseInt; rebuilding.', flush=True)
    return bool(changed)


def compile_compact(input_dir: Path, output_dir: Path, source: str, *, port: int, model_log: bool,
                    bookstack_legacy: bool = False):
    """Generate bounded file groups, repair build errors, and leave a stage report."""
    suite = bundled_suite(source)
    storefront = suite is not None and suite.name == prestashop_profile.SUITE
    report_path = output_dir / '.arc/compilation.json'
    profile = 'bookstack-full-track' if bookstack_legacy else 'prestashop' if storefront else 'compact'
    report = {'profile': profile,
        'status': 'RUNNING', 'stages': {}}
    console = DemoConsole()
    workspace = None

    def run(stage, action):
        record = report['stages'][stage] = {'status': 'RUNNING'}
        save_json(report_path, report)
        print(f'[compact] {stage}', flush=True)
        started = monotonic()
        try:
            with console_log(output_dir, stage=stage, model_log=model_log, debug_model_io=model_log):
                result = action()
        except BaseException as error:
            record.update(status='FAILED', error=str(error), elapsed_seconds=round(monotonic() - started, 2))
            report['status'] = 'FAILED'
            save_json(report_path, report)
            raise
        record.update(status='GREEN', elapsed_seconds=round(monotonic() - started, 2))
        save_json(report_path, report)
        return result

    def check_build(*args):
        result = capture_process([*npm_command(), 'run', 'build', *args], cwd=output_dir, timeout=90)
        if result['returncode'] and not bookstack_legacy:
            repaired = repair_implicit_parameters(output_dir, result['output'])
            if storefront:
                repaired = repair_storefront_route_params(output_dir, result['output']) or repaired
            if repaired:
                result = capture_process([*npm_command(), 'run', 'build', *args], cwd=output_dir, timeout=90)
        if result['returncode']:
            raise ValueError(result['output'][-6000:])
        startup = capture_process(['node', '--input-type=module', '-e', STARTUP_CHECK],
            cwd=output_dir, timeout=15, env={'ARC_CHECK_FRONTEND': '0' if args else '1'})
        if startup['returncode']:
            raise ValueError(startup['output'][-6000:])

    def check_frontend():
        check_build()
        if workspace is not None:
            browser = run_suite(workspace, output_dir, storefront_probe=True)
            if browser['failed'] or browser['passed'] != 1:
                failure = next(iter(browser['failures'].values()), {})
                raise ValueError('Storefront failed to render in Chromium. ' +
                    failure.get('error', '') + '\n' + failure.get('page_snapshot', ''))

    def generate(instructions, payload, paths, build, *, attempts=3, repair_backend=False):
        def accept(result):
            files = result['files']
            if not isinstance(files, dict) or set(files) != set(paths):
                raise ValueError(f'Return exactly these file paths: {list(paths)}')
            if any(not isinstance(value, str) or not value.strip() for value in files.values()):
                raise ValueError('Each file must have nonempty source text')
            for path, content in files.items():
                save_text(output_dir / path, content)
            try:
                build()
            except ValueError as build_error:
                if bookstack_legacy:
                    raise
                # Repair a valid generated candidate before spending a full proposal.
                editor = FileTools(output_dir, writable=(*paths, BACKEND) if repair_backend else paths)
                backend_before_repair = (output_dir / BACKEND).read_bytes() if repair_backend else None
                original_limit, original_reasoning, original_client = (
                    model.max_output_tokens, model.reasoning, model.client)
                model.max_output_tokens = min(original_limit, 6000)
                model.reasoning = 'none'
                model.client = original_client.with_options(timeout=65, max_retries=0)
                try:
                    repair_prompt = BUILD_REPAIR_PROMPT
                    if repair_backend:
                        repair_prompt += (' Inspect both the frontend consumer and the backend JSON response. '
                            'When the server returns incomplete objects, fix the response at the source. '
                            'Keep required fields and use real values rather than placeholder defaults.')
                    repair = model.generate_json(repair_prompt, {
                        'diagnostics': str(build_error), 'files': editor.state()})
                    edits = repair['tool_calls']
                    if not 1 <= len(edits) <= 6 or editor.effect(edits) != 'write':
                        raise ValueError('Expected one to six source edits')
                    editor.execute(edits)
                    build()
                except (ValueError, KeyError, TypeError, RuntimeError, OSError) as error:
                    if backend_before_repair is not None:
                        save_bytes(output_dir / BACKEND, backend_before_repair)
                    raise ValueError(f'{build_error}\nLocal build repair failed: {error}') from error
                finally:
                    model.max_output_tokens, model.reasoning, model.client = (
                        original_limit, original_reasoning, original_client)
            return files

        propose_json(model, instructions, payload, accept, console, 'Generate and build', max_attempts=attempts)

    def style_frontend(references):
        # Keep a buildable template stylesheet if the optional visual pass fails.
        stylesheet = output_dir / FRONTEND[1]
        original = stylesheet.read_bytes()
        model.max_output_tokens = min(configured_output_limit, 10000 if storefront else 6000)
        try:
            generate(
                'Style the supplied React application using the visual references. '
                'Return {"files":{"frontend/src/style.css":"complete CSS"}}. '
                'Use existing classes and retain usable layouts, forms and dialogs.',
                {'app_source': read_source(output_dir / FRONTEND[0]), 'references': references},
                (FRONTEND[1],), check_frontend, attempts=1)
        except (RuntimeError, OSError, ValueError) as error:
            save_bytes(stylesheet, original)
            print(f'[compact] Kept template styling after visual pass failed: {type(error).__name__}', flush=True)
            check_frontend()

    def visual_evidence():
        references = import_module('01_explore_requirement').collect_images(yaml.safe_load(source))
        if not references:
            return {}
        vision = VisualModel()
        vision.reasoning = os.getenv('VISUAL_REASONING', os.getenv('MODEL_REASONING', 'none')).lower()
        vision.client = vision.client.with_options(timeout=25, max_retries=0)
        evidence = {}
        # Sample across the document so early navigation doesn't use every image slot.
        count = min(4, len(references))
        indexes = [i * (len(references) - 1) // max(1, count - 1) for i in range(count)]
        try:
            for index in indexes:
                relative = references[index]
                path = (input_dir / relative).resolve()
                if not path.is_relative_to(input_dir.resolve()):
                    raise ValueError(f'Reference must be inside the input directory: {relative}')
                try:
                    evidence[relative] = vision.analyze(path, max_attempts=1)
                except (OSError, ValueError, RuntimeError) as error:
                    print(f'[compact] Reference unavailable: {relative} ({type(error).__name__})', flush=True)
        finally:
            vision.client.close()
        save_json(output_dir / '.arc/visual_analysis.json', evidence)
        return evidence

    run('initialize', lambda: initialize_project(output_dir, port=port))
    model = run('model configuration', TextModel)
    model.reasoning = os.getenv('MODEL_REASONING', 'none').lower()
    large = len(source) > 100_000
    configured_output_limit = model.max_output_tokens
    model.max_output_tokens = min(configured_output_limit, 26000 if large else 16000)
    model.client = model.client.with_options(timeout=360 if large else 180, max_retries=0)
    backend_prompt, frontend_prompt = BACKEND_PROMPT, FRONTEND_PROMPT
    if bookstack_legacy:
        from infrastructure import bookstack_profile
        backend_prompt, frontend_prompt = bookstack_profile.BACKEND_PROMPT, bookstack_profile.FRONTEND_PROMPT
    elif storefront:
        backend_prompt += prestashop_profile.BACKEND_GUIDANCE
        frontend_prompt += prestashop_profile.FRONTEND_GUIDANCE
        print('[compiler] PrestaShop: using the storefront generation profile.', flush=True)
    def generate_frontend(frontend_request):
        if storefront:
            # The original release generated the paired view and CSS from one proposal.
            # If the gateway truncates that pair, use the recovered split pipeline.
            stylesheet = output_dir / FRONTEND[1]
            baseline_css = stylesheet.read_bytes()
            try:
                generate(frontend_prompt, frontend_request, FRONTEND, check_frontend, attempts=2, repair_backend=True)
            except RuntimeError as error:
                if not any(reason in str(error) for reason in ('finish_reason=length', 'failed to render in Chromium')):
                    raise
                save_bytes(stylesheet, baseline_css)
                print('[compact] Retrying the storefront with separate TSX and CSS generation.', flush=True)
            else:
                return False
        elif not large or bookstack_legacy:
            generate(frontend_prompt, frontend_request, FRONTEND, check_build)
            return False
        model.max_output_tokens = min(configured_output_limit, 32000)
        functional_prompt = frontend_prompt.replace(
            '"frontend/src/App.tsx":"complete React TSX source",\n'
            '"frontend/src/style.css":"complete CSS source"',
            '"frontend/src/App.tsx":"complete React TSX source"').replace(
            'both files and the closing JSON object', 'the TSX file and the closing JSON object')
        functional_prompt = functional_prompt.replace(
            'Generate TSX and CSS together, using shared layout, card and modal styles.',
            'Use shared class names for layouts, cards and modals.')
        functional_prompt += '\nUse meaningful CSS class names. A separate pass supplies the stylesheet.'
        generate(functional_prompt, frontend_request, (FRONTEND[0],), check_frontend, repair_backend=storefront)
        return True

    def recover_storefront(failures, previous_repair):
        client, budget = model.client, model.max_output_tokens
        model.client = client.with_options(timeout=240, max_retries=0)
        model.max_output_tokens = min(configured_output_limit, 30000)
        try:
            generate(frontend_prompt + '\nThe previous UI passed the build but no public scenario passed. '
                'Use the diagnostics to redesign the common UI and routing around the existing API.',
                {**frontend_request, 'backend_source': read_source(output_dir / BACKEND),
                    'failed_scenarios': failures[:5], 'previous_repair': previous_repair},
                FRONTEND, check_frontend, attempts=1, repair_backend=True)
        finally:
            model.client, model.max_output_tokens = client, budget

    resources = ExitStack()
    try:
        run('install dependencies', lambda: install_dependencies(output_dir, timeout=90))
        run('backend', lambda: generate(backend_prompt, {'requirements_yaml': source,
            'declared_account_fixtures': account_fixtures(source)}, (BACKEND,),
            lambda: check_build('-w', '@arc/backend')))
        references = run('sample reference images', visual_evidence)
        if storefront:
            temporary = Path(resources.enter_context(TemporaryDirectory(prefix='arc-storefront-')))
            try:
                prepare_workspace(suite, temporary)
                copyfile(Path(__file__).with_name('storefront_probe.spec.ts'), temporary / 'storefront-probe.spec.ts')
                workspace = temporary
            except (RuntimeError, OSError, TimeoutExpired) as error:
                print(f'[compact] Storefront browser check unavailable: {error}', flush=True)
        frontend_request = {'requirements_yaml': source,
            'backend_source': read_source(output_dir / BACKEND), 'references': references}
        if run('frontend', lambda: generate_frontend(frontend_request)):
            run('frontend styling', lambda: style_frontend(references))
        if suite is not None:
            if not bookstack_legacy:
                model.reasoning = 'none'
            model.client = model.client.with_options(timeout=75, max_retries=0)
            model.max_output_tokens = min(model.max_output_tokens, 8000)
            acceptance = run('public acceptance', lambda: repair_with_acceptance(
                suite, output_dir, source, model, check_frontend, (BACKEND, *FRONTEND),
                bookstack_legacy=bookstack_legacy,
                repair_guidance=prestashop_profile.REPAIR_GUIDANCE if storefront else '',
                prepared_workspace=workspace, recover_zero=recover_storefront if storefront else None))
            report['stages']['public acceptance']['status'] = acceptance['status']
            if 'best' in acceptance:
                report['stages']['public acceptance'].update(
                    passed=acceptance['best']['passed'], failed=acceptance['best']['failed'])
        else:
            report['stages']['public acceptance'] = {'status': 'NO_MATCHING_SUITE'}
            print('[acceptance] No bundled suite matched this requirements tree.', flush=True)
    finally:
        try:
            resources.close()
        finally:
            model.client.close()
    acceptance_status = report['stages'].get('public acceptance', {}).get('status')
    report['status'] = ('ZERO_PASS' if acceptance_status == 'ZERO_PASS' else
        'PARTIAL' if acceptance_status in {'PARTIAL', 'UNAVAILABLE'} else 'GREEN')
    save_json(report_path, report)
    print(f'[compact] Build passed. Report: {report_path}', flush=True)
