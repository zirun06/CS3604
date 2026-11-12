import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { probeNavigation } from '../infrastructure/tasks/probe_railway_navigation.mjs';
const require=createRequire(resolve(process.argv[2],'package.json'));
const express=require('express');
const {chromium}=createRequire(resolve(process.argv[3],'package.json'))('playwright');
function fixture(persistent) {
  const app=express(); app.use(express.urlencoded({extended:false}));
  app.post('/login',(req,res)=>{
    if(req.body.username!=='real_user'||req.body.password!=='real_password') return res.status(401).end();
    res.cookie('sid','fixture',{httpOnly:true});res.redirect('/');
  });
  const menu=`<nav aria-label="Personal center menu">
    <a href="/personal/orders">Order center</a><a href="/personal/orders">Ticket orders</a>
    <a href="/personal/profile">Personal</a><a href="/personal/profile">User information</a>
    <a href="/personal/security">Account security</a><a href="/personal/passengers">Information management</a>
    <a href="/personal/passengers">My Passengers</a></nav>`;
  app.get('/{*path}',(req,res)=>{
    const signedIn=(req.headers.cookie||'').includes('sid=fixture');
    const header=signedIn?'<a href="/logout">Sign Out</a><a href="/personal">My 12306</a>':'<a href="/login">Login</a>';
    let body='';
    if(req.path==='/login') body='<form method="post" action="/login"><input name="username" placeholder="Email/Username/Mobile number"><input name="password" placeholder="Password" type="password"><button>LOGIN</button></form>';
    if(req.path.startsWith('/personal') && signedIn) {
      if(persistent||req.path==='/personal') body+=menu;
      if(req.path==='/personal') body+='<section aria-label="Notice"><img alt="Notice"><a href="/results">ticket booking</a></section>';
      if(req.path.includes('passengers')) body+='<table><tr><th>Name</th><th>ID type</th><th>ID number</th></tr></table>';
      if(req.path.includes('orders')) body+='<button role="tab">Uncompleted orders</button>';
      if(req.path.includes('profile')) body+='<section aria-label="Essential information">Real profile</section>';
      if(req.path.includes('security')) body+='<a href="/password">Login password</a><section aria-label="Security mailbox">Real mailbox</section>';
    }
    res.send('<!doctype html><html><body>'+header+body+'</body></html>');
  }); return app;
}
const account={username:'real_user',password:'real_password'};
const good=await probeNavigation(fixture(true),chromium,account);
assert.equal(good.status,'GREEN',JSON.stringify(good));assert.equal(good.completed.length,7);
const broken=await probeNavigation(fixture(false),chromium,account);
assert.equal(broken.status,'FAILED');assert.equal(broken.step,'Information management -> My Passengers');
assert.match(broken.url,/passengers/);
console.log('Railway browser gate checks passed: real login/reload, persistent multi-page navigation, missing child-page menu detected.');
