"""Real SQLite/startup failures must be repaired by the database-owning task."""
from tool_fixtures import propose_files

from contextlib import redirect_stdout
from importlib import import_module
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from infrastructure.shared.agent.tasks import StageIncomplete
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.shared.agent.tools import FileTools
from infrastructure.stages.database.implementation import verify_database_runtime
from infrastructure.stages.database.runtime import initializer_source
from infrastructure.stages.database.testing import DatabaseChecks
from infrastructure.utils.files import save_json, save_text


SQL = 'CREATE TABLE IF NOT EXISTS "Note" ("id" INTEGER PRIMARY KEY, "tags" TEXT NOT NULL CHECK(json_valid("tags") AND json_type("tags") = \'array\'));'
BAD_SQL = 'CREATE TABLE IF NOT EXISTS "Note" ("id" INTEGER PRIMARY KEY, "tags" TEXT CHECK(NOT EXISTS (SELECT 1 FROM json_each("tags"))));'


def schema():
    def field(kind, primary=False):
        return {'description': 'Persistent value', 'type': kind, 'nullable': False,
            'primary_key': primary, 'unique': False, 'references': None, 'constraints': []}
    return {'entities': {'Note': {'description': 'Saved notes', 'fields': {
        'id': field('integer', True), 'tags': field('json')}}}, 'requirements': {}}


def prepare(output, sql=SQL):
    initialize_project(output)
    arc = output / '.arc'
    save_json(arc / 'requirements.json', {'id': 'ROOT'})
    save_json(arc / 'db_schema.json', schema())
    save_text(output / 'backend/src/db/tables/Note.sql', sql)
    save_text(output / 'backend/src/db/initialize.ts', initializer_source({'Note': {'path': 'Note.sql'}}))
    return arc


class RealDatabaseRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modules = Path(os.environ.get('ARC_DB_TEST_NODE_MODULES', 'node_modules')).resolve()
        if not all((modules / name).exists() for name in ('better-sqlite3', 'tsx', 'typescript', 'express')):
            raise unittest.SkipTest('Set ARC_DB_TEST_NODE_MODULES to installed generated-app dependencies')
        cls.modules = modules

    def workspace(self, directory, sql=SQL):
        output = Path(directory)
        arc = prepare(output, sql)
        (output / 'node_modules').symlink_to(self.modules, target_is_directory=True)
        return output, arc

    def test_real_initialization_repeat_missing_table_and_compiled_server_restart(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            output, arc = self.workspace(directory)
            # Existing application data must survive the successful output initialization.
            first = DatabaseChecks(output, schema()).run()
            self.assertEqual(first['returncode'], 0, first)
            self.assertEqual(first['completed'], ['fresh initialization', 'repeated initialization',
                'missing-table recovery', 'compiled initialization', 'fresh server startup',
                'server restart', 'output database initialization'])
            self.assertTrue((output / 'backend/data/app.db').is_file())
            script = "const D=require('better-sqlite3');const d=new D('backend/data/app.db');d.prepare('INSERT INTO Note(id,tags) VALUES(1,?)').run('[\"saved\"]');d.close();"
            from infrastructure.utils.processes import capture_process
            seeded = capture_process(['node', '-e', script], cwd=output, timeout=30)
            self.assertEqual(seeded['returncode'], 0, seeded)
            result = DatabaseChecks(output, schema()).run()
            self.assertEqual(result['returncode'], 0, result)
            observed = capture_process(['node', '-e', "const D=require('better-sqlite3');const d=new D('backend/data/app.db');console.log(d.prepare('SELECT tags FROM Note WHERE id=1').get().tags);d.close();"], cwd=output, timeout=30)
            self.assertEqual(observed['stdout'].strip(), '["saved"]')
