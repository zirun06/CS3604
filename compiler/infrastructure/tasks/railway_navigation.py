"""Repair a bounded shared layout against a short real-browser prerequisite gate."""

import json
from pathlib import Path
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from infrastructure.compact_acceptance import prepare_workspace
from infrastructure.utils.files import save_bytes, save_json
from infrastructure.utils.processes import capture_process


SCRIPTS = Path(__file__).parent
APP = 'frontend/src/App.tsx'
PROMPT = '''Repair only the 12306 personal-center layout/navigation architecture.
Return one JSON object with a components object mapping ACTUAL allowed component
names to their complete source declarations. The actual existing names and sources
are the keys of component_contract.replaceable_components; new names are explicitly
listed in component_contract.allowed_new_components. Omit unchanged components.
Replace whole listed components, NOT edit_file fragments and NOT the whole App.tsx file.
All other existing source, imports, APIs and business page components are retained.

Critical architecture:
- Personal center menu must remain mounted on EVERY personal subpage, after parent
  navigation and after reload, inside the existing authentication protection.
- Its links are Personal Center; Order center -> Ticket orders; Personal -> User
  information, Account security, Verify mobile number; Information management -> My
  Passengers. All those actions are links. Do NOT replace Order center with summary,
  details or button. Parent links may share a destination with their first child,
  but the destination must still contain the complete menu and child links.
- Reuse the ACTUAL destinations from existing_links/routes. Never invent a URL or
  route to a component that does not exist. My Passengers and User information must
  use the correct casing even if the header has My passengers in its dropdown.
- A safe design is ArcRailwayPersonalLayout({children}) with shared menu and children.
  In EACH existing personal Route keep the original guard AND original view, placing
  the layout INSIDE that guard. Keep the routes flat, same order and exact paths.
  Preserve original notice, ticket-booking link and user display on PersonalCenter,
  removing its duplicate embedded menu when a shared layout now supplies it.
- Preserve App's session provider, router, header/footer, hooks and initialization.
  Reuse already imported Link/Router components; do not add imports or use Outlet.
  Return each component as one function declaration or one arrow variable statement
  with its exact name. Preserve existing exports. The new layout must accept children
  without requiring new props from original business pages.
- Native links and real nested content must render; no hidden duplicates, fake pages
  or application/test data changes. Solve the whole shared structure in this proposal.
'''


def component_contract(output: Path) -> dict:
    result = capture_process(['node', str(SCRIPTS / 'railway_components.mjs'), str(output), 'inspect'],
                             cwd=output, timeout=15)
    if result['returncode']:
        raise ValueError(result['output'][-4000:])
    return json.loads(result['stdout'].strip().splitlines()[-1])


def ensure_navigation(suite: Path, output: Path, model, check_build, *, max_repairs: int = 2) -> dict:
    """A failed/unavailable optional gate restores the original App and remains reported."""
    output = output.resolve()
    report = {'status': 'RUNNING', 'attempts': []}
    report_path = output / '.arc/railway_navigation.json'
    original = (output / APP).read_bytes()
    limit, reasoning, client = model.max_output_tokens, model.reasoning, model.client

    def publish():
        save_json(report_path, report)

    try:
        with TemporaryDirectory(prefix='arc-railway-navigation-') as temporary:
            browser = Path(temporary)
            prepare_workspace(suite, browser)

            def probe():
                result = capture_process(['node', str(SCRIPTS / 'probe_railway_navigation.mjs'),
                    str(output), str(browser)], cwd=output, timeout=65)
                try:
                    diagnostic = json.loads(result['stdout'].strip().splitlines()[-1])
                except (ValueError, IndexError) as error:
                    raise RuntimeError(result['output'][-4000:]) from error
                return diagnostic

            failure = probe()
            report['attempts'].append({'kind': 'initial', **failure})
            publish()
            if failure['status'] == 'GREEN':
                report['status'] = 'GREEN'
                return report
            # A session/API failure is outside a layout-only repair's write scope.
            if failure.get('step') in {'initialization', 'login and reload', 'start'}:
                report.update(status='BLOCKED_BY_SESSION', reason='Leave session/API failures to normal acceptance repair')
                return report
            contract = component_contract(output)
            if 'App' not in contract['replaceable_components']:
                report.update(status='UNAVAILABLE', reason='No bounded App component found')
                return report
            model.max_output_tokens = min(limit, 10000)
            model.reasoning = 'none'
            model.client = client.with_options(timeout=100, max_retries=0)
            previous = None
            for number in range(1, max_repairs + 1):
                print(f'[railway navigation] Repair layout {number}/{max_repairs}; blocked at {failure.get("step")}', flush=True)
                save_bytes(output / APP, original)
                try:
                    reply = model.generate_json(PROMPT, {'component_contract': contract,
                        'browser_failure': failure, 'previous_repair': previous})
                    proposal = output / '.arc/railway_components_proposal.json'
                    save_json(proposal, reply)
                    applied = capture_process(['node', str(SCRIPTS / 'railway_components.mjs'),
                        str(output), 'apply', str(proposal)], cwd=output, timeout=15)
                    if applied['returncode']:
                        raise ValueError(applied['output'][-4000:])
                    check_build()
                    candidate = probe()
                    report['attempts'].append({'kind': 'repair', 'number': number, **candidate})
                    if candidate['status'] == 'GREEN':
                        report['status'] = 'GREEN'
                        return report
                    previous = {'message': 'Candidate failed; original components have been restored.', 'candidate_failure': candidate}
                except (ValueError, KeyError, TypeError, RuntimeError, OSError, TimeoutExpired) as error:
                    previous = {'error': str(error)[-5000:]}
                    report['attempts'].append({'kind': 'repair', 'number': number, 'status': 'REJECTED', **previous})
                save_bytes(output / APP, original)
                check_build()
                publish()
            report['status'] = 'FAILED'
    except (ValueError, KeyError, TypeError, RuntimeError, OSError, TimeoutExpired) as error:
        report.update(status='UNAVAILABLE', error=str(error)[-4000:])
        if (output / APP).read_bytes() != original:
            save_bytes(output / APP, original)
            check_build()
    finally:
        model.max_output_tokens, model.reasoning, model.client = limit, reasoning, client
        publish()
    return report
