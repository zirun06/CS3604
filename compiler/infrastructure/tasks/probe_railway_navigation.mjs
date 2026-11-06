// A short real-browser prerequisite gate; no mutation of the application's persistent DB.
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export async function probeNavigation(app, chromium, account) {
  let server, browser, page; let step = 'start'; const completed = [], errors = [];
  try {
    server = app.listen(0, '127.0.0.1');
    await new Promise((resolve,reject)=>server.once('listening',resolve).once('error',reject));
    browser = await chromium.launch({timeout:8000}); page = await browser.newPage(); page.setDefaultTimeout(2500);
    page.on('pageerror',error=>errors.push(error.message));
    const link = (scope,name)=>scope.getByRole('link',{name,exact:true});
    const menu = ()=>page.getByRole('navigation',{name:'Personal center menu',exact:true});
    async function visible(locator) {await locator.waitFor({state:'visible',timeout:2500});}
    async function navigate(parent,child) {
      step = parent+' -> '+child;
      await link(menu(),parent).click({timeout:2500}); await visible(menu());
      await link(menu(),child).click({timeout:2500}); await visible(menu());
    }
    await page.goto('http://127.0.0.1:'+server.address().port,{waitUntil:'domcontentloaded',timeout:8000});
    step='login and reload';
    await link(page,'Login').click({timeout:2500});
    await page.getByPlaceholder('Email/Username/Mobile number',{exact:true}).fill(account.username,{timeout:2500});
    await page.getByPlaceholder('Password',{exact:true}).fill(account.password,{timeout:2500});
    await page.getByRole('button',{name:'LOGIN',exact:true}).click({timeout:2500});
    await visible(link(page,'Sign Out')); await page.reload({waitUntil:'domcontentloaded',timeout:8000});
    await visible(link(page,'Sign Out')); completed.push(step);
    step='personal center'; await link(page,'My 12306').click({timeout:2500}); await visible(menu());
    const notice=page.getByRole('region',{name:'Notice',exact:true});
    await visible(notice); await visible(notice.getByRole('img',{name:'Notice',exact:true}));
    await visible(link(notice,'ticket booking')); completed.push(step);
    await navigate('Information management','My Passengers');
    for(const name of ['Name','ID type','ID number']) await visible(page.getByRole('columnheader',{name,exact:true}));
    completed.push(step);
    await navigate('Order center','Ticket orders');
    await visible(page.getByRole('tab',{name:'Uncompleted orders',exact:true})); completed.push(step);
    await navigate('Personal','User information');
    await visible(page.getByRole('region',{name:'Essential information',exact:true})); completed.push(step);
    await navigate('Personal','Account security');
    await visible(link(page,'Login password'));
    await visible(page.getByRole('region',{name:'Security mailbox',exact:true})); completed.push(step);
    step='reload personal subpage'; await page.reload({waitUntil:'domcontentloaded',timeout:8000});
    await visible(menu()); await visible(link(page,'Sign Out')); completed.push(step);
    if(errors.length) throw new Error(errors.join('\n'));
    return {status:'GREEN',completed};
  } catch(error) {
    return {status:'FAILED',step,completed,error:error.message,page_errors:errors,
      url:page?.url(),body:page ? (await page.locator('body').innerText().catch(()=>'' )).slice(0,6000) : '',
      menu_html:page ? (await page.getByRole('navigation',{name:'Personal center menu',exact:true}).first()
        .evaluate(n=>n.outerHTML).catch(()=>'' )).slice(0,6000) : ''};
  } finally {
    if(browser) await browser.close();
    if(server) {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
  }
}

async function main(workspace,browserWorkspace) {
  const load=relative=>import(pathToFileURL(resolve(workspace,relative)).href);
  const {chromium}=createRequire(resolve(browserWorkspace,'package.json'))('playwright');
  const world=JSON.parse(readFileSync(resolve(workspace,'.arc/initial_world.json'),'utf8'));
  const accounts=(world.seed_records?.['verified account directory'] || []).flatMap(r=>r.accounts || []);
  const account=accounts.find(a=>a.username==='registered_user') || accounts[0];
  if(!account?.password) throw new Error('The navigation gate requires a declared verified account');
  const {createApp}=await load('backend/dist/app.js');
  const {createDatabaseClient}=await load('backend/dist/db/client.js');
  const {initializeDatabase}=await load('backend/dist/db/initialize.js');
  const db=createDatabaseClient(':memory:');
  try {
    initializeDatabase(db);const result=await probeNavigation(createApp(db),chromium,account);
    console.log(JSON.stringify(result));process.exitCode=result.status==='GREEN'?0:1;
  } finally {db.close();}
}
if(process.argv[1] && pathToFileURL(resolve(process.argv[1])).href===import.meta.url)
  main(...process.argv.slice(2)).catch(error=>{console.log(JSON.stringify({status:'FAILED',step:'initialization',error:error.message}));process.exitCode=1;});
