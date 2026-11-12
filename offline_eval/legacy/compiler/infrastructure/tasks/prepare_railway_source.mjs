// Railway-only source corrections for missing cookie parsing and field/row semantics.
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const workspace = resolve(process.argv[2]);
const ts = createRequire(resolve(workspace, 'package.json'))('typescript');
const mode = process.argv[3];
const path = resolve(workspace, process.argv[4] || (mode === 'backend' ? 'backend/src/api/register.ts' : 'frontend/src/App.tsx'));
let source = readFileSync(path, 'utf8');
const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true,
  mode === 'backend' ? ts.ScriptKind.TS : ts.ScriptKind.TSX);
const edits = [];
function insert(position, text) { edits.push({ start: position, end: position, text }); }
function replace(node, text) { edits.push({ start: node.getStart(file), end: node.end, text }); }
function attribute(node, name) { return node.attributes.properties.find(p => ts.isJsxAttribute(p) && p.name.getText(file) === name); }

if (mode === 'backend') {
  let readsCookies = false;
  function inspect(node) {
    if (ts.isPropertyAccessExpression(node) && node.name.text === 'cookies') readsCookies = true;
    if (ts.isElementAccessExpression(node) && ts.isStringLiteral(node.argumentExpression) && node.argumentExpression.text === 'cookies') readsCookies = true;
    ts.forEachChild(node, inspect);
  }
  inspect(file);
  if (readsCookies && !source.includes('// ARC_RAILWAY_COOKIE_BOOTSTRAP')) {
    const register = file.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === 'registerApis' && n.body);
    if (!register || !register.parameters[0]) throw new Error('Expected registerApis(app, db) to install railway cookie middleware');
    const app = register.parameters[0].name.getText(file);
    insert(register.body.getStart(file) + 1, `
  // ARC_RAILWAY_COOKIE_BOOTSTRAP: the shared template has no cookie-parser middleware.
  ${app}.use((request, _response, next) => {
    const jar: Record<string, string> = {};
    for (const pair of (request.headers.cookie || '').split(';')) {
      const separator = pair.indexOf('=');
      if (separator < 1) continue;
      const name = pair.slice(0, separator).trim();
      const raw = pair.slice(separator + 1).trim();
      if (Object.prototype.hasOwnProperty.call(jar, name)) continue;
      try { Object.defineProperty(jar, name, {value: decodeURIComponent(raw), enumerable: true}); }
      catch { Object.defineProperty(jar, name, {value: raw, enumerable: true}); }
    }
    request.cookies = Object.assign(Object.create(null), jar, request.cookies || {});
    next();
  });
`);
  }
} else if (mode === 'frontend') {
  function visit(node) {
    if (ts.isJsxElement(node)) {
      const opening = node.openingElement;
      const click = attribute(opening, 'onClick');
      const explicitName = attribute(opening, 'aria-label');
      const textName = node.children.filter(ts.isJsxText).map(n => n.text.trim()).join(' ');
      if (opening.tagName.getText(file) === 'button' &&
          (textName === 'Sign Out' || explicitName?.initializer && ts.isStringLiteral(explicitName.initializer) && explicitName.initializer.text === 'Sign Out') &&
          click?.initializer && ts.isJsxExpression(click.initializer) && click.initializer.expression) {
        replace(opening.tagName, 'a'); replace(node.closingElement.tagName, 'a');
        if (!attribute(opening, 'href')) insert(opening.tagName.end, ' href="#"');
        const type = attribute(opening, 'type'); if (type) replace(type, '');
        const handler = click.initializer.expression.getText(file);
        replace(click.initializer, `{(event) => { event.preventDefault(); void (${handler} as (...args: any[]) => unknown)(event); }}`);
      }
      const label = attribute(node.openingElement, 'label');
      // Components with an explicit label prop express the intended name, whereas
      // a wrapping native label includes all SELECT option text in that name.
      if (label?.initializer && (ts.isStringLiteral(label.initializer) ||
          ts.isJsxExpression(label.initializer) && label.initializer.expression)) {
        const controls = node.children.filter(n => ts.isJsxElement(n) &&
          ['select', 'input', 'textarea'].includes(n.openingElement.tagName.getText(file)) ||
          ts.isJsxSelfClosingElement(n) && ['input', 'select', 'textarea'].includes(n.tagName.getText(file)));
        if (controls.length === 1) {
          const opening = ts.isJsxElement(controls[0]) ? controls[0].openingElement : controls[0];
          if (!attribute(opening, 'aria-label') && !attribute(opening, 'aria-labelledby'))
            insert(opening.tagName.end, ' aria-label=' + label.initializer.getText(file));
        }
      }
      // Preserve each identity as independently identifiable visible text when
      // the same table cell also contains station/metadata child elements.
      if (node.openingElement.tagName.getText(file) === 'td' && node.children.some(n => ts.isJsxElement(n))) {
        for (const child of node.children) {
          if (ts.isJsxExpression(child) && child.expression &&
              (ts.isIdentifier(child.expression) || ts.isPropertyAccessExpression(child.expression))) {
            insert(child.getStart(file), '<span>'); insert(child.end, "</span>{' '}");
          }
        }
        for (let index = 0; index < node.children.length; index++) {
          const child = node.children[index];
          if (!ts.isJsxElement(child) || child.openingElement.tagName.getText(file) !== 'span') continue;
          const following = node.children.slice(index + 1).filter(n => !ts.isJsxText(n) || n.text.trim());
          if (following.length && ts.isJsxElement(following[0])) insert(child.end, "{' '}");
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
} else throw new Error('Expected backend or frontend mode');

for (const edit of edits.sort((a, b) => b.start - a.start)) source = source.slice(0, edit.start) + edit.text + source.slice(edit.end);
if (edits.length) writeFileSync(path, source);
console.log(JSON.stringify({ mode, changes: edits.length }));
