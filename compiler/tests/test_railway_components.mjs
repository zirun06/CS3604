import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const workspace = resolve(process.argv[2]);
const folder = mkdtempSync(resolve(tmpdir(), 'arc-railway-components-'));
const file = resolve(folder, 'App.tsx'), proposal = resolve(folder, 'proposal.json');
const script = fileURLToPath(new URL('../infrastructure/tasks/railway_components.mjs', import.meta.url));
const initial = `import {BrowserRouter,Routes,Route,Link} from 'react-router-dom';
function Header(){return <header>Header</header>}
function Protected({children}:any){return children}
function Orders(){return <div>Orders</div>}
function Center(){return <nav aria-label="Personal center menu"><Link to="/personal/orders">Order center</Link></nav>}
export function App(){return <BrowserRouter><Header/><Routes><Route path="/personal" element={<Protected><Center/></Protected>}/><Route path="/personal/orders" element={<Protected><Orders/></Protected>}/></Routes></BrowserRouter>}
const protectedBusinessLogic = 'must remain byte-identical';
`;
const validApp = `export function App(){return <BrowserRouter><Header/><Routes><Route path="/personal" element={<Protected><ArcRailwayPersonalLayout><Center/></ArcRailwayPersonalLayout></Protected>}/><Route path="/personal/orders" element={<Protected><ArcRailwayPersonalLayout><Orders/></ArcRailwayPersonalLayout></Protected>}/></Routes></BrowserRouter>}`;
function call(mode, components) {
  if (components) writeFileSync(proposal, JSON.stringify({components}));
  return spawnSync(process.execPath, [script, workspace, mode, proposal, '--source', file], {encoding:'utf8'});
}
try {
  writeFileSync(file, initial);
  const inspected = call('inspect'); assert.equal(inspected.status, 0, inspected.stderr);
  const contract = JSON.parse(inspected.stdout);
  assert.equal(contract.menu_owner, 'Center'); assert.equal(contract.routes.length, 2);
  assert.equal(contract.existing_links[0].target, '/personal/orders');
  for(const components of [
    {Orders: 'function Orders(){return null}'},
    {App: validApp.replace('/personal/orders', '/invented')},
    {App: validApp.replace('<Protected><ArcRailwayPersonalLayout><Orders/></ArcRailwayPersonalLayout></Protected>', '<Orders/>')},
    {App: validApp.replace('<Header/>','')},
    {App: validApp+'; console.log("outside component")'},
  ]) {
    const result = call('apply', components); assert.notEqual(result.status, 0);
    assert.equal(readFileSync(file,'utf8'), initial, 'Invalid proposal writes nothing');
  }
  const result = call('apply', {App: validApp, Center:'function Center(){return <section>Original notice</section>}',
    ArcRailwayPersonalLayout:'function ArcRailwayPersonalLayout({children}:any){return <div><ArcRailwayPersonalMenu/>{children}</div>}',
    ArcRailwayPersonalMenu:'function ArcRailwayPersonalMenu(){return <nav aria-label="Personal center menu"><Link to="/personal/orders">Order center</Link></nav>}' });
  assert.equal(result.status, 0, result.stderr);
  const after=readFileSync(file,'utf8');
  assert.ok(after.includes("const protectedBusinessLogic = 'must remain byte-identical';"));
  assert.ok(after.includes('function Orders(){return <div>Orders</div>}'));
  console.log('Railway component checks passed: component scope, complete declarations, route/guard/provider preservation, original business source retention.');
} finally {
  assert.ok(resolve(folder).startsWith(resolve(tmpdir())) && folder.includes('arc-railway-components-'));
  rmSync(folder,{recursive:true,force:true});
}
