// Associate visible metric labels and a feed's existing controls with its scope.
// No values, event handlers, ownership checks or layout elements are changed.
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

const [workspace, relative = 'frontend/src/App.tsx'] = process.argv.slice(2);
const require = createRequire(resolve(workspace, 'package.json'));
const ts = require('typescript');
const path = resolve(workspace, relative);
const text = readFileSync(path, 'utf8');
const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = new Set(['Score', 'Answer count', 'View count', 'Reputation',
  'Question count', 'Title character count', 'Comment votes', 'Asked', 'Modified']);
const edits = [];

function attribute(opening, name) {
  return opening.attributes.properties.find(a => ts.isJsxAttribute(a) && a.name.text === name);
}

function labelExpression(node) {
  if (!ts.isJsxElement(node)) return null;
  const pieces = [];
  for (const child of node.children) {
    if (ts.isJsxText(child)) pieces.push(child.text.replace(/\s+/g, ' '));
    else if (ts.isJsxExpression(child) && child.expression) {
      if (ts.isStringLiteral(child.expression)) pieces.push(child.expression.text);
      else pieces.push({ expression: child.expression.getText(source) });
    } else return null;
  }
  const fixed = pieces.filter(p => typeof p === 'string').join('').trim();
  const dynamic = pieces.filter(p => typeof p !== 'string');
  if (!dynamic.length && names.has(fixed)) return JSON.stringify(fixed);
  if (fixed === 'Earn count' && dynamic.length === 1 &&
      typeof pieces[0] === 'string' && pieces[0].trim() === 'Earn count') {
    return '"Earn count " + (' + dynamic[0].expression + ')';
  }
  return null;
}

function visit(node) {
  if (ts.isJsxElement(node) || ts.isJsxFragment(node)) {
    let previous = null;
    for (const child of node.children) {
      if (ts.isJsxText(child) && !child.text.trim()) continue;
      if (ts.isJsxExpression(child) && !child.expression) continue;
      if (ts.isJsxElement(child)) {
        const opening = child.openingElement;
        const role = attribute(opening, 'role');
        if (role?.initializer && ts.isStringLiteral(role.initializer) &&
            role.initializer.text === 'status' && !attribute(opening, 'aria-label') &&
            !attribute(opening, 'aria-labelledby') && previous) {
          const expression = labelExpression(previous);
          if (expression) edits.push([opening.getEnd() - 1, opening.getEnd() - 1,
                                      ' aria-label={' + expression + '}']);
        }
      }
      previous = child;
    }
  }
  ts.forEachChild(node, visit);
}

// Leave syntax errors for the normal build diagnostics and repair loop.
if (!source.parseDiagnostics.length) visit(source);
const statusCount = edits.length;
const feeds = [];
const controls = [];
function value(a) { return a?.initializer && ts.isStringLiteral(a.initializer) ? a.initializer.text : null; }
function collect(node) {
  if (ts.isJsxElement(node)) {
    const opening = node.openingElement;
    if (value(attribute(opening, 'role')) === 'region' &&
        value(attribute(opening, 'aria-label')) === 'Question feed' &&
        !attribute(opening, 'aria-labelledby') &&
        !opening.attributes.properties.some(ts.isJsxSpreadAttribute)) feeds.push(node);
    if (['button', 'a', 'Link'].includes(opening.tagName.getText(source))) {
      const text = node.children.filter(ts.isJsxText).map(child => child.text).join('').replace(/\s+/g, ' ').trim();
      if (text === 'Ask Question') controls.push(node);
    }
  }
  ts.forEachChild(node, collect);
}
function contains(parent, child) { return child.pos >= parent.pos && child.end <= parent.end; }
function globalLandmark(node) {
  if (ts.isJsxElement(node) && ['main', 'header', 'nav', 'aside', 'footer'].includes(node.openingElement.tagName.getText(source))) return true;
  return !!ts.forEachChild(node, globalLandmark);
}
let feedCount = 0;
if (!source.parseDiagnostics.length) collect(source);
for (const feed of feeds) {
  if (controls.some(control => contains(feed, control))) continue;
  for (let parent = feed.parent; parent; parent = parent.parent) {
    if (ts.isFunctionDeclaration(parent) || ts.isArrowFunction(parent) ||
        ts.isFunctionExpression(parent) || ts.isMethodDeclaration(parent)) break;
    if (!ts.isJsxElement(parent)) continue;
    const opening = parent.openingElement;
    if (globalLandmark(parent)) break;
    if (attribute(opening, 'role') || attribute(opening, 'aria-label') || attribute(opening, 'aria-labelledby')) break;
    if (opening.attributes.properties.some(ts.isJsxSpreadAttribute)) break;
    if (feeds.filter(other => contains(parent, other)).length !== 1) break;
    if (!['div', 'section', 'article'].includes(opening.tagName.getText(source))) continue;
    if (!controls.some(control => contains(parent, control))) continue;
    const role = attribute(feed.openingElement, 'role');
    const label = attribute(feed.openingElement, 'aria-label');
    edits.push([role.getStart(source), role.getEnd(), '']);
    edits.push([label.getStart(source), label.getEnd(), '']);
    edits.push([opening.getEnd() - 1, opening.getEnd() - 1,
                ' ' + role.getText(source) + ' ' + label.getText(source)]);
    feedCount++;
    break;
  }
}
let updated = text;
for (const [offset, end, addition] of edits.sort((a, b) => b[0] - a[0])) {
  updated = updated.slice(0, offset) + addition + updated.slice(end);
}
if (edits.length) writeFileSync(path, updated, 'utf8');
process.stdout.write(JSON.stringify({ associated_status_labels: statusCount, associated_feed_regions: feedCount }) + '\n');
