"""Single-response SQL implementation through native edit_file calls."""

import json
from openai import OpenAIError

from infrastructure.shared.agent.agent import BaseAgent
from infrastructure.shared.models.text import ModelOutputTruncated, ModelRequestFailed, reasoning_arguments
from infrastructure.shared.agent.design_batches import check_request_size
from infrastructure.utils.presentation.model_io import record_tool_execution


SQL_INSTRUCTIONS = """Implement each entity in task.tables using data definition language (DDL).
Choose SQL syntax and physical types appropriate to the supplied technology stack.
Use edit_file/create for a missing output_path under backend/src/db/tables.
For existing SQL, use exact local edit_file/replace edits and preserve unrelated
definitions. Each entity owns one fixed SQL path. All required definitions and
referenced SQL are supplied. Use the exact output_path.

Define the table while preserving canonical entity and field names. Quote identifiers
according to the target database dialect. Implement supplied primary keys, nullability,
uniqueness, foreign-key references and database-enforceable value constraints.
Map logical field types to appropriate physical types for the target database.
Use explicit NOT NULL when nullable=false. Follow the target database's key-generation
capabilities and supplied schema evidence; application code supplies other generated
values. Do not invent defaults, normalization, cascades or uniqueness.

Use CHECK or other supported DDL constraints where appropriate. Respect the target
database's restrictions on constraint expressions, including JSON validation.
Describe application-only rules such as password hashing in comments instead of
inventing database checks. Keep rules that cannot be enforced by supported DDL in
application code.

Each file defines its own table, without extra tables, data mutations or application
startup code. Referenced tables provide target definitions and available SQL; a
missing implementation means that table has not been generated yet. Handle foreign
keys, self-references and cyclic dependencies according to the supplied dependency
plan and target database capabilities. The compiler owns ordered initialization.
Keep repeated initialization safe and preserve existing data, using conditional
table creation where supported.
"""

SEED_INSTRUCTIONS = '''Review the supplied requirements and propose only their explicit prerequisite rows.
Each table has one insertion file: backend/src/db/seeds/ENTITY.sql. The compiler has
created these files and a dependency-ordered seed.ts loader. Edit only the insertion
SQL files; do not put records or INSERT statements in seed.ts or the table DDL files.
The insertion-file mapping identifies the current tables. The canonical table list
names the available tables; their DDL is in backend/src/db/tables/ENTITY.sql.
All canonical table and insertion SQL contents are supplied.
Use only the supplied canonical tables and insertion SQL. The password helper contract is specified below;
there is no need to inspect the seed loader or other infrastructure.

Identify data that must EXIST BEFORE this requirement's When actions:
- System/domain data users cannot create through the application, such as train services,
  reference catalogues, built-in roles or already stocked books.
- Existing users, books, shelves and other domain records stated in Given or explicit
  seed/prerequisite sections. Include these even when another requirement implements
  their creation: login must be testable with a pre-existing account independently of
  registration, and reading/editing content must not depend on its creation workflow.
- Include the related parent rows and association rows needed to make these records valid.
Preserve exact names, credentials, contents, relationships and initial status supplied by
requirements. For omitted mandatory fields, choose minimal valid deterministic values.
Do not discard prerequisites merely because they occur in a scenario rather than a
sentence saying "system startup". Use the supplied complete requirement and its scenarios.
If a generic reference such as "an existing verified account" does not identify concrete
records, do not invent a separate account, password or object. The defining leaf requirement
will supply those records during this pass. Fill omitted mandatory fields only for records
whose identity is actually established by this requirement.

Do not pre-execute the current When/Then. A record created by this scenario's operation
must remain absent until that operation. Do not fabricate authenticated sessions, personal
history, favorites or drafts that the requirement explicitly establishes through login
or other UI actions. Browser/session state is not a database seed prerequisite.
Different scenarios may need different preconditions. Seed their distinct prerequisite
objects with the exact specified identities; scenario-specific absence, counts or mutable
states can still be arranged by isolated test fixtures. If constraints prevent coexistence,
keep the shared baseline valid and leave conflicting scenario variations to test setup.
Return an empty rows array when no prerequisite rows need adding.

Inspect existing insertion SQL and propose only missing rows. The compiler appends them without editing previous records. A table's insertion file inserts only into that table; put its parents
and associations in their own files. SELECT subqueries may resolve existing foreign keys.
Use stable identifiers/business keys and SQLite INSERT ... SELECT ... WHERE NOT EXISTS,
or a targeted ON CONFLICT ... DO NOTHING. Avoid INSERT OR IGNORE, which hides invalid data.
Repeated startup must not duplicate records, overwrite user edits or reset credentials.
Do not DELETE, DROP, REPLACE, change table definitions, disable constraints or suppress errors.
The loader executes these files in table-dependency order inside the initialization
transaction; foreign-key checks are deferred until all seed files have executed.

For password-hash columns, use the SQL function seed_password_hash('required password').
It returns scrypt$saltHex$digestHex using a 16-byte salt and a 64-byte digest, compatible
with the documented test credential format. Never store a plaintext password in a hash
column or invent a digest. The password function is called by SQL only for missing rows.
Escape SQL literals correctly; use 0/1 booleans and valid JSON text when required.
The compiler performs real initialization/build checks after this pass.
'''


class DatabaseImplementationAgent(BaseAgent):
    """Generate a complete group of table files through scoped native edits."""

    def run(self, input: dict, files) -> dict:
        task = {**input, "technology_stack": "React + Express + SQLite (better-sqlite3)",
            "directory_structure": files.describe(), "files": files.snapshot()}
        check_request_size(task, len(task["units"]))
        messages = [{"role": "system", "content": SQL_INSTRUCTIONS +
            "\nReturn all required native edit_file calls in one response, one path per table."},
            {"role": "user", "content": json.dumps(task, ensure_ascii=False)}]
        self.messages = messages
        try:
            response = self.model._request(model=self.model.name, messages=messages,
                tools=files.definitions(["edit_file"]), tool_choice="required",
                **reasoning_arguments(self.model.name, self.model.reasoning))
        except OpenAIError as error:
            raise ModelRequestFailed(f"Database model request failed: {error}") from error
        if not response.choices:
            raise ValueError("Database agent returned no choices")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ModelOutputTruncated("Database SQL response was truncated")
        message = choice.message
        messages.append(message.model_dump(exclude_none=True))
        if getattr(message, "refusal", None):
            raise ValueError(f"Database model refused the task: {message.refusal}")
        calls = message.tool_calls or []
        if not calls:
            raise ValueError("A table batch must generate SQL through edit_file")
        try:
            results = files.execute(calls)
        except (ValueError, OSError) as error:
            for call in calls:
                record_tool_execution(call.model_dump(exclude_none=True),
                    {"error": str(error), "status": "BATCH_ROLLED_BACK"}, logger=self.logger)
            raise
        messages.extend(results)
        for call, result in zip(calls, results):
            record_tool_execution(call.model_dump(exclude_none=True), json.loads(result["content"]), logger=self.logger)
        return {"files": sorted(files.changed_paths)}
