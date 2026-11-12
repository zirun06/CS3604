import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
export async function probeBackend(app) {
  app.get('/__ctrip_html_probe__',(_req,res)=>res.send('<!doctype html><html><body>HTML response probe</body></html>'));
  const server=app.listen(0,'127.0.0.1');let cookie='';
  await new Promise((resolve,reject)=>server.once('listening',resolve).once('error',reject));
  const base='http://127.0.0.1:'+server.address().port;
  async function request(path,body) {
    const response=await fetch(base+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...(cookie?{Cookie:cookie}:{})},
      ...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(4000)});
    const set=response.headers.getSetCookie();if(set.length)cookie=set.map(c=>c.split(';')[0]).join('; ');
    return {ok:response.ok,status:response.status,body:await response.json()};
  }
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const mobile='139'+String(Date.now()).slice(-8), password='TravelProbe1234';
  try {
    const document=await fetch(base+'/__ctrip_html_probe__',{signal:AbortSignal.timeout(4000)});
    assert((document.headers.get('content-type')||'').includes('text/html'),'API middleware must not force JSON Content-Type onto HTML/static responses');
    let result=await request('/api/session');assert(result.ok&&!result.body.authenticated,'A new browser must remain anonymous');
    result=await request('/api/register/verify-mobile',{mobile,code:'123456'});assert(!result.ok,'Reject a verification code before it is sent');
    result=await request('/api/register/send-code',{mobile});assert(result.ok,'Send registration code: '+JSON.stringify(result));
    const sentCookie=cookie;
    result=await request('/api/session');assert(result.ok&&!result.body.authenticated,'Guest bootstrap must not authenticate a null user');
    assert(cookie===sentCookie,'Guest bootstrap replaced the verification session cookie');
    result=await request('/api/register/verify-mobile',{mobile,code:'123456'});
    assert(result.ok,'Sent code must survive the anonymous cookie roundtrip: '+JSON.stringify(result));
    result=await request('/api/register/complete',{mobile,code:'123456',password,confirmPassword:password});assert(result.ok,'Persist the verified account: '+JSON.stringify(result));
    result=await request('/api/login/password',{account:mobile,password,agree:true});assert(result.ok,'Registered credentials must authenticate');
    result=await request('/api/session');assert(result.ok&&result.body.authenticated&&result.body.user?.id,'Login cookie must restore a real user');
    await request('/api/logout',{});result=await request('/api/session');assert(!result.body.authenticated,'Logout must clear authentication');
    return {status:'GREEN',checks:['guest cookie persistence','sent-code gating','registration','login reload','logout']};
  } finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
}
async function main(workspace){
  const load=relative=>import(pathToFileURL(resolve(workspace,relative)).href);
  const {createApp}=await load('backend/dist/app.js');const {createDatabaseClient}=await load('backend/dist/db/client.js');
  const {initializeDatabase}=await load('backend/dist/db/initialize.js');const db=createDatabaseClient(':memory:');
  try{initializeDatabase(db);console.log(JSON.stringify(await probeBackend(createApp(db))));}finally{db.close();}
}
if(process.argv[1]&&pathToFileURL(resolve(process.argv[1])).href===import.meta.url)
  main(process.argv[2]).catch(error=>{console.error(error.message);process.exitCode=1;});
