"""Ctrip-only bounded global-navigation repair with real browser validation."""

import json
from pathlib import Path
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from infrastructure.compact_acceptance import prepare_workspace
from infrastructure.utils.files import save_bytes, save_json
from infrastructure.utils.processes import capture_process


SCRIPTS = Path(__file__).parent
APP = 'frontend/src/App.tsx'
PROMPT = """Repair only the Ctrip Global navigation component.
Return one JSON object with a components mapping from ACTUAL names in
component_contract.replaceable_components to their complete declarations.
Only these existing components may change; all pages, APIs and imports remain.
Use the supplied existing_links and routes for every navigation destination.
- Global navigation is one named navigation landmark, visible on every page.
- Flights is a native button opening flight links, including Flight status. The
  trigger must be the only action named Flights; label its search child Flight search.
- More services is a unique action opening the EXISTING more-services hub route.
  Preserve access to Airport guide, Reimbursement vouchers, Domestic airport directory
  and International airport directory. Prefer navigating to that existing hub over
  replacing it with an incomplete dropdown.
- Signed-in My account is a native button opening real links Orders and Personal
  center inside a role=menu container. Do NOT override Orders/Personal center to
  role=menuitem. Log out ALONE keeps role=menuitem, as explicitly required.
- Hover and click must cooperate: opening the menu on pointer enter must not make
  the subsequent click close it. Clicking My account must leave its links visible.
- Keep the current auth/context hook, login/register links, logout API and refresh
  behavior. Use existing Link and useNavigate/useState imports as already available.
- Keep the source's logo and other global behavior. No fake data or hidden duplicate
  targets. Preserve all original routes and root providers.
Return each replacement as exactly one complete function or arrow declaration.
"""


def component_contract(output: Path) -> dict:
    result = capture_process(['node', str(SCRIPTS / 'ctrip_components.mjs'), str(output), 'inspect'],
                             cwd=output, timeout=15)
    if result['returncode']:
        raise ValueError(result['output'][-4000:])
    return json.loads(result['stdout'].strip().splitlines()[-1])


def ensure_navigation(suite: Path, output: Path, model, check_build, *, max_repairs: int = 2) -> dict:
    """A failed/unavailable optional gate restores the original App and remains reported."""
    output = output.resolve()
    report = {'status': 'RUNNING', 'attempts': []}
    report_path = output / '.arc/ctrip_navigation.json'
    original = (output / APP).read_bytes()
    limit, reasoning, client = model.max_output_tokens, model.reasoning, model.client

    def publish():
        save_json(report_path, report)

    try:
        with TemporaryDirectory(prefix='arc-ctrip-navigation-') as temporary:
            browser = Path(temporary)
            prepare_workspace(suite, browser)

            def probe():
                result = capture_process(['node', str(SCRIPTS / 'probe_ctrip_navigation.mjs'),
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
            if failure.get('step') in {'initialization', 'password credentials', 'password login', 'start'}:
                report.update(status='BLOCKED_BY_SESSION', reason='Leave session/API failures to normal acceptance repair')
                return report
            contract = component_contract(output)
            if not contract['replaceable_components']:
                report.update(status='UNAVAILABLE', reason='No bounded Global navigation component found')
                return report
            model.max_output_tokens = min(limit, 10000)
            model.reasoning = 'none'
            model.client = client.with_options(timeout=100, max_retries=0)
            previous = None
            for number in range(1, max_repairs + 1):
                print(f'[ctrip navigation] Repair layout {number}/{max_repairs}; blocked at {failure.get("step")}', flush=True)
                save_bytes(output / APP, original)
                try:
                    reply = model.generate_json(PROMPT, {'component_contract': contract,
                        'browser_failure': failure, 'previous_repair': previous})
                    proposal = output / '.arc/ctrip_components_proposal.json'
                    save_json(proposal, reply)
                    applied = capture_process(['node', str(SCRIPTS / 'ctrip_components.mjs'),
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
