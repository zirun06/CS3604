"""Step 04: implement dependency groups and source-grounded prerequisite data."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from infrastructure.shared.agent.implementation_batches import ImplementationBatches, require_any
from infrastructure.shared.agent.recovery import reject_paths
from infrastructure.shared.agent.tools.file_tools import NativeFileTools
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.implementation import implement_startup_data, verify_database_runtime
from infrastructure.stages.database.implementation_agent import DatabaseImplementationAgent
from infrastructure.stages.database.order import implementation_groups, table_dependencies
from infrastructure.stages.database.runtime import initializer_source
from infrastructure.utils.files import read_artifact, read_source, save_text, save_json
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.presentation.events import validation


def table_path(name):
    return f"backend/src/db/tables/{name}.sql"


class TableCheck:
    @validation("database_check")
    def run(self, name, content, fields):
        """Verify the individual DDL file in isolated SQLite before committing it."""
        try:
            with closing(sqlite3.connect(":memory:")) as connection:
                def ddl_only(action, table, *_):
                    if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH} or (
                        action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
                        and not (table or "").startswith("sqlite_")
                    ):
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                connection.set_authorizer(ddl_only)
                connection.executescript(content)
                connection.set_authorizer(None)
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                if tables != [(name,)]:
                    raise ValueError(f"Expected only table {name}, got {tables}")
                columns = {row[1] for row in connection.execute("SELECT * FROM pragma_table_info(?)", (name,))}
                if columns != set(fields):
                    raise ValueError(f"{name} columns {sorted(columns)} differ from the schema")
        except (sqlite3.Error, ValueError) as error:
            return {"returncode": 1, "output": str(error)}
        return {"returncode": 0, "output": f"Created {name} with its declared columns"}


def implement_db(arc_dir: Path, pause: bool = False) -> dict:
    output = arc_dir.parent.resolve()
    schema = read_artifact(arc_dir, "db_schema.json")
    if not schema["entities"] and not schema["requirements"]:
        return {"status": "MISSING_PREREQUISITES", "missing": ["Accepted schema design in db_schema.json"]}
    for required in ("backend/package.json", "backend/src/db/client.ts", "backend/src/db/initialize.ts"):
        if not (output / required).is_file():
            raise ValueError("Run main.py --stage 00 first to initialize the project structure")
    console = DemoConsole(pause)
    groups = implementation_groups(schema)
    order = [name for group in groups for name in group]
    dependencies = table_dependencies(schema)
    values = {name: schema["entities"][name] for name in order}
    owners = {name: [rid for rid, fields in schema["requirements"].items()
        if any(field.split(".", 1)[0] == name for field in fields)] for name in order}
    signals = {name: {name, *dependencies[name]} for name in order}
    # Preserve dependency order; unrelated adjacent tables stay in separate batches.
    batches = ImplementationBatches(arc_dir, "04", console, phase="ddl").register(values, owners, signals, ordered=True)
    implementations = {}

    def process(batch, entry):
        targets = {name: table_path(name) for name in batch.units}
        nearby = {target for name in batch.units for target in dependencies[name]}
        request = batches.context(batch, {"tables": {name: {"entity": values[name], "output_path": path,
            "references": dependencies[name]} for name, path in targets.items()},
            "dependency_order": order, "referenced_tables": {name: values[name] for name in sorted(nearby)}})
        tools = NativeFileTools(output, requirements=entry["requirements"], stage="database",
            writable=targets.values(), readable=[table_path(name) for name in sorted(nearby)])
        baseline = {path: (output / path).read_bytes() for path in targets.values() if (output / path).is_file()}
        agent = DatabaseImplementationAgent(json_mode=False)
        try:
            agent.run(request, tools)
        finally:
            agent.model.client.close()
        passed, rejected = {}, {}
        checker = TableCheck()
        for name, relative in targets.items():
            path = output / relative
            if not path.is_file():
                rejected[name] = {"error": f"Missing {relative}"}
                continue
            content = read_source(path)
            result = checker.run(name, content, values[name]["fields"])
            if result["returncode"]:
                rejected[name] = result
            else:
                passed[name] = {"path": relative, "content": content}
        require_any(passed, rejected)
        for name, evidence in rejected.items():
            evidence["archive"] = reject_paths(output, batch.id + " / " + name, baseline, [targets[name]])
        entry["rejected_checks"] = rejected
        return passed

    ddl = batches.run(process)
    implementations.update({name: {k: ddl[name][k] for k in ("path", "content")}
        for name in order if ddl[name]["status"] == "GREEN"})
    # A table with a missing FK target cannot join the runnable subset.
    blocked = []
    changed = True
    while changed:
        changed = False
        for name in tuple(implementations):
            missing = sorted(set(dependencies[name]) - implementations.keys())
            if missing:
                blocked.append({"status": "FAILED", "table": name, "error": "Missing foreign-key targets",
                    "tables": missing})
                del implementations[name]
                changed = True
    initializer = output / "backend/src/db/initialize.ts"
    if not initializer.resolve().is_relative_to(output):
        raise ValueError("DB initializer path escapes the output directory")
    save_text(initializer, initializer_source(implementations))
    checkpoint(output, stage="04", task="database initializer", action="Publish ordered SQL initialization",
        details={"table_order": order, "published_tables": list(implementations)})
    seeds = implement_startup_data(arc_dir, schema, console, list(implementations))
    runnable_schema = {**schema, "entities": {name: schema["entities"][name] for name in implementations}}
    report = verify_database_runtime(arc_dir, runnable_schema, console)
    failures = [*blocked, *(value for value in [*ddl.values(), *seeds.values()] if value["status"] != "GREEN")]
    if failures:
        report.update(status="COMPLETED_WITH_FAILURES", failures=failures)
        save_json(arc_dir / "db_checks.json", report)
        return report
    return implementations
