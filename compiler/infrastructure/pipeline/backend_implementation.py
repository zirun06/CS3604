"""Step 06: implement backend APIs against real-server HTTP acceptance suites."""

from pathlib import Path

from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.type_repair import recheck_types
from infrastructure.shared.agent.recovery import reject_paths, final_checks, complete_report
from infrastructure.shared.agent.files import editable_application_path
from infrastructure.stages.backend.context import load_context, supplied_sources, related_schema
from infrastructure.shared.agent.implementation_batches import ImplementationBatches, passing_checks, require_any
from infrastructure.shared.agent.feedback import CheckFailure
from infrastructure.stages.database.order import table_dependencies
from infrastructure.utils.files import read_artifact
from infrastructure.stages.backend.runtime import REGISTER_PATH, TEST_RUNNER_PATH, TEST_SUPPORT_PATH, prepare_runtime, test_path
from infrastructure.stages.backend.testing import BackendChecks, require_green, test_run_status
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json
from infrastructure.shared.project.git import checkpoint


TEST_INSTRUCTIONS = """Write one HTTP acceptance suite per entry in task.apis before implementing the group. Each entry has its own API, owners and test_path. Use each owner's requirement_evidence.
Derive expected outcomes from the requirement scenarios, API method/path, I/O, P/Q and DB
changes. Use edit_file to create the .test.ts target under backend/tests or update test_path.
Use { test } from node:test and assert from node:assert/strict with async test callbacks.
Import { createApiTest, fixturePasswordHash } as needed from task.support_module with a
relative .js ESM path. Do not import handlers, createApp, server or test aliases.

At the start of each test call const { database, baseURL } = createApiTest(t).
The compiler owns a real backend process running backend/src/server.ts, its assigned port
and its temporary on-disk database. The helper restores prerequisite data before each case
and opens that SAME database for Given setup and SQL observations. Test files/cases run
sequentially. Do not start a server, choose a port, create a separate database, run tests
concurrently, mock HTTP or call business functions directly.

Exercise EVERY success/rejection case through real HTTP:
const response = await fetch(new URL('/api/example', baseURL), {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ example: 'value' }), redirect: 'manual'
});
assert.equal(response.status, expectedStatus);
const body = await response.json();
Adapt the example to the canonical contract. Substitute encoded concrete route parameter
values, construct query strings and JSON bodies, and verify actual status/body/headers.
For 204 or other empty responses use text() or skip JSON parsing. Use redirect:'manual'
when validating status/Location. Node fetch does not maintain browser cookies: obtain
required cookies from real responses using headers.getSetCookie(), strip attributes and
send them in a Cookie header for subsequent requests when this API requires it. Supply
only contract-required authentication; do not test another requirement's login flow as
an incidental dependency. Necessary existing sessions/accounts can be prepared via SQL.
For requirement-defined authentication, assert real Set-Cookie/Cookie round-trips,
bootstrap with the same credential and rejection of another identity's records when required.
Exercise declared JSON field names, parameter names and rejection response shapes.

Seed only required Given state directly through database with parameterized SQL and valid
values; use 0/1 booleans. Read the actual shared helper/SQL definitions rather than guessing
fixture arguments or password encodings. Initialization loads db/seeds/ENTITY.sql; reuse
existing prerequisites instead of assuming empty tables or duplicating identities. Arrange
scenario-specific absence/conflicting states in this isolated database. Do not invoke
another requirement's registration/creation API to manufacture Given data.

Within max_tests cover meaningful success and critical requirement-defined rejection.
Assert relevant persisted results/forbidden writes with SQL where needed; HTTP is the
only way to execute the operation. Do not assert unspecified wording, random identifiers,
hashes or timestamps. Do not inspect source text, add mocks, skip/focus tests or hardcode
success. Browser workflows belong to frontend E2E. Missing routes/behavior should fail real
assertions; do not expect 404/501 merely because this API is not implemented yet.

The compiler compiles the suite, runs accepted HTTP regressions, then runs this suite
against the actual backend. Assertion RED establishes missing behavior. Existing behavior
may already be GREEN; no stub replaces it. Backend startup failures are implementation
feedback, not proof the test is wrong. During generation repair test syntax/fixtures and
existing compilation problems, not the new operation. Generated tests remain correctable
against requirement evidence; preserve valid success/rejection coverage and previous tests.
"""

IMPLEMENT_INSTRUCTIONS = """Implement all entries in task.apis according to their canonical contracts against their generated tests.
Read the associated implementation files and extend or create business sources inside the supplied backend scope.
Choose meaningful filenames, reuse existing helpers, and extend shared API wiring incrementally. For an API module export:
export async function handle(request: ApiRequest, connection: Database.Database): Promise<ApiResponse>.
The export is always handle; signature.name identifies the business operation.
Tests exercise the operation through HTTP, not through an exported test alias. Import ApiRequest and ApiResponse from backend/src/api/types.ts
using a relative .js ESM import. Return status/body/optional headers, not Express objects.

Implement request validation, API preconditions, success/rejection responses and DB
effects according to the contract and scenarios. Use the supplied connection, parameterized
better-sqlite3 SQL, and transactions for related writes. Respect schema-generated integer
keys and use node:crypto for UUIDs or hashing when the schema/contract requires them.
Use the supplied test utilities and generated tests to understand existing fixture data
conventions. Preserve compatibility when reading those records. Production storage must
satisfy the contract and keep plaintext passwords out of persistent data.
Preserve required comparison rules and shared credential/header conventions.

Do not start a server, open another database, change schema or seed production data.
Use installed dependencies and Node standard modules. Implement the operation directly;
no DB-access primitive layer is generated. The compiler owns the HTTP test runner and fixture.
Predefined credentials in seeds/*.sql use seed_password_hash; its scrypt encoding is
defined in backend/src/db/seed.ts and must remain readable by credential handlers.
Read and edit task.api_wiring.registry to import this handle and register its actual
Express route, adapting params/query/body/headers and status/body/headers between HTTP
and the handler contract. Inspect app/server wiring when needed. The compiler will not
regenerate these files. Preserve all existing routes and middleware; insert/update this
API without replacing unrelated registrations or introducing duplicate routes. Extend
the existing registerApis implementation; never rebuild its body or route map with only
the current API. Earlier requirement implementations remain mandatory. Translate
contract path placeholders (including {name}) to syntax accepted by the installed router;
pass concrete parameter names and values to handle. Preserve cookies and error handling.
Use read_file with optional line ranges, to inspect related wiring; read only the relevant missing
lines and use a unique exact edit_file replacement. Do not start the production server in source code.
Preserve unrelated behavior when repairing other supplied writable backend sources.
The generated acceptance tests are read-only during implementation.
SQL, designs, test utilities and compiler infrastructure remain references.
The compiler starts the real server and runs current/accepted HTTP API suites after TypeScript checks. Repair implementation
failures without weakening assertions or detecting tests to fake business behavior.
"""



def api_capability_signals(api, modules):
    """Use route families and transitive business operations, plus shared DB entities."""
    path = api["signature"]["path"]
    family = next((part for part in path.split("/")[2:] if part and not part.startswith((":", "{"))), "")
    calls, pending = set(), list(api.get("callees", []))
    while pending:
        target = pending.pop()
        if target not in calls:
            calls.add(target)
            pending.extend(modules.get(target, {}).get("callees", []))
    return {*(f"module:{item}" for item in calls),
        *(f"entity:{field.split('.', 1)[0]}" for field in api["read"] + api["write"]),
        *([f"route:{family}"] if family else [])}


def implement_backend_tdd(arc_dir: Path, pause: bool = False, max_turns: int = 10, max_tests: int = 5) -> dict:
    if min(max_turns, max_tests) < 1:
        raise ValueError("max_turns and max_tests must be positive")
    tree, schema, _ = load_context(arc_dir)
    contracts = read_artifact(arc_dir, "backend_apis.json")
    output = arc_dir.parent.resolve()
    if not (output / "backend/src/db/initialize.ts").is_file():
        raise ValueError("Missing database initializer; run stage 04")
    prepare_runtime(output)
    install_dependencies(output)
    console = DemoConsole(pause)
    owners = {aid: [rid for rid in tree.leaves if aid in contracts["requirements"].get(rid, [])]
        for aid in contracts["apis"]}
    apis = {aid: api for aid, api in contracts["apis"].items() if owners[aid]}
    dependencies = table_dependencies(schema)
    blocked_apis = {}
    for aid, api in apis.items():
        required = set(related_schema(schema, [api]))
        pending = list(required)
        while pending:
            for target in dependencies[pending.pop()]:
                if target not in required:
                    pending.append(target)
                    required.add(target)
        missing = sorted(name for name in required if not (output / f"backend/src/db/tables/{name}.sql").is_file())
        if missing:
            blocked_apis[aid] = {"status": "FAILED", "api": aid, "error": "Missing table SQL", "tables": missing}
    apis = {aid: api for aid, api in apis.items() if aid not in blocked_apis}
    paths = {aid: test_path(owners[aid][0], aid) for aid in apis}
    signals = {aid: api_capability_signals(api, contracts["modules"]) for aid, api in apis.items()}
    batches = ImplementationBatches(arc_dir, "06", console).register(apis, owners, signals)
    report = {"status": "RUNNING", "requirements": {}, "apis": {}, "tests": {}, "red": {}, "green": {}, "agents": {}}
    def record_requirements():
        for rid in tree.leaves:
            ids = contracts["requirements"].get(rid, [])
            if rid not in contracts["requirements"]:
                report["requirements"][rid] = {"status": "FAILED", "requirement": rid, "apis": [],
                    "error": "Missing accepted backend design"}
            else:
                report["requirements"][rid] = {"requirement": rid, "apis": ids, "status": (
                    "NO_DIRECT_APIS" if not ids else "GREEN" if all(aid in batches.accepted for aid in ids) else "FAILED")}

    report_path = arc_dir / "backend_tdd.json"
    save_json(report_path, report)
    if not apis:
        batches.publish()
        report["apis"].update(blocked_apis)
        record_requirements()
        complete_report(report, [*blocked_apis.values(), *report["requirements"].values()], {})
        if report["status"] == "GREEN":
            report["status"] = "NO_APIS"
        report["summary"] = {"tests": 0, "pass": 0, "fail": 0}
        save_json(report_path, report)
        return report
    checks, model = BackendChecks(output), TextModel()

    def process(batch, entry):
        selected = {aid: paths[aid] for aid in batch.units}
        tests = list(selected.values())
        sources = list(dict.fromkeys(path for aid in selected for path in supplied_sources(output, apis[aid], schema)))
        regression = [paths[aid] for aid in batches.regression(batch)]
        context = batches.context(batch, {"apis": {aid: {"api": apis[aid], "owners": owners[aid], "test_path": relative}
                for aid, relative in selected.items()}, "db_schema": related_schema(schema, [apis[aid] for aid in selected]),
            "max_tests": max_tests, "support_module": TEST_SUPPORT_PATH,
            "api_wiring": {"registry": REGISTER_PATH, "app": "backend/src/app.ts", "server": "backend/src/server.ts"}})
        existing = {path: (output / path).read_bytes() for path in tests if (output / path).is_file()}

        def compile_tests(files, workspace=None):
            compiled = recheck_types(lambda: checks.typecheck(files), workspace)
            if compiled["returncode"]:
                raise CheckFailure("Test TypeScript compilation failed", compiled)
            return compiled

        def generation_gate():
            compiled = compile_tests(tests)
            def observe(aid):
                if not (output / paths[aid]).is_file():
                    raise ValueError(f"Missing canonical test for {aid}")
                result = checks.tests([paths[aid]])
                return {**result, "status": test_run_status(result)}
            passed, rejected = passing_checks(batch.units, observe, lambda _: None)
            require_any(passed, rejected)
            return {"typecheck": compiled, "passed": passed, "rejected": rejected}

        test_workspace = FileTools(output, ["backend"], requirements=entry["requirements"], stage="backend",
            files=[*tests, *sources, TEST_SUPPORT_PATH], writable=tests)
        generated = run_file_agent(model, TEST_INSTRUCTIONS, {**context, "test_paths": tests}, test_workspace,
            generation_gate, max_turns, console, batch.id + " / test generation", test_phase="generation", batch_limits=True)
        generated_checks = generated["checks"]
        for aid in generated_checks["rejected"]:
            relative = paths[aid]
            generated_checks["rejected"][aid]["archive"] = reject_paths(
                output, batch.id + " / " + aid, existing, [relative])
        candidates = tuple(generated_checks["passed"])
        active_files = [paths[aid] for aid in candidates]

        def implementation_gate():
            compiled = compile_tests([*active_files, *regression], workspace)
            if regression:
                require_green(checks.tests(regression))
            passed, rejected = passing_checks(candidates, lambda aid: checks.tests([paths[aid]]), require_green)
            require_any(passed, rejected)
            return {"typecheck": compiled, "passed": passed, "rejected": rejected}

        workspace = FileTools(output, ["backend"], requirements=batches.requirement_ids(candidates), stage="backend",
            files=[REGISTER_PATH, *active_files, *sources],
            allow_write=lambda relative: "/tests/" not in relative and editable_application_path(output, relative))
        task = {**context, "units": list(candidates), "apis": {aid: context["apis"][aid] for aid in candidates}}
        implemented = run_file_agent(model, IMPLEMENT_INSTRUCTIONS, task, workspace, implementation_gate,
            max_turns, console, batch.id + " / implementation", feedback=generated_checks, batch_limits=True, protect_candidates=True)
        results = implemented["checks"]
        for aid, evidence in results["rejected"].items():
            evidence["test_archive"] = reject_paths(output, batch.id + " / " + aid, existing, [paths[aid]])
        entry["rejected_checks"] = {**generated_checks["rejected"], **results["rejected"]}
        return {aid: {"api": aid, "requirements": owners[aid], "test_path": paths[aid],
            "red": generated_checks["passed"][aid], "green": evidence,
            "test_turns": generated["turns"], "implementation_turns": implemented["turns"]}
            for aid, evidence in results["passed"].items()}

    try:
        report["apis"] = {**blocked_apis, **batches.run(process)}
        for aid, entry in batches.accepted.items():
            for owner in owners[aid]:
                report["tests"].setdefault(owner, {})[aid] = paths[aid]
            report["red"][aid] = entry["red"]
            report["green"][aid] = entry["green"]
            report["agents"][aid] = {"generation": entry["test_turns"], "implementation": entry["implementation_turns"]}
        record_requirements()
        all_files = [paths[aid] for aid in batches.accepted]
        verification = final_checks(console, typecheck=(checks.typecheck, None),
            tests=(lambda: checks.tests(all_files), require_green if all_files else None), build=(checks.build, None))
        final = verification["tests"].get("result") or {}
        report["summary"] = {key: final.get(key, 0) for key in ("tests", "pass", "fail")}
        complete_report(report, [*report["apis"].values(), *report["requirements"].values()], verification)
        save_json(report_path, report)
        checkpoint(output, stage="06", task="API acceptance", action="Publish grouped backend report", details=report["summary"])
        return report
    finally:
        model.client.close()
