"""Accumulate source-grounded startup rows and run canonical database checks."""

from contextlib import closing
import re
import sqlite3

from infrastructure.shared.agent.design_batches import check_request_size
from infrastructure.shared.agent.feedback import CheckFailure
from infrastructure.shared.agent.implementation_batches import ImplementationBatches, require_any
from infrastructure.shared.models.text import TextModel
from infrastructure.stages.database.implementation_agent import SEED_INSTRUCTIONS
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.order import table_dependencies
from infrastructure.stages.database.testing import DatabaseChecks
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.utils.files import read_artifact, read_source, save_json, save_text
from infrastructure.stages.database.runtime import seed_source
from infrastructure.utils.presentation.events import validation


SEED_PATH = "backend/src/db/seed.ts"
EXPLICIT = re.compile(r"\b(?:prerequisites?|preconditions?|startup data|seed data|pre[- ]?existing|"
    r"already (?:exists?|contains?|has|present)|initial (?:data|records))\b", re.I)
HEADING = re.compile(r"^\s*(?:#+\s*|\*\*)?(?:when|then|actions?|scenarios?|outcomes?)\b", re.I)
ABSENCE = re.compile(r"\b(?:there (?:is|are) no|does not exist|do not exist|not yet (?:created|registered))\b", re.I)
INSERT = re.compile(r'^\s*INSERT\s+INTO\s+(?:"([^"]+)"|\[([^\]]+)\]|([\w]+))\s*\(', re.I)
SQL_LITERAL = re.compile(r"'(?:''|[^'])*'")
SEED_RESPONSE = """
Return JSON {"requirements":{requirement_id:{"rows":[{"table":"Entity",
"sql":"INSERT INTO Entity (...) SELECT ... WHERE NOT EXISTS (...);",
"evidence":{"source":"description:0 or exact step ID","quote":"verbatim source text",
"identity":"concrete identifying text in both the quote and SQL"}}]}}}.
Return exactly one entry per unit, even when rows is empty. Quote ONLY a supplied
prerequisite evidence entry. Generic statements with no concrete identifying value do not
authorize a row. Do not quote When or Then. Never seed what an action creates. Only propose
a single idempotent INSERT statement per row, and keep earlier rows unchanged.
"""


def prerequisite_evidence(requirement, steps):
    """Index explicitly marked prerequisite paragraphs and Given clauses with stable source IDs."""
    evidence = {}
    for index, block in enumerate(re.split(r"\n\s*\n", requirement["description"])):
        lines = []
        for line in block.splitlines():
            if HEADING.match(line):
                break
            lines.append(line)
        text = "\n".join(lines)
        if EXPLICIT.search(text):
            evidence[f"description:{index}"] = text
    for step in steps:
        # A Given clause that asserts absence is a test precondition, not a seed row.
        existing = "\n".join(line for line in step["Given"].splitlines() if not ABSENCE.search(line))
        if existing:
            evidence[step["id"]] = existing
    return evidence


def validate_seed_row(row, sources, allowed):
    table, sql, proof = row["table"], row["sql"].strip(), row["evidence"]
    source = sources.get(proof["source"], "")
    quote, identity = proof["quote"], proof["identity"]
    if not quote or quote not in source or not identity or identity not in quote or identity not in sql:
        raise ValueError("Seed row lacks a concrete identity grounded in supplied prerequisite evidence")
    match = INSERT.match(sql)
    if table not in allowed or not match or table not in match.groups():
        raise ValueError("Seed SQL must insert into its assigned canonical table")
    unquoted = SQL_LITERAL.sub("''", sql).rstrip()
    if (not sqlite3.complete_statement(sql) or unquoted.count(";") != 1 or not unquoted.endswith(";")
            or not re.search(r"\b(?:WHERE\s+NOT\s+EXISTS|ON\s+CONFLICT\b.*?DO\s+NOTHING)\b", unquoted, re.I | re.S)
            or re.search(r"\b(?:UPDATE|DELETE|DROP|REPLACE|ATTACH|PRAGMA)\b", unquoted, re.I)):
        raise ValueError("Seed SQL must be one idempotent INSERT without destructive operations")
    return sql


class SeedCheck:
    def __init__(self, output, paths):
        self.output, self.paths = output, paths

    @validation("database_check")
    def run(self, seeds):
        """Check schema and prerequisite SQL with SQLite before publishing each leaf's rows."""
        try:
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.create_function("seed_password_hash", 1, lambda _value: "scrypt$" + "0" * 32 + "$" + "0" * 128)
                connection.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY
                    if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH} else sqlite3.SQLITE_OK)
                connection.execute("PRAGMA foreign_keys = ON")
                for table in self.paths:
                    connection.executescript(read_source(self.output / f"backend/src/db/tables/{table}.sql"))
                # Keep the transaction open across all files, with the same FK deferral as the app.
                script = "BEGIN;\nPRAGMA defer_foreign_keys=ON;\n" + "\n".join(seeds.values()) + "\nCOMMIT;"
                connection.executescript(script)
        except sqlite3.Error as error:
            return {"returncode": 1, "output": str(error)}
        return {"returncode": 0, "output": "Prerequisites initialize successfully in SQLite"}


def implement_startup_data(arc_dir, schema, console, order):
    """Batch prerequisite generation by related tables; commit each validated leaf independently."""
    output = arc_dir.parent.resolve()
    if not order:
        ImplementationBatches(arc_dir, "04", console, phase="seed").register({}, {}, {}).publish()
        return {}
    insert_paths = {name: f"backend/src/db/seeds/{name}.sql" for name in order}
    for name, relative in insert_paths.items():
        if not (output / relative).is_file():
            save_text(output / relative, f"-- Prerequisite rows for {name}.\n")
    save_text(output / SEED_PATH, seed_source(order))
    checkpoint(output, stage="04", task="startup data loader", action="Publish per-table insertion files and loader",
        details={"insertion_order": order, "insert_files": insert_paths})
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    deps = table_dependencies(schema)
    values, signals, priorities = {}, {}, {}
    ranks = {name: index for index, name in enumerate(order)}
    for rid in tree.leaves:
        steps = [tree.steps[sid] for sid in tree.own_steps[rid]]
        evidence = prerequisite_evidence(tree.requirements[rid], steps)
        if not evidence:
            continue
        names = {field.split(".", 1)[0] for field in schema["requirements"].get(rid, [])}
        priorities[rid] = max((ranks.get(name, len(ranks)) for name in names), default=len(ranks))
        pending = list(names)
        while pending:
            for parent in deps[pending.pop()]:
                if parent not in names:
                    names.add(parent)
                    pending.append(parent)
        names.intersection_update(insert_paths)
        if not names:
            continue
        values[rid] = {"evidence": evidence, "tables": [name for name in order if name in names]}
        signals[rid] = names
    batches = ImplementationBatches(arc_dir, "04", console, phase="seed").register(
        {rid: values[rid] for rid in sorted(values, key=priorities.get)},
        {rid: [rid] for rid in values}, signals, ordered=True)
    checker = SeedCheck(output, order)
    model = TextModel(json_mode=False) if values else None

    def process(batch, entry):
        records = {rid: values[rid] for rid in batch.units}
        tables = {name for record in records.values() for name in record["tables"]}
        baseline = {name: read_source(output / path) for name, path in insert_paths.items()}
        request = batches.context(batch, {"prerequisites": records, "table_names": order,
            "tables": {name: schema["entities"][name] for name in sorted(tables)},
            "existing_rows": {name: baseline[name] for name in sorted(tables)}})
        # The seed agent sees only prerequisites; When/Then are not in the seed request.
        request.pop("requirement_evidence")
        check_request_size(request, len(batch.units))
        response = model.generate_json(SEED_INSTRUCTIONS + SEED_RESPONSE, request)
        if not isinstance(response, dict) or "requirements" not in response:
            raise ValueError("Seed output lacks requirement-attributed rows")
        response = response["requirements"]
        if not isinstance(response, dict) or set(response) != set(batch.units):
            raise ValueError("Seed output must attribute rows to exactly the active requirements")
        prepared, rejected = {}, {}
        for rid in batch.units:
            try:
                rows = []
                for row in response[rid]["rows"]:
                    sql = validate_seed_row(row, records[rid]["evidence"], records[rid]["tables"])
                    rows.append({"table": row["table"], "sql": sql, **row["evidence"]})
                prepared[rid] = rows
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                rejected[rid] = {"error": str(error)}

        def merged(current, entries):
            candidate = dict(current)
            for rid, rows in entries.items():
                for row in rows:
                    table, sql = row["table"], row["sql"]
                    if sql not in candidate[table]:
                        comment = re.sub(r"[\r\n]", " ", f"{rid} {row['source']}")
                        candidate[table] += f"\n-- Source: {comment}\n{sql}\n"
            return candidate

        def check(candidate):
            return checker.run(candidate) if candidate != baseline else {"returncode": 0}

        # Cyclic or interdependent prerequisites can succeed together even if
        # they cannot be committed leaf by leaf against the old database.
        combined = merged(baseline, prepared)
        whole = check(combined)
        if whole["returncode"] == 0:
            passed = {rid: {"rows": rows} for rid, rows in prepared.items()}
        else:
            combined, passed = dict(baseline), {}
            for rid, rows in prepared.items():
                candidate = merged(combined, {rid: rows})
                result = check(candidate)
                if result["returncode"]:
                    rejected[rid] = result
                else:
                    combined = candidate
                    passed[rid] = {"rows": rows}
        for name in combined:
            if combined[name] != baseline[name]:
                save_text(output / insert_paths[name], combined[name])
        require_any(passed, rejected)
        entry["rejected_checks"] = rejected
        return passed

    try:
        return batches.run(process)
    finally:
        if model is not None:
            model.client.close()


def verify_database_runtime(arc_dir, schema, console):
    """Execute the fixed build/initialization/startup checks without an agent repair loop."""
    output = arc_dir.parent.resolve()
    report = {"status": "CHECKING", "expected_tables": list(schema["entities"])}
    path = arc_dir / "db_checks.json"
    save_json(path, report)
    try:
        install_dependencies(output)
        result = DatabaseChecks(output, schema).run()
        report.update(status="GREEN" if result["returncode"] == 0 else "FAILED", checks=result)
        save_json(path, report)
        checkpoint(output, stage="04", task="database runtime", action="Execute fixed database initialization and startup checks",
            status=report["status"], details=result)
        if result["returncode"]:
            raise CheckFailure("Database initialization or startup failed", result)
        return report
    except Exception as error:
        report.update(status="FAILED", error=str(error))
        save_json(path, report)
        raise
