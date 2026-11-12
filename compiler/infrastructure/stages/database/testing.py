"""Execute the application's SQLite initialization and compiled server startup."""

import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic

from infrastructure.utils.budget import BudgetExhausted
from infrastructure.utils.presentation.events import validation_event
from infrastructure.utils.processes import capture_process, npm_command


PROBE_SOURCE = r'''
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { createServer } from "node:net";
import { setTimeout as delay } from "node:timers/promises";
const plan = JSON.parse(readFileSync(process.argv[2], "utf8"));
const Database = createRequire(join(process.cwd(), "package.json"))("better-sqlite3");
const quote = name => '"' + name.replaceAll('"', '""') + '"';
let phase = "setup", server;
const completed = [];
const validations = [];
function record(type, started) {
  validations.push({ type, phase, seconds: (performance.now() - started) / 1000,
    result: completed.includes(phase) ? "passed" : "failed" });
}
function inspect(filename, marker = false) {
  if (!existsSync(filename)) throw new Error("Initialization did not create DATABASE_URL: " + filename);
  const db = new Database(filename);
  try {
    for (const [table, fields] of Object.entries(plan.tables)) {
      const columns = db.prepare(`PRAGMA table_info(${quote(table)})`).all().map(row => row.name);
      if (!columns.length) throw new Error("Missing table: " + table);
      for (const field of fields) if (!columns.includes(field)) throw new Error("Missing column: " + table + "." + field);
    }
    if (db.prepare("PRAGMA foreign_key_check").all().length) throw new Error("Foreign-key validation failed");
    if (marker && db.prepare('SELECT value FROM "__arc_startup_probe"').get()?.value !== "preserve")
      throw new Error("Initialization changed existing data");
  } finally { db.close(); }
}
function tableRows(filename) {
  const db = new Database(filename, { readonly: true });
  db.defaultSafeIntegers(true);
  try {
    return Object.keys(plan.tables).map(table => db.prepare("SELECT * FROM " + quote(table)).all()
      .map(row => JSON.stringify(row, (_key, value) =>
        typeof value === "bigint" ? { integer: value.toString() } : value)).sort());
  } finally { db.close(); }
}
function verifyPersistence(filename, expected, phaseName) {
  phase = phaseName;
  const started = performance.now();
  try {
    inspect(filename, true);
    if (JSON.stringify(tableRows(filename)) !== JSON.stringify(expected))
      throw new Error("File database business rows changed after reopening: " + phaseName);
    completed.push(phase);
  } finally { record("persistence_check", started); }
}
function seedMarker(filename) {
  const db = new Database(filename);
  try { db.exec('CREATE TABLE "__arc_startup_probe" (value TEXT); INSERT INTO "__arc_startup_probe" VALUES (\'preserve\');'); }
  finally { db.close(); }
}
function setup(command, filename, marker = false) {
  const started = performance.now();
  try {
    const result = spawnSync(command[0], command.slice(1), { cwd: process.cwd(),
      env: { ...process.env, DATABASE_URL: filename }, encoding: "utf8", timeout: 60000 });
    if (result.error || result.status !== 0)
      throw new Error([result.error?.message, result.stdout, result.stderr].filter(Boolean).join("\n"));
    inspect(filename, marker);
    completed.push(phase);
  } finally { record("database_check", started); }
}
async function stopServer() {
  if (!server) return;
  const child = server;
  server = undefined;
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  for (let i = 0; i < 30 && child.exitCode === null && child.signalCode === null; i++) await delay(100);
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
    await new Promise(resolve => child.once("exit", resolve));
  }
}
async function startup(filename, marker = false) {
  const started = performance.now();
  let output = "", spawnError;
  const listener = createServer();
  await new Promise((resolve, reject) => { listener.once("error", reject); listener.listen(0, "127.0.0.1", resolve); });
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  server = spawn(process.execPath, ["backend/dist/server.js"], {
    cwd: process.cwd(), env: { ...process.env, DATABASE_URL: filename, PORT: String(port) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const child = server;
  child.stdout.on("data", data => { output = (output + data).slice(-24000); });
  child.stderr.on("data", data => { output = (output + data).slice(-24000); });
  child.on("error", error => { spawnError = error; });
  try {
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      if (spawnError) throw spawnError;
      if (child.exitCode !== null || child.signalCode !== null) throw new Error("Server exited before readiness:\n" + output);
      if (port) {
        const response = await fetch(`http://127.0.0.1:${port}/api/health`, { signal: AbortSignal.timeout(1000) }).catch(() => null);
        if (response?.ok) {
          inspect(filename, marker);
          completed.push(phase);
          return;
        }
      }
      await delay(100);
    }
    throw new Error("Server did not become ready:\n" + output);
  } finally {
    try { await stopServer(); }
    finally { record("startup_check", started); }
  }
}
try {
  const database = join(plan.directory, "setup.db");
  phase = "fresh initialization"; setup(plan.setup, database);
  const initialRows = tableRows(database);
  seedMarker(database);
  phase = "repeated initialization"; setup(plan.setup, database);
  verifyPersistence(database, initialRows, "idempotent file database");
  const first = Object.keys(plan.tables)[0];
  if (first) {
    const db = new Database(database);
    try { db.pragma("foreign_keys = OFF"); db.exec(`DROP TABLE ${quote(first)}`); }
    finally { db.close(); }
    phase = "missing-table recovery"; setup(plan.setup, database, true);
  }
  phase = "compiled initialization"; setup([process.execPath, "backend/dist/db/setup.js"], database, true);
  const startupDatabase = join(plan.directory, "startup.db");
  phase = "fresh server startup"; await startup(startupDatabase);
  const serverRows = tableRows(startupDatabase);
  seedMarker(startupDatabase);
  phase = "server restart"; await startup(startupDatabase);
  verifyPersistence(startupDatabase, serverRows, "file database after server restart");
  phase = "output database initialization"; setup(plan.setup, plan.database);
  console.log(JSON.stringify({ status: "GREEN", completed, validations, database_path: plan.database }));
} catch (error) {
  console.error(JSON.stringify({ phase, completed, validations, error: error.stack ?? String(error) }));
  process.exitCode = 1;
} finally { await stopServer(); }
'''


class DatabaseChecks:
    """Probe disposable databases before initializing the output's persistent database."""

    def __init__(self, output, schema):
        self.output = Path(output).resolve()
        self.schema = schema
        self.node = shutil.which("node")
        if not self.node:
            raise ValueError("Node.js is required for database initialization checks")

    def run(self):
        started = monotonic()
        build = None
        try:
            try:
                build = capture_process([*npm_command(), "run", "build", "--workspace", "@arc/backend"],
                    cwd=self.output, timeout=600)
            except BudgetExhausted as error:
                validation_event("build", monotonic() - started,
                    "failed" if getattr(error, "process_started", False) else "not_run")
                for kind in ("database_check", "startup_check", "persistence_check"):
                    validation_event(kind, 0, "not_run", reason=str(error))
                raise
            except Exception:
                validation_event("build", monotonic() - started, "failed")
                raise
            validation_event("build", monotonic() - started, "failed" if build["returncode"] else "passed")
            if build["returncode"]:
                for kind in ("database_check", "startup_check", "persistence_check"):
                    validation_event(kind, 0, "not_run", reason="backend build failed")
                return {**build, "phase": "backend build"}
            with TemporaryDirectory(prefix="arc-db-check-") as temporary:
                plan = {"directory": temporary, "database": str(self.output / "backend/data/app.db"),
                    "tables": {name: list(entity["fields"]) for name, entity in self.schema["entities"].items()},
                    "setup": [*npm_command(), "run", "db:init", "--workspace", "@arc/backend"]}
                runner = Path(temporary) / "check-database.mjs"
                arguments = Path(temporary) / "plan.json"
                runner.write_text(PROBE_SOURCE, encoding="utf-8")
                arguments.write_text(json.dumps(plan), encoding="utf-8")
                probe_started = monotonic()
                try:
                    result = capture_process([self.node, str(runner), str(arguments)],
                        cwd=self.output, timeout=600)
                except BudgetExhausted as error:
                    validation_event("database_check", monotonic() - probe_started,
                        "failed" if getattr(error, "process_started", False) else "not_run", reason=str(error))
                    raise
            observed = set()
            for stream in ("stderr", "stdout"):
                for line in result.get(stream, "").splitlines():
                    try:
                        detail = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(detail, dict):
                        for check in detail.get("validations", []):
                            kind = check.get("type")
                            if kind in {"database_check", "startup_check", "persistence_check"} and check.get("result") in {"passed", "failed"}:
                                observed.add(kind)
                                validation_event(kind, check["seconds"], check["result"], check_phase=check["phase"])
                        result.update({key: detail[key] for key in ("phase", "completed", "error", "status", "database_path") if key in detail})
            if "database_check" not in observed:
                validation_event("database_check", monotonic() - probe_started,
                    "failed" if result["returncode"] else "passed")
            if "startup_check" not in observed:
                validation_event("startup_check", 0, "not_run", reason="startup was not reached")
            if "persistence_check" not in observed:
                validation_event("persistence_check", 0, "not_run", reason="file database was not reopened")
            return result
        except subprocess.TimeoutExpired as error:
            return {"returncode": 1, "phase": "database initialization", "output": str(error), "error": "Database checks timed out"}
