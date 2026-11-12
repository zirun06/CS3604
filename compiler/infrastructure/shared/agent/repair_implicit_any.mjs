// Annotate only parameters identified by the TypeScript compiler in generated code.
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

const [workspace, encoded] = process.argv.slice(2);
const require = createRequire(resolve(workspace, 'package.json'));
const ts = require('typescript');
let changed = 0;

for (const [relative, locations] of Object.entries(JSON.parse(encoded))) {
  const path = resolve(workspace, relative);
  const source = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true);
  if (source.parseDiagnostics.length) continue;
  const offsets = new Set();
  for (const [line, column] of locations) {
    const lines = source.getLineStarts();
    if (line < 1 || line > lines.length || column < 1) continue;
    const position = lines[line - 1] + column - 1;
    if (position < (lines[line] ?? source.text.length)) offsets.add(position);
  }
  const edits = [];
  function visit(node) {
    if (ts.isParameter(node) && ts.isIdentifier(node.name) && !node.type &&
        offsets.has(node.name.getStart(source))) {
      const fn = node.parent;
      const needsParens = ts.isArrowFunction(fn) &&
        !fn.getChildren(source).some(child => child.kind === ts.SyntaxKind.OpenParenToken);
      const start = node.name.getStart(source);
      const end = node.name.getEnd();
      const optionalEnd = node.questionToken?.getEnd() ?? end;
      // At this boundary TypeScript already infers any. Make that explicit
      // without changing runtime behavior or disabling strict mode.
      edits.push(needsParens
        ? [start, end, `(${node.name.getText(source)}: any)`]
        : [optionalEnd, optionalEnd, ': any']);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  if (!edits.length) continue;
  let content = source.text;
  for (const [start, end, replacement] of edits.sort((a, b) => b[0] - a[0])) {
    content = content.slice(0, start) + replacement + content.slice(end);
  }
  writeFileSync(path, content, 'utf8');
  changed += edits.length;
}
console.log(changed);
