import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const workspace=resolve(process.argv[2]),require=createRequire(resolve(workspace,'package.json'));
const ts=require('typescript'),Database=require('better-sqlite3');
const folder=mkdtempSync(resolve(tmpdir(),'arc-ctrip-source-')),file=resolve(folder,'fixture.tsx');
const script=fileURLToPath(new URL('../infrastructure/tasks/prepare_ctrip_source.mjs',import.meta.url));
function run(mode,source){if(source!==undefined)writeFileSync(file,source);const result=spawnSync(process.execPath,[script,workspace,mode,file],{encoding:'utf8'});assert.equal(result.status,0,result.stderr);return readFileSync(file,'utf8');}
const db=new Database(':memory:');
try{
  db.exec("CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT);CREATE TABLE sessions(token TEXT,user_id INTEGER);INSERT INTO users VALUES(1,'real');INSERT INTO sessions VALUES('guest',NULL),('signed',1)");
  const backend=run('backend',`export function getSession(db:any,token:string){return db.prepare('SELECT s.token, s.user_id, u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?').get(token);}
    export function ensureGuest(db:any,token:string){return getSession(db,token);}
    const BASE=100;export function clockNow(){return BASE;}
    export function registerApis(app:any){app.use((_req:any,res:any,next:any)=>{res.setHeader('Content-Type','application/json');next();});}`);
  assert.equal(run('backend'),backend,'Backend preparation is idempotent');
  assert.match(backend,/app.use\('\/api',/);
  const module={exports:{}};new Function('exports','module',ts.transpileModule(backend,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText)(module.exports,module);
  assert.equal(module.exports.getSession(db,'guest').token,'guest');assert.equal(module.exports.getSession(db,'guest').id,null);
  assert.equal(module.exports.getSession(db,'signed').id,1);
  const before=module.exports.clockNow();await new Promise(resolve=>setTimeout(resolve,25));assert.ok(module.exports.clockNow()>before);
  const ui=run('frontend',`function App(){return <><nav aria-label="Global navigation"><Link role="menuitem" to="/orders">Orders</Link><Link to="/more">More services</Link><div onMouseEnter={()=>setOpen(true)}><button onClick={()=>setOpen(o=>!o)}>My account</button></div></nav>
    <Link to="/more">More services</Link><button role="tab" onClick={()=>setMode('sms')}>Verification code login</button>
    <button role="menuitem">Log out</button><h1>Book flight {number}</h1><main><section aria-label="Flight list">real flights</section></main></>}`);
  assert.equal((ui.match(/role="menuitem"/g)||[]).length,1);assert.match(ui,/setOpen\(true\)/);assert.ok(!ui.includes('o=>!o'));
  assert.match(ui,/<span>\{number\}<\/span>/);
  assert.match(ui,/Explore more services/);assert.match(ui,/role="link"/);assert.match(ui,/aria-label="Book flight"/);assert.match(ui,/<h1>Flight results<\/h1>/);
  assert.equal(run('frontend'),ui,'Frontend preparation is idempotent');
  const synchronized=run('frontend',`export async function api(path:string){const res=await fetch(path);if(!res.ok)throw Error('failed');return await res.json();}
    export function useSession(){const [session,setSession]=useState(null);useEffect(()=>{api('/api/session').then(setSession)},[]);return session;}
    export function App(){const [user,setUser]=useState(null);useEffect(()=>{api('/api/session').then(setUser)},[]);return user;}`);
  assert.equal(run('frontend'),synchronized);
  const events=new EventTarget(),updates=[];
  const syncModule={exports:{}};
  new Function('exports','module','useState','useEffect','window','fetch',ts.transpileModule(synchronized,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText)(syncModule.exports,syncModule,()=>[null,value=>updates.push(value)],callback=>callback(),events,async path=>({ok:path!=='/fail',json:async()=>({authenticated:false})}));
  syncModule.exports.useSession();syncModule.exports.App();await new Promise(resolve=>setTimeout(resolve,0));updates.length=0;
  await syncModule.exports.api('/api/login/password');assert.equal(updates.filter(v=>typeof v==='function').length,2,'Both persistent consumers refresh after login');
  updates.length=0;await syncModule.exports.api('/api/session');assert.equal(updates.length,0,'Session reads do not cause an event loop');
  const dateUi=run('frontend',`function Home(){return <div><label>Departure date<input aria-label="Departure date"/></label><button onClick={()=>setPicker('depart')}>Choose date</button></div>}`);
  assert.match(dateUi,/<input onClick=\{\(\)=>setPicker\('depart'\)\}/);assert.equal(run('frontend'),dateUi);
  const pointerUi=run('frontend',`function Header(){const enter=()=>setOpen(true);const click=()=>{setOpen(v=>!v);doOtherWork()};return <div onPointerEnter={enter}><button onClick={click}>My account</button></div>}`);
  assert.ok(!pointerUi.includes('v=>!v'));assert.match(pointerUi,/doOtherWork\(\)/);assert.equal(run('frontend'),pointerUi);
  const fields=run('frontend',`function Fields({record}:{record:{name:string,city:string,meta:object}}){return <><span>{record.name} · {record.city}</span><div>Mobile: {record.name || '-'}</div><div>Object: {record.meta}</div><span>{record.name}</span><nav aria-label="Global navigation"><div onMouseEnter={()=>setServices(true)}><button onClick={()=>setServices(v=>!v)}>More services</button></div></nav><div><button onClick={()=>setOther(v=>!v)}>More services</button></div></>}`);
  assert.match(fields,/<span><span>\{record.name\}<\/span> · <span>\{record.city\}<\/span><\/span>/);
  assert.match(fields,/<div>Mobile: <span>\{record.name \|\| '-'\}<\/span><\/div>/);
  assert.match(fields,/<div>Object: \{record.meta\}<\/div>/);
  assert.match(fields,/setServices\(true\)/);assert.match(fields,/setOther\(v=>!v\)/);
  assert.equal(run('frontend'),fields,'Scalar boundaries remain idempotent and do not wrap objects or standalone fields');
  const routing=run('frontend',`import {Link,useNavigate} from 'react-router-dom';function Airports(){const navigate=useNavigate();return <><section aria-label="Popular airports">{names.map(name=><li><button type="button" onClick={()=>navigate('/airport/'+encodeURIComponent(name))}>{name}</button></li>)}</section><section aria-label="Domestic airports"><button onClick={()=>setLetter('C')}>C</button></section><section aria-label="Pending vouchers">{orders.map(o=><li key={o.id}>{o.number}</li>)}</section><section aria-label="Order list"><Link to={'/orders/'+id}>View details</Link></section></>}`);
  assert.ok(routing.includes("to={'/airport/'+encodeURIComponent(name)}"));
  assert.match(routing,/<button onClick=\{\(\)=>setLetter\('C'\)\}>C/);
  assert.match(routing,/aria-label=\{'Record ' \+ o.number\}/);assert.match(routing,/<Link role="button"/);
  assert.equal(run('frontend'),routing,'Navigation and voucher identity repairs are idempotent');
  const booleans=run('frontend',`function Form({password,confirm}:{password:string,confirm:string}){return <><button disabled={password && password!==confirm}>Save</button><input checked={password===confirm}/></>}`);
  assert.match(booleans,/disabled=\{Boolean\(password && password!==confirm\)\}/);assert.match(booleans,/checked=\{password===confirm\}/);assert.equal(run('frontend'),booleans);
  const bus=run('frontend',`function Bus({buses}:{buses:{name:string,stop:string}[]}){return <section aria-label="City buses"><div>{buses.map(bus=><div>{bus.name} · {bus.stop}</div>)}</div></section>}`);
  assert.match(bus,/role="group"/);assert.match(bus,/aria-label=\{'Record ' \+ bus.name\}/);assert.equal(run('frontend'),bus);
  assert.equal((bus.match(/role="group"/g)||[]).length,1,'Record identity never escapes a map callback scope');
  const menuLabels=run('frontend',`function Dropdown(props:{label:string}){return <button aria-haspopup="menu">{props.label}</button>}function Nav(){return <nav aria-label="Global navigation"><button>Flights</button><Dropdown label="My account"/></nav>}`);
  assert.match(menuLabels,/aria-label=\{props.label\}/);assert.match(menuLabels,/aria-label="Flights"/);assert.equal(run('frontend'),menuLabels);
  const sharedTrigger=run('frontend',`function Dropdown(props:{label:string}){const [open,setOpen]=useState(false);return <button aria-haspopup="menu" onPointerEnter={()=>setOpen(true)} onClick={()=>{doOtherWork();setOpen(v=>!v)}}>{props.label}</button>}`);
  assert.ok(!sharedTrigger.includes('v=>!v'));assert.match(sharedTrigger,/doOtherWork\(\)/);assert.equal(run('frontend'),sharedTrigger);
  console.log('Ctrip source checks passed: actual nullable SQLite guest session, authenticated owner, advancing clock, native roles, headings, menu hover/click, idempotence.');
}finally{db.close();assert.ok(folder.startsWith(resolve(tmpdir()))&&folder.includes('arc-ctrip-source-'));rmSync(folder,{recursive:true,force:true});}
