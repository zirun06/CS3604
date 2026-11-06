import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const workspace = resolve(process.argv[2]);
const require = createRequire(resolve(workspace, 'package.json'));
const ts = require('typescript');
const express = require('express');
const temporary = mkdtempSync(resolve(tmpdir(), 'arc-railway-source-'));
const target = resolve(temporary, 'fixture.tsx');
const script = fileURLToPath(new URL('../infrastructure/tasks/prepare_railway_source.mjs', import.meta.url));
function prepare(mode, text) {
  if (text !== undefined) writeFileSync(target, text);
  const result = spawnSync(process.execPath, [script, workspace, mode, target], {encoding: 'utf8'});
  assert.equal(result.status, 0, result.stderr);
  return readFileSync(target, 'utf8');
}
let server;
try {
  const backend = prepare('backend', `export function registerApis(app: any, db: any) {
    app.get('/roundtrip', (req: any, res: any) => res.json(req.cookies));
  }`);
  assert.equal(prepare('backend'), backend, 'Cookie middleware is idempotent');
  const js = ts.transpileModule(backend, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
  const module = {exports: {}};
  new Function('exports', 'module', js)(module.exports, module);
  const app = express(); module.exports.registerApis(app, null);
  server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  const response = await fetch('http://127.0.0.1:' + server.address().port + '/roundtrip',
    {headers: {cookie: 'sid=durable%3Dtoken; malformed=%GG; sid=second; __proto__=safe'}});
  const cookies = await response.json();
  assert.equal(cookies.sid, 'durable=token');
  assert.equal(cookies.malformed, '%GG');
  assert.equal(cookies.__proto__, 'safe');
  assert.equal(prepare('backend', 'export function registerApis(app: any, db: any) {}'),
    'export function registerApis(app: any, db: any) {}', 'No cookie reader, no middleware');
  const ui = prepare('frontend', `const App=()=> <><Field label="Nationality"><select><option>China</option></select></Field>
    <Field label={dynamicLabel}><input value={value}/></Field>
    <Field label="Keep"><select aria-label="Existing" /></Field>
    <td>{train.number}<div>{train.station}</div></td>
    <td><span>{train.number}</span></td>
    <button type="button" onClick={logout}>Sign Out</button>
    <button type="button" onClick={pay}>Pay</button></>`);
  assert.match(ui, /select aria-label="Nationality"/);
  assert.match(ui, /input aria-label=\{dynamicLabel\}/);
  assert.match(ui, /select aria-label="Existing"/);
  assert.match(ui, /<td><span>\{train.number\}<\/span>\{' '\}<div>/);
  assert.match(ui, /<a href="#"/);
  assert.match(ui, />Sign Out<\/a>/);
  assert.match(ui, /event.preventDefault\(\)/);
  assert.match(ui, /void \(logout as/);
  assert.match(ui, /<button type="button" onClick=\{pay\}>Pay<\/button>/);
  assert.equal(prepare('frontend'), ui, 'Control and identity corrections are idempotent');
  const syntax = ts.createSourceFile('fixture.tsx', ui, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  assert.equal(syntax.parseDiagnostics.length, 0);
  const table = prepare('frontend', `export function App(){const train={number:'G7',station:'Station'};return <table><tbody><tr><td><span>{train.number}</span><div>{train.station}</div></td></tr></tbody></table>}`);
  const tableJs = ts.transpileModule(table, {compilerOptions: {module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React}}).outputText;
  const rendered = {exports:{}};
  new Function('React', 'exports', 'module', tableJs)(require('react'), rendered.exports, rendered);
  const html = require('react-dom/server').renderToStaticMarkup(require('react').createElement(rendered.exports.App));
  assert.match(html.replace(/<[^>]+>/g, ''), /G7\s+Station/, 'Train identity retains a word boundary in cell textContent');
  console.log('Railway source checks passed: real cookie HTTP roundtrip, malformed/duplicate cookies, labelled controls, isolated identity, idempotence.');
} finally {
  if (server) {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
  // This is the unique temporary fixture directory created by this test.
  assert.equal(resolve(temporary).startsWith(resolve(tmpdir()) + (process.platform === 'win32' ? '\\' : '/')), true);
  assert.match(temporary.slice(resolve(tmpdir()).length), /arc-railway-source-/);
  rmSync(temporary, {recursive:true, force:true});
}
