// Prepare constant INSERT statements against the initialized in-memory schema.
// Preparing checks SQL shape and column names without executing a write.
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export function validateInserts(ts, db, text, filename = 'backend/src/api/register.ts') {
  const source = ts.createSourceFile(filename, text, ts.ScriptTarget.Latest, true);
  const errors = [];
  let checked = 0;
  if (source.parseDiagnostics.length) return { checked, errors };
  function visit(node) {
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) &&
        node.expression.name.text === 'prepare' && node.arguments.length) {
      const literal = node.arguments[0];
      if ((ts.isStringLiteral(literal) || ts.isNoSubstitutionTemplateLiteral(literal)) &&
          /^\s*INSERT\b/i.test(literal.text)) {
        checked++;
        try { db.prepare(literal.text); }
        catch (error) {
          const { line } = source.getLineAndCharacterOfPosition(literal.getStart(source));
          errors.push(`${filename}:${line + 1}: ${error.message}\nSQL: ${literal.text}`);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return { checked, errors };
}

async function main(workspace) {
  const require = createRequire(resolve(workspace, 'package.json'));
  const ts = require('typescript');
  const load = relative => import(pathToFileURL(resolve(workspace, relative)).href);
  const { createApp } = await load('backend/dist/app.js');
  const { createDatabaseClient } = await load('backend/dist/db/client.js');
  const { initializeDatabase } = await load('backend/dist/db/initialize.js');
  const db = createDatabaseClient(':memory:');
  try {
    initializeDatabase(db);
    createApp(db);
    const text = readFileSync(resolve(workspace, 'backend/src/api/register.ts'), 'utf8');
    const result = validateInserts(ts, db, text);
    if (result.errors.length) throw new Error(result.errors.join('\n\n'));
    console.log(JSON.stringify({ validated_constant_inserts: result.checked }));
  } finally { db.close(); }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  main(resolve(process.argv[2])).catch(error => { console.error(error.message); process.exitCode = 1; });
}
