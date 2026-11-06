"""Repair Ctrip airport/voucher components in isolation before broad acceptance."""
import json
from pathlib import Path
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from infrastructure.compact_acceptance import prepare_workspace, run_suite
from infrastructure.utils.files import save_bytes, save_json
from infrastructure.utils.processes import capture_process

SCRIPTS = Path(__file__).parent
APP = 'frontend/src/App.tsx'
PROMPT = """Repair ONLY the supplied existing Ctrip airport/voucher components.
Return JSON {"components": {actual_name: complete_function_or_arrow_declaration}}.
Do not modify imports, global navigation, auth, other pages, routes or backend.
Use existing APIs, their supplied response shapes, real owner-scoped records and
existing routes. No fake inventory, orders, hidden duplicate targets or test edits.
Airport/city names and Boarding process are real links. C is a filter button.
Directory routes must select their corresponding tab and expose its city links
immediately. Weather city and temperature are independently visible text values.
Voucher rows have accessible identity Record <actual order number>; preserve
owner boundaries, eligibility, completed/pending state, and existing old-order
expansion. Do not replace API data with constants or invent unsupported services.
Airport bus and phone records use Record <actual service name> within their list
region. Keep each stop/time/headway/phone value independently identifiable.
Fix the supplied failures without losing any previously passing service scenario.
Keep all referenced types, functions and imports compatible with the existing app.
"""


def ensure_services(suite: Path, output: Path, model, check_build, *, max_repairs: int = 2) -> dict:
    output = output.resolve()
    best_source = (output / APP).read_bytes()
    report = {'status': 'RUNNING', 'attempts': []}
    settings = model.max_output_tokens, model.reasoning, model.client
    report_path = output / '.arc/ctrip_services.json'
    try:
        inspected = capture_process(['node', str(SCRIPTS/'ctrip_components.mjs'), str(output), 'inspect-services'], cwd=output, timeout=20)
        if inspected['returncode']:
            raise ValueError(inspected['output'][-3000:])
        contract = json.loads(inspected['stdout'].strip().splitlines()[-1])
        if not contract['replaceable_components']:
            report['status'] = 'UNAVAILABLE'
            return report
        with TemporaryDirectory(prefix='arc-ctrip-services-') as temporary:
            browser = Path(temporary)
            prepare_workspace(suite, browser)
            best = run_suite(browser, output, grep=r'REQ-(?:8|9)[.]')
            report['attempts'].append({'kind': 'initial', **best})
            report['best'] = best
            model.max_output_tokens = min(settings[0], 12000)
            model.reasoning = 'none'
            model.client = settings[2].with_options(timeout=100, max_retries=0)
            feedback = None
            for number in range(1, max_repairs + 1):
                if not best['failed'] and not best['skipped']:
                    break
                print(f"[ctrip services] {best['passed']} passed, {best['failed']} failed; bounded repair {number}/{max_repairs}", flush=True)
                save_json(report_path, report)
                try:
                    # The current best source, not a stale pre-repair declaration.
                    inspected = capture_process(['node', str(SCRIPTS/'ctrip_components.mjs'), str(output), 'inspect-services'], cwd=output, timeout=20)
                    if inspected['returncode']:
                        raise ValueError(inspected['output'][-3000:])
                    contract = json.loads(inspected['stdout'].strip().splitlines()[-1])
                    reply = model.generate_json(PROMPT, {'component_contract': contract, 'service_failures': best['failures'], 'previous_repair': feedback})
                    proposal = output/'.arc/ctrip_services_proposal.json'
                    save_json(proposal, reply)
                    applied = capture_process(['node', str(SCRIPTS/'ctrip_components.mjs'), str(output), 'apply-services', str(proposal)], cwd=output, timeout=20)
                    if applied['returncode']:
                        raise ValueError(applied['output'][-4000:])
                    check_build()
                    candidate = run_suite(browser, output, grep=r'REQ-(?:8|9)[.]')
                    accepted = candidate['passed'] > best['passed'] and not candidate['skipped'] and not (set(candidate['failures'])-set(best['failures']))
                    report['attempts'].append({'kind': 'repair', 'number': number, 'accepted': accepted, **candidate})
                    if accepted:
                        best, best_source = candidate, (output/APP).read_bytes()
                        report['best'] = best
                        feedback = None
                    else:
                        feedback = {'candidate_failures': candidate['failures'], 'reason': 'No verified gain or a previous passing scenario regressed; changes restored.'}
                except (ValueError, KeyError, TypeError, RuntimeError, OSError, TimeoutExpired) as error:
                    feedback = {'error': str(error)[-4000:]}
                    report['attempts'].append({'kind': 'repair', 'number': number, 'accepted': False, **feedback})
                if (output/APP).read_bytes() != best_source:
                    save_bytes(output/APP, best_source)
                    check_build()
            report['status'] = 'GREEN' if not best['failed'] and not best['skipped'] else 'PARTIAL'
    except (ValueError, KeyError, TypeError, RuntimeError, OSError, TimeoutExpired) as error:
        report.update(status='UNAVAILABLE', error=str(error)[-4000:])
        if (output/APP).read_bytes() != best_source:
            save_bytes(output/APP, best_source)
            check_build()
    finally:
        model.max_output_tokens, model.reasoning, model.client = settings
        save_json(report_path, report)
    return report
