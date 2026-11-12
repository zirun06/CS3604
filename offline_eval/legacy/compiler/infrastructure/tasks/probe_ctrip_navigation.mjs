import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
export async function probeNavigation(app,chromium,account){
  let server,browser,page,step='start';const completed=[],errors=[];
  try{
    server=app.listen(0,'127.0.0.1');await new Promise((resolve,reject)=>server.once('listening',resolve).once('error',reject));
    browser=await chromium.launch({timeout:8000});page=await browser.newPage();page.setDefaultTimeout(4000);page.on('pageerror',e=>errors.push(e.message));
    const base='http://127.0.0.1:'+server.address().port;
    const nav=()=>page.getByRole('navigation',{name:'Global navigation',exact:true});
    const link=(scope,name)=>scope.getByRole('link',{name,exact:true});
    const action=(scope,name)=>link(scope,name).or(scope.getByRole('button',{name,exact:true}));
    const heading=name=>page.getByRole('heading',{name,exact:true}).waitFor({state:'visible'});
    await page.goto(base,{waitUntil:'domcontentloaded',timeout:8000});
    step='entry Log in link';await nav().waitFor({state:'visible',timeout:8000});await link(nav(),'Log in').click();
    step='password credentials';await page.getByLabel('Account',{exact:true}).fill(account.email || account.username || account.mobile);
    await page.getByLabel('Password',{exact:true}).fill(account.password);await page.getByRole('checkbox',{name:'Agree to terms',exact:true}).check();
    step='password login';await page.getByRole('button',{name:'Log in',exact:true}).click();await page.getByRole('button',{name:'My account',exact:true}).waitFor({state:'visible'});completed.push(step);
    step='My account -> Orders';await page.getByRole('button',{name:'My account',exact:true}).click();
    await page.getByRole('menu').filter({has:link(page,'Orders')}).waitFor({state:'visible'});
    await link(page,'Orders').click();await heading('Orders');completed.push(step);
    step='My account -> Personal center';await page.getByRole('button',{name:'My account',exact:true}).click();
    await page.getByRole('menu').filter({has:link(page,'Personal center')}).waitFor({state:'visible'});
    await link(page,'Personal center').click();await heading('Personal center');
    await page.getByRole('button',{name:'Common information',exact:true}).waitFor({state:'visible'});completed.push(step);
    step='session reload';await page.reload({waitUntil:'domcontentloaded',timeout:8000});await page.getByRole('button',{name:'My account',exact:true}).waitFor({state:'visible'});completed.push(step);
    step='Log out menuitem';await page.getByRole('button',{name:'My account',exact:true}).hover();
    await page.getByRole('menuitem',{name:'Log out',exact:true}).click();await link(nav(),'Log in').waitFor({state:'visible'});completed.push(step);
    step='Flights -> Flight status';await action(nav(),'Flights').click();await link(page,'Flight status').click();await heading('Flight status');completed.push(step);
    step='More services -> Airport guide';await action(nav(),'More services').click();
    for(const name of ['Domestic airport directory','International airport directory'])await action(page,name).waitFor({state:'visible'});
    await action(page,'Airport guide').click();
    await page.getByRole('region',{name:'Popular airports',exact:true}).waitFor({state:'visible'});completed.push(step);
    if(errors.length)throw new Error(errors.join('\n'));
    return {status:'GREEN',completed};
  }catch(error){return {status:'FAILED',step,completed,error:error.message,page_errors:errors,url:page?.url(),body:page?(await page.locator('body').innerText().catch(()=>'' )).slice(0,6500):''};}
  finally{if(browser)await browser.close();if(server){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}}
}
async function main(workspace,browserWorkspace){
  const {chromium}=createRequire(resolve(browserWorkspace,'package.json'))('playwright');const load=relative=>import(pathToFileURL(resolve(workspace,relative)).href);
  const world=JSON.parse(readFileSync(resolve(workspace,'.arc/initial_world.json'),'utf8'));
  const accounts=(world.seed_records?.['existing verified accounts'] || []).flatMap(row=>Object.values(row));const account=accounts.find(a=>a?.email&&a?.password);
  if(!account)throw new Error('A declared verified account is required');
  const {createApp}=await load('backend/dist/app.js');const {createDatabaseClient}=await load('backend/dist/db/client.js');const {initializeDatabase}=await load('backend/dist/db/initialize.js');const db=createDatabaseClient(':memory:');
  try{initializeDatabase(db);const result=await probeNavigation(createApp(db),chromium,account);console.log(JSON.stringify(result));process.exitCode=result.status==='GREEN'?0:1;}finally{db.close();}
}
if(process.argv[1]&&pathToFileURL(resolve(process.argv[1])).href===import.meta.url)main(...process.argv.slice(2)).catch(error=>{console.log(JSON.stringify({status:'FAILED',step:'initialization',error:error.message}));process.exitCode=1;});
