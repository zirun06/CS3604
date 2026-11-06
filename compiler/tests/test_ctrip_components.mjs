import assert from 'node:assert/strict';
import { mkdtempSync,readFileSync,writeFileSync,rmSync } from 'node:fs';
import { resolve } from 'node:path';import { tmpdir } from 'node:os';import { fileURLToPath } from 'node:url';import { spawnSync } from 'node:child_process';
const workspace=resolve(process.argv[2]),folder=mkdtempSync(resolve(tmpdir(),'arc-ctrip-components-')),file=resolve(folder,'App.tsx'),proposal=resolve(folder,'proposal.json');
const script=fileURLToPath(new URL('../infrastructure/tasks/ctrip_components.mjs',import.meta.url));
const initial=`import {BrowserRouter,Routes,Route,Link} from 'react-router-dom';
function GlobalNav(){return <nav aria-label="Global navigation"><Link to="/orders">Orders</Link></nav>}
function Orders(){return <div>Original business page</div>}
export function App(){return <BrowserRouter><GlobalNav/><Routes><Route path="/orders" element={<Orders/>}/></Routes></BrowserRouter>}`;
function call(mode,components){if(components)writeFileSync(proposal,JSON.stringify({components}));return spawnSync(process.execPath,[script,workspace,mode,proposal,'--source',file],{encoding:'utf8'});}
try{
 writeFileSync(file,initial);const inspected=call('inspect');assert.equal(inspected.status,0,inspected.stderr);assert.deepEqual(Object.keys(JSON.parse(inspected.stdout).replaceable_components),['GlobalNav']);
 for(const components of [{App:'function App(){return null}'},{Orders:'function Orders(){return null}'},{GlobalNav:'function GlobalNav(){return <Route path="/fake" element={<Orders/>}/>}'},{GlobalNav:'function GlobalNav(){return null}; console.log("outside")'}]){assert.notEqual(call('apply',components).status,0);assert.equal(readFileSync(file,'utf8'),initial);}
 const result=call('apply',{GlobalNav:'function GlobalNav(){return <nav aria-label="Global navigation"><Link to="/orders">Orders</Link><button>My account</button></nav>}'});assert.equal(result.status,0,result.stderr);
 const after=readFileSync(file,'utf8');assert.ok(after.includes('function Orders(){return <div>Original business page</div>}'));assert.ok(after.includes(initial.slice(initial.indexOf('export function App'))));
 const services=initial+`\nfunction Airports(){return <section aria-label="Popular airports">real airport records</section>}\nfunction Vouchers(){return <section aria-label="Pending vouchers">real voucher records</section>}`;
 writeFileSync(file,services);const domain=call('inspect-services');assert.equal(domain.status,0,domain.stderr);
 assert.deepEqual(Object.keys(JSON.parse(domain.stdout).replaceable_components),['Airports','Vouchers']);
 for(const components of [{GlobalNav:'function GlobalNav(){return null}'},{App:'function App(){return null}'},{Orders:'function Orders(){return null}'}]) {
  assert.notEqual(call('apply-services',components).status,0);assert.equal(readFileSync(file,'utf8'),services);
 }
 assert.equal(call('apply-services',{Airports:'function Airports(){return <section aria-label="Popular airports"><Link to="/airport">Actual airport</Link></section>}'}).status,0);
 assert.ok(readFileSync(file,'utf8').startsWith(initial));
 console.log('Ctrip component checks passed: only global navigation can change; app, business views, routes and providers preserved.');
}finally{assert.ok(folder.startsWith(resolve(tmpdir()))&&folder.includes('arc-ctrip-components-'));rmSync(folder,{recursive:true,force:true});}
