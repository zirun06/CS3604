import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { probeBackend } from '../infrastructure/tasks/probe_ctrip_backend.mjs';
const express=createRequire(resolve(process.argv[2],'package.json'))('express');
function fixture({rotate=false,bypass=false,globalJson=false}={}){
 const app=express();app.use(express.json());let index=0,auth=false,account=null;const sent=new Map();
 if(globalJson)app.use((_req,res,next)=>{res.type('json');next();});
 app.use((req,res,next)=>{let token=(req.headers.cookie||'').replace('sid=','');if(!token){token='g'+(++index);res.cookie('sid',token);}req.token=token;next();});
 app.get('/api/session',(req,res)=>{if(rotate&&!auth)res.cookie('sid','rotated'+(++index));res.json({authenticated:auth,...(auth?{user:{id:1,mobile:account.mobile}}:{})});});
 app.post('/api/register/send-code',(req,res)=>{sent.set(req.token,req.body.mobile);res.json({ok:true});});
 app.post('/api/register/verify-mobile',(req,res)=>{if(!bypass&&(sent.get(req.token)!==req.body.mobile||req.body.code!=='123456'))return res.status(400).json({error:'not sent'});res.json({ok:true});});
 app.post('/api/register/complete',(req,res)=>{account=req.body;res.json({ok:true});});
 app.post('/api/login/password',(req,res)=>{if(!account||req.body.account!==account.mobile||req.body.password!==account.password)return res.status(401).json({error:'bad credentials'});auth=true;res.json({ok:true});});
 app.post('/api/logout',(_req,res)=>{auth=false;res.json({ok:true});});return app;
}
assert.equal((await probeBackend(fixture())).status,'GREEN');
await assert.rejects(probeBackend(fixture({rotate:true})),/replaced the verification session cookie/);
await assert.rejects(probeBackend(fixture({bypass:true})),/before it is sent/);
await assert.rejects(probeBackend(fixture({globalJson:true})),/HTML\/static responses/);
console.log('Ctrip backend checks passed: real HTTP registration/login/logout, lost guest cookie detected, unsent-code bypass detected.');
