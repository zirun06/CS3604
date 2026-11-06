// Run with: node tests/test_sql_inserts.mjs <generated application workspace>
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { validateInserts } from '../infrastructure/tasks/validate_sql_inserts.mjs';

const require = createRequire(resolve(process.argv[2], 'package.json'));
const ts = require('typescript');
const Database = require('better-sqlite3');
const db = new Database(':memory:');
try {
  db.exec('CREATE TABLE posts (owner INTEGER, title TEXT, body TEXT, score INTEGER)');
  const text = `
    db.prepare('INSERT INTO posts (owner,title,body,score) VALUES (?,?,?,0)');
    db.prepare('INSERT INTO posts (owner,title,body,score) VALUES (?,?,0)');
    db.prepare('INSERT INTO posts (missing_column) VALUES (?)');
    db.prepare(dynamicSql);
    db.prepare('SELECT 1');
  `;
  const result = validateInserts(ts, db, text);
  assert.equal(result.checked, 3);
  assert.equal(result.errors.length, 2);
  assert.match(result.errors[0], /3 values for 4 columns/);
  assert.match(result.errors[1], /missing_column/);
  assert.equal(db.prepare('SELECT COUNT(*) AS count FROM posts').get().count, 0,
    'SQL validation must never insert application data');
  console.log('SQL checks passed: valid insert, column mismatch, unknown column, dynamic SQL, no writes.');
} finally { db.close(); }
