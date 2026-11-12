// Inspect/replace bounded top-level React components, preserving route contracts.
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const workspace = resolve(process.argv[2]);
const ts = createRequire(resolve(workspace, 'package.json'))('typescript');
const sourceOption = process.argv.indexOf('--source');
const path = resolve(workspace, sourceOption < 0 ? 'frontend/src/App.tsx' : process.argv[sourceOption + 1]);
const source = readFileSync(path, 'utf8');
const parse = text => ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const file = parse(source);
function walk(node, callback) { callback(node); ts.forEachChild(node, child => walk(child, callback)); }
function attribute(opening, name) { return opening.attributes.properties.find(p => ts.isJsxAttribute(p) && p.name.getText(file) === name); }
function literal(attr) { return attr?.initializer && ts.isStringLiteral(attr.initializer) ? attr.initializer.text : null; }
function componentName(node) {
  if (ts.isFunctionDeclaration(node)) return node.name?.text;
  if (ts.isVariableStatement(node) && node.declarationList.declarations.length === 1) {
    const declaration = node.declarationList.declarations[0];
    if (ts.isIdentifier(declaration.name) && declaration.initializer &&
        (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer))) return declaration.name.text;
  }
}
function components(root) { return new Map(root.statements.map(n => [componentName(n), n]).filter(([name]) => name)); }
function jsxNames(node, root) {
  const names = new Set();
  walk(node, child => {
    if (ts.isJsxOpeningElement(child) || ts.isJsxSelfClosingElement(child)) {
      const name = child.tagName.getText(root);
      if (/^[A-Z]/.test(name)) names.add(name);
    }
  });
  return names;
}
function inventory(root) {
  const routes = [];
  walk(root, node => {
    if (!ts.isJsxSelfClosingElement(node) && !ts.isJsxOpeningElement(node)) return;
    const attrs = node.attributes.properties.filter(ts.isJsxAttribute);
    const element = attrs.find(a => a.name.getText(root) === 'element');
    const path = attrs.find(a => a.name.getText(root) === 'path');
    const index = attrs.some(a => a.name.getText(root) === 'index');
    if (!element || !path && !index) return;
    routes.push({path: path?.initializer?.getText(root) ?? '<index>',
      components: [...jsxNames(element, root)].sort(), element: element.getText(root)});
  });
  return routes;
}
const declarations = components(file);
let menuOwner = null;
let menu = null;
for (const [name, node] of declarations) walk(node, child => {
  if (ts.isJsxElement(child) && literal(attribute(child.openingElement, 'aria-label')) === 'Personal center menu') {
    if (menuOwner && menuOwner !== name) throw new Error('Ambiguous Personal center menu owners');
    menuOwner = name; menu = child.getText(file);
  }
});
const allowed = [...new Set(['App', menuOwner].filter(Boolean))];
const additions = ['ArcRailwayPersonalMenu', 'ArcRailwayPersonalLayout'];
const links = [];
walk(file, node => {
  if (!ts.isJsxElement(node)) return;
  const target = literal(attribute(node.openingElement, 'to')) ?? literal(attribute(node.openingElement, 'href'));
  const name = node.children.filter(ts.isJsxText).map(n => n.text.trim()).join(' ').trim();
  if (target && name) links.push({name, target, tag: node.openingElement.tagName.getText(file)});
});
const contract = {replaceable_components: Object.fromEntries(allowed.filter(n => declarations.has(n)).map(n => [n, declarations.get(n).getText(file)])),
  allowed_new_components: additions, menu_owner: menuOwner, menu_source: menu,
  routes: inventory(file), existing_links: links};

if (process.argv[3] === 'inspect') console.log(JSON.stringify(contract));
else if (process.argv[3] === 'apply') {
  const proposal = JSON.parse(readFileSync(resolve(process.argv[4]), 'utf8'));
  if (!proposal.components || Array.isArray(proposal.components) || typeof proposal.components !== 'object') throw new Error('Return components as an object');
  const edits = []; const appended = [];
  for (const [name, code] of Object.entries(proposal.components)) {
    if (![...allowed, ...additions].includes(name) || typeof code !== 'string') throw new Error('Component is outside the bounded layout scope: ' + name);
    const replacement = parse(code);
    if (replacement.parseDiagnostics.length || replacement.statements.length !== 1 || componentName(replacement.statements[0]) !== name)
      throw new Error('Each component must be one complete function/arrow declaration with its exact name: ' + name);
    if (declarations.has(name)) {
      if (!allowed.includes(name) && !additions.includes(name)) throw new Error('Unexpected existing declaration');
      const original = declarations.get(name);
      edits.push({start: original.getStart(file), end: original.end, code});
    } else appended.push(code);
  }
  if (!edits.length && !appended.length) throw new Error('No component changes supplied');
  let candidate = source;
  for (const edit of edits.sort((a,b) => b.start-a.start)) candidate = candidate.slice(0, edit.start)+edit.code+candidate.slice(edit.end);
  candidate += appended.length ? '\n'+appended.join('\n')+'\n' : '';
  const after = parse(candidate);
  if (after.parseDiagnostics.length) throw new Error('Replacement produced invalid TSX');
  const beforeRoutes = inventory(file), afterRoutes = inventory(after);
  if (JSON.stringify(beforeRoutes.map(r=>r.path)) !== JSON.stringify(afterRoutes.map(r=>r.path))) throw new Error('Existing route paths/order must remain unchanged');
  beforeRoutes.forEach((route,index) => {
    for (const name of route.components) if (!afterRoutes[index].components.includes(name))
      throw new Error(`Route ${route.path} lost its original view or protection component: ${name}`);
  });
  const newDeclarations = components(after);
  if (declarations.has('App')) for (const name of jsxNames(declarations.get('App'), file))
    if (!jsxNames(newDeclarations.get('App'), after).has(name)) throw new Error('App lost an original component/provider: '+name);
  writeFileSync(path, candidate);
  console.log(JSON.stringify({replaced: edits.length, added: appended.length, preserved_routes: beforeRoutes.length}));
} else throw new Error('Expected inspect or apply');
