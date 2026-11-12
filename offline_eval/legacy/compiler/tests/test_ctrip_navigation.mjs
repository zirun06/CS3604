import assert from 'node:assert/strict';import {createRequire} from 'node:module';import {resolve} from 'node:path';
import {probeNavigation} from '../infrastructure/tasks/probe_ctrip_navigation.mjs';
const express=createRequire(resolve(process.argv[2],'package.json'))('express');const {chromium}=createRequire(resolve(process.argv[3],'package.json'))('playwright');
function fixture(wrongRole=false,decorated=false,explicitLabels=false){const app=express();app.use(express.urlencoded({extended:false}));
 app.post('/login',(req,res)=>{if(req.body.account!=='fixture@example.com'||req.body.password!=='fixture-pass')return res.status(401).end();res.cookie('sid','real');res.redirect('/');});
 app.get('/logout',(_req,res)=>{res.clearCookie('sid');res.redirect('/');});
 app.get('/{*path}',(req,res)=>{const signed=(req.headers.cookie||'').includes('sid=real');
 const header=`<nav aria-label="Global navigation"><button onclick="this.nextElementSibling.hidden=false">Flights</button><div hidden><a href="/status">Flight status</a></div><button onclick="this.nextElementSibling.hidden=false">More services</button><div hidden><a href="/airport">Airport guide</a><a href="/domestic">Domestic airport directory</a><a href="/international">International airport directory</a></div>${signed?`<button onclick="this.nextElementSibling.hidden=false" onmouseenter="this.nextElementSibling.hidden=false">My account</button><div role="menu" hidden><a ${wrongRole?'role="menuitem"':''} href="/orders">Orders</a><a href="/personal">Personal center</a><a role="menuitem" href="/logout">Log out</a></div>`:'<a href="/login">Log in</a>'}</nav>`;
 let body='';if(req.path==='/status')body='<h1>Flight status</h1>';if(req.path==='/airport')body='<section aria-label="Popular airports">Actual airport list</section>';
 if(req.path==='/login')body='<form method="post" action="/login"><label>Account<input name="account"></label><label>Password<input name="password" type="password"></label><label><input type="checkbox">Agree to terms</label><button>Log in</button></form>';
 if(req.path==='/orders')body='<h1>Orders</h1>';if(req.path==='/personal')body='<h1>Personal center</h1><button>Common information</button>';
 const accessible=explicitLabels?header.replace(/<button([^>]*)>(Flights|More services|My account)<\/button>/g,(_match,attrs,name)=>`<button aria-label="${name}"${attrs}>${name}</button>`):header;
 res.send('<!doctype html><html><head>'+(decorated?'<style>nav button::after{content:"▾"}</style>':'')+'</head><body>'+accessible+body+'</body></html>');});return app;}
const account={email:'fixture@example.com',password:'fixture-pass'};
const green=await probeNavigation(fixture(),chromium,account);assert.equal(green.status,'GREEN',JSON.stringify(green));assert.equal(green.completed.length,7);
const failed=await probeNavigation(fixture(true),chromium,account);assert.equal(failed.status,'FAILED');assert.equal(failed.step,'My account -> Orders');
const decorated=await probeNavigation(fixture(false,true,false),chromium,account);assert.equal(decorated.status,'FAILED');assert.equal(decorated.step,'password login');
const named=await probeNavigation(fixture(false,true,true),chromium,account);assert.equal(named.status,'GREEN',JSON.stringify(named));
console.log('Ctrip browser checks passed: public service navigation, real login/reload, native account links; menuitem override rejected.');
