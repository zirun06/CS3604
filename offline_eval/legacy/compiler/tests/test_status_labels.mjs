// Run with: node tests/test_status_labels.mjs <generated application workspace>
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, existsSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const workspace = resolve(process.argv[2]);
const script = fileURLToPath(new URL('../infrastructure/tasks/associate_status_labels.mjs', import.meta.url));
const temporary = mkdtempSync(resolve(tmpdir(), 'arc-status-labels-'));
try {
  const file = resolve(temporary, 'fixture.tsx');
  const original = `const View = () => <>
    <div><span>Score</span><span role="status">{score}</span></div>
    <div><span>Reputation</span><span role="status" aria-label="Existing name">{reputation}</span></div>
    <div><span>Question count</span><span role="status" aria-labelledby="count-label">{count}</span></div>
    <div><span>Earn count {badge.name}</span><span role="status">{badge.count}</span></div>
    <div><span>Unrelated title</span><span role="status">{message}</span></div>
  </>`;
  writeFileSync(file, original);
  function run() {
    const result = spawnSync(process.execPath, [script, workspace, file], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout).associated_status_labels;
  }
  assert.equal(run(), 2);
  const updated = readFileSync(file, 'utf8');
  assert.match(updated, /role="status" aria-label=\{"Score"\}>\{score\}/);
  assert.match(updated, /aria-label=\{"Earn count " \+ \(badge.name\)\}>\{badge.count\}/);
  assert.ok(updated.includes('aria-label="Existing name">{reputation}'));
  assert.ok(updated.includes('aria-labelledby="count-label">{count}'));
  assert.ok(updated.includes('<span>Unrelated title</span><span role="status">{message}</span>'));
  assert.equal(run(), 0, 'A second pass must leave existing names alone');
  assert.equal(readFileSync(file, 'utf8'), updated);
  writeFileSync(file, 'const View = () => <div><span>Score</span><span role="status">{score}');
  assert.equal(run(), 0, 'Syntax errors remain owned by the build repair stage');
  console.log('Status association checks passed: labels, dynamic labels, existing names, unrelated text, idempotence, syntax errors.');
} finally {
  const file = resolve(temporary, 'fixture.tsx');
  if (existsSync(file)) unlinkSync(file);
  rmdirSync(temporary);
}
