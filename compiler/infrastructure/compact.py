"""Bounded compiler for large web requirements using the shared application template."""

from importlib import import_module
import json
import os
from pathlib import Path
import re
from time import monotonic

import yaml

from infrastructure.tasks import bookstack
from infrastructure.tasks.profile import DEFAULT, TaskProfile
from infrastructure.tasks.prompts import BACKEND_PROMPT, FRONTEND_PROMPT
from infrastructure.tasks.registry import select_profile
from infrastructure.tasks.initial_world import initial_world
from infrastructure.tasks.railway_navigation import ensure_navigation as ensure_railway_navigation
from infrastructure.tasks.ctrip_navigation import ensure_navigation as ensure_ctrip_navigation
from infrastructure.tasks.ctrip_services import ensure_services as ensure_ctrip_services
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.agent.tools import FileTools
from infrastructure.compact_acceptance import bundled_suite, repair_with_acceptance
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
                    bookstack_legacy: bool = False, task_profile: TaskProfile | None = None):
    """Generate bounded file groups, repair build errors, and leave a stage report."""
    suite = bundled_suite(source)
    config = task_profile or select_profile(suite)
    if bookstack_legacy:
        config = bookstack.PROFILE
    elif task_profile is None and config.legacy_acceptance:
        # Direct compact callers historically opt into the BookStack workflow.
        config = DEFAULT
    bookstack_legacy = config.legacy_acceptance
    report_path = output_dir / '.arc/compilation.json'
    report = {'profile': config.report_profile, 'task': config.key,
        'status': 'RUNNING', 'stages': {}}
    console = DemoConsole()

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
        if config.ctrip_contract:
            prepared = capture_process(['node', str(Path(__file__).parent / 'tasks' /
                'prepare_ctrip_source.mjs'), str(output_dir), 'backend' if args else 'frontend'],
                cwd=output_dir, timeout=15)
            if prepared['returncode']:
                raise ValueError(prepared['output'][-4000:])
        if config.railway_contract:
            prepared = capture_process(['node', str(Path(__file__).parent / 'tasks' /
                'prepare_railway_source.mjs'), str(output_dir), 'backend' if args else 'frontend'],
                cwd=output_dir, timeout=15)
            if prepared['returncode']:
                raise ValueError(prepared['output'][-4000:])
        if config.associate_status_labels and not args:
            labels = capture_process(['node', str(Path(__file__).parent / 'tasks' /
                'associate_status_labels.mjs'), str(output_dir)], cwd=output_dir, timeout=15)
            if labels['returncode']:
                raise ValueError(labels['output'][-3000:])
        result = capture_process([*npm_command(), 'run', 'build', *args], cwd=output_dir, timeout=90)
        if result['returncode'] and config.build_repair:
            repaired = repair_implicit_parameters(output_dir, result['output'])
            if config.route_parameter_repair:
                repaired = repair_storefront_route_params(output_dir, result['output']) or repaired
            if repaired:
                result = capture_process([*npm_command(), 'run', 'build', *args], cwd=output_dir, timeout=90)
        if result['returncode']:
            raise ValueError(result['output'][-6000:])
        startup = capture_process(['node', '--input-type=module', '-e', STARTUP_CHECK],
            cwd=output_dir, timeout=15, env={'ARC_CHECK_FRONTEND': '0' if args else '1'})
        if startup['returncode']:
            raise ValueError(startup['output'][-6000:])
        if config.validate_sql_inserts:
            sql = capture_process(['node', str(Path(__file__).parent / 'tasks' /
                'validate_sql_inserts.mjs'), str(output_dir)], cwd=output_dir, timeout=15)
            if sql['returncode']:
                raise ValueError(sql['output'][-5000:])
        if config.probe_backend_contract:
            api = capture_process(['node', str(Path(__file__).parent / 'tasks' /
                'probe_backend_contract.mjs'), str(output_dir)], cwd=output_dir, timeout=25)
            if api['returncode']:
                raise ValueError(api['output'][-5000:])
        if config.ctrip_contract:
            api = capture_process(['node', str(Path(__file__).parent / 'tasks' /
                'probe_ctrip_backend.mjs'), str(output_dir)], cwd=output_dir, timeout=30)
            if api['returncode']:
                raise ValueError(api['output'][-5000:])

    def generate(instructions, payload, paths, build, *, attempts=None):
        def accept_files(result):
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
                if not config.build_repair:
                    raise
                # Repair a valid generated candidate before spending a full proposal.
                editor = FileTools(output_dir, writable=paths)
                original_limit, original_reasoning, original_client = (
                    model.max_output_tokens, model.reasoning, model.client)
                model.max_output_tokens = min(original_limit, config.build_repair_output_tokens)
                model.reasoning = 'none'
                model.client = original_client.with_options(timeout=65, max_retries=0)
                try:
                    diagnostics = str(build_error)
                    for number in range(config.build_repair_attempts):
                        try:
                            repair = model.generate_json(BUILD_REPAIR_PROMPT, {
                                'diagnostics': diagnostics, 'files': editor.state(),
                                **({'declared_initial_world': payload['declared_initial_world']}
                                   if 'declared_initial_world' in payload else {})})
                            edits = repair['tool_calls']
                            if not 1 <= len(edits) <= 6 or editor.effect(edits) != 'write':
                                raise ValueError('Expected one to six source edits')
                            editor.execute(edits)
                            build()
                            break
                        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as error:
                            diagnostics = str(error)
                            if number + 1 == config.build_repair_attempts:
                                raise ValueError(f'{build_error}\nLocal build repair failed: {error}') from error
                finally:
                    model.max_output_tokens, model.reasoning, model.client = (
                        original_limit, original_reasoning, original_client)
            return files

        def accept(result):
            if not config.rollback_failed_candidates:
                return accept_files(result)
            originals = {path: (output_dir / path).read_bytes() for path in paths}
            try:
                return accept_files(result)
            except BaseException:
                for path, content in originals.items():
                    save_bytes(output_dir / path, content)
                raise

        propose_json(model, instructions, payload, accept, console, 'Generate and build',
            max_attempts=config.generation_attempts if attempts is None else attempts)

    def style_frontend(references):
        # Keep a buildable template stylesheet if the optional visual pass fails.
        stylesheet = output_dir / FRONTEND[1]
        original = stylesheet.read_bytes()
        model.max_output_tokens = min(configured_output_limit, config.style_output_tokens)
        try:
            generate(
                'Style the supplied React application using the visual references. '
                'Return {"files":{"frontend/src/style.css":"complete CSS"}}. '
                'Use existing classes and retain usable layouts, forms and dialogs.' + config.style_guidance,
                {'app_source': read_source(output_dir / FRONTEND[0]), 'references': references},
                (FRONTEND[1],), check_build, attempts=config.style_attempts)
        except (RuntimeError, OSError, ValueError) as error:
            save_bytes(stylesheet, original)
            print(f'[compact] Kept template styling after visual pass failed: {type(error).__name__}', flush=True)
            check_build()

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
    if config.transient_retries:
        model.transient_retries = config.transient_retries
    model.reasoning = os.getenv('MODEL_REASONING', 'none').lower()
    large = len(source) > 100_000
    configured_output_limit = model.max_output_tokens
    model.max_output_tokens = min(configured_output_limit, config.large_output_tokens if large else config.small_output_tokens)
    model.client = model.client.with_options(timeout=360 if large else 180, max_retries=0)
    backend_prompt, frontend_prompt = config.backend_prompt, config.frontend_prompt
    print(f'[compiler] Task strategy: {config.key}', flush=True)

    def generate_frontend(frontend_request):
        if config.frontend_mode == 'joint_then_split_on_length':
            # The original release generated the paired view and CSS from one proposal.
            # If the gateway truncates that pair, use the recovered split pipeline.
            stylesheet = output_dir / FRONTEND[1]
            baseline_css = stylesheet.read_bytes()
            try:
                generate(frontend_prompt, frontend_request, FRONTEND, check_build, attempts=config.joint_attempts)
            except RuntimeError as error:
                if 'finish_reason=length' not in str(error):
                    raise
                save_bytes(stylesheet, baseline_css)
                print('[compact] Storefront frontend response truncated; generating TSX and CSS separately.', flush=True)
            else:
                return False
        elif config.frontend_mode == 'joint' or (config.frontend_mode == 'auto' and not large):
            generate(frontend_prompt, frontend_request, FRONTEND, check_build, attempts=config.joint_attempts)
            return False
        model.max_output_tokens = min(configured_output_limit, config.split_output_tokens)
        functional_prompt = frontend_prompt.replace(
            '"frontend/src/App.tsx":"complete React TSX source",\n'
            '"frontend/src/style.css":"complete CSS source"',
            '"frontend/src/App.tsx":"complete React TSX source"').replace(
            'both files and the closing JSON object', 'the TSX file and the closing JSON object')
        functional_prompt = functional_prompt.replace(
            'Generate TSX and CSS together, using shared layout, card and modal styles.',
            'Use shared class names for layouts, cards and modals.')
        functional_prompt += '\nUse meaningful CSS class names. A separate pass supplies the stylesheet.'
        generate(functional_prompt, frontend_request, (FRONTEND[0],), check_build)
        return True

    try:
        run('install dependencies', lambda: install_dependencies(output_dir, timeout=90))
        generation_source = source
        railway_world = None
        if config.railway_contract:
            from infrastructure.tasks.railway_context import prepare_context
            packet = prepare_context(source)
            generation_source = packet['requirements_yaml']
            railway_world = packet['declared_railway_world']
            save_json(output_dir / '.arc/initial_world.json', railway_world)
            save_text(output_dir / '.arc/generation_requirements.yaml', generation_source)
            save_json(output_dir / '.arc/context_metrics.json', {
                **packet['metrics'], 'generation_characters': len(generation_source)})
            print(f'[railway] Requirement context {len(source)} -> {len(generation_source)} characters; '
                  'all original requirements/scenarios retained.', flush=True)
        ctrip_world = None
        if config.ctrip_contract:
            from infrastructure.tasks.ctrip_context import prepare_context
            packet = prepare_context(source)
            generation_source = packet['requirements_yaml']
            ctrip_world = packet['declared_ctrip_world']
            save_json(output_dir / '.arc/initial_world.json', ctrip_world)
            save_text(output_dir / '.arc/generation_requirements.yaml', generation_source)
            save_json(output_dir / '.arc/context_metrics.json', packet['metrics'])
            print(f'[ctrip] Requirement context {len(source)} -> {len(generation_source)} characters; '
                  'all original requirements/scenarios retained.', flush=True)
        backend_request = {'requirements_yaml': generation_source,
            'declared_account_fixtures': account_fixtures(source)}
        if railway_world is not None:
            backend_request['declared_railway_world'] = railway_world
        if ctrip_world is not None:
            backend_request['declared_ctrip_world'] = ctrip_world
        if config.index_initial_world:
            backend_request['declared_initial_world'] = initial_world(source)
            save_json(output_dir / '.arc/initial_world.json', backend_request['declared_initial_world'])
        run('backend', lambda: generate(backend_prompt, backend_request, (BACKEND,),
            lambda: check_build('-w', '@arc/backend')))
        references = run('sample reference images', visual_evidence)
        frontend_request = {'requirements_yaml': generation_source,
            'backend_source': read_source(output_dir / BACKEND), 'references': references}
        if run('frontend', lambda: generate_frontend(frontend_request)):
            run('frontend styling', lambda: style_frontend(references))
        if config.railway_navigation_gate and suite is not None:
            navigation = run('railway navigation', lambda: ensure_railway_navigation(
                suite, output_dir, model, check_build))
            report['stages']['railway navigation']['status'] = navigation['status']
        if config.ctrip_contract and suite is not None:
            navigation = run('ctrip navigation', lambda: ensure_ctrip_navigation(
                suite, output_dir, model, check_build))
            report['stages']['ctrip navigation']['status'] = navigation['status']
            if navigation['status'] == 'GREEN':
                services = run('ctrip services', lambda: ensure_ctrip_services(
                    suite, output_dir, model, check_build))
                report['stages']['ctrip services']['status'] = services['status']
            else:
                report['stages']['ctrip services'] = {'status': 'BLOCKED_BY_NAVIGATION'}
        if suite is not None:
            if not bookstack_legacy:
                model.reasoning = 'none'
            model.client = model.client.with_options(timeout=75, max_retries=0)
            model.max_output_tokens = min(model.max_output_tokens, config.repair_output_tokens)
            acceptance = run('public acceptance', lambda: repair_with_acceptance(
                suite, output_dir, source, model, check_build, (BACKEND, *FRONTEND),
                bookstack_legacy=bookstack_legacy,
                repair_guidance=config.repair_guidance,
                **({'adaptive_repairs': True} if config.adaptive_repairs else {}),
                **({'repair_dependencies': dict(config.repair_dependencies)}
                   if config.repair_dependencies else {}),
                **({'retry_invalid_edits': True} if config.retry_invalid_edits else {}),
                **({'allow_zero_progress': True} if config.allow_zero_progress else {}),
                **({'max_repairs': config.acceptance_attempts,
                    'failure_limit': config.repair_failure_limit, 'edit_retries': config.repair_edit_retries}
                   if (config.acceptance_attempts, config.repair_failure_limit, config.repair_edit_retries)
                   != (3, 14, 0) else {})))
            report['stages']['public acceptance']['status'] = acceptance['status']
            if 'best' in acceptance:
                report['stages']['public acceptance'].update(
                    passed=acceptance['best']['passed'], failed=acceptance['best']['failed'])
        else:
            report['stages']['public acceptance'] = {'status': 'NO_MATCHING_SUITE'}
            print('[acceptance] No bundled suite matched this requirements tree.', flush=True)
    finally:
        model.client.close()
    report['status'] = ('PARTIAL' if report['stages'].get('public acceptance', {}).get('status') in
        {'PARTIAL', 'UNAVAILABLE'} else 'GREEN')
    save_json(report_path, report)
    print(f'[compact] Build passed. Report: {report_path}', flush=True)
