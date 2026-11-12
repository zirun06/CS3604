import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { probeContract } from '../infrastructure/tasks/probe_backend_contract.mjs';

const require = createRequire(resolve(process.argv[2], 'package.json'));
const express = require('express');
function app({ failRead = false, wrongShape = false, dropCookie = false, historical = [], brokenDetail = false } = {}) {
  const app = express(); app.use(express.json()); let current = null; let registered;
  app.get('/api/questions', (_req, res) => failRead ? res.status(500).json({error:'guest FK'}) : res.json({questions:[]}));
  app.get('/api/tags', (_req, res) => res.json({tags:[]}));
  app.get('/api/users', (_req, res) => res.json({users:[]}));
  app.get('/api/search', (req, res) => res.json({questions:historical.filter(row => row.title === req.query.q)}));
  app.get('/api/questions/:id', (req, res) => brokenDetail
    ? res.status(500).json({error:'no such column: a.modified_at'})
    : res.json({question:historical.find(row => String(row.id) === req.params.id)}));
  app.post('/api/auth/signup', (req, res) => {
    registered = {id:1,email:req.body.email,display_name:req.body.email,reputation:0};
    current = wrongShape ? {...registered,display_name:undefined,displayName:req.body.email} : registered;
    if (!dropCookie) res.cookie('sid','test-session');res.json({user:current});
  });
  app.get('/api/auth/me', (req, res) => res.json({user:req.headers.cookie?.includes('sid=test-session') ? current : null}));
  app.post('/api/auth/logout', (_req, res) => { current=null;res.clearCookie('sid');res.json({ok:true}); });
  app.post('/api/auth/login', (_req, res) => {current=registered;res.cookie('sid','test-session');res.json({user:current});});
  return app;
}
assert.deepEqual(await probeContract(app()), {public_reads:3,registration_login_session:'passed'});
await assert.rejects(probeContract(app({failRead:true})), /GET \/api\/questions: HTTP 500/);
await assert.rejects(probeContract(app({wrongShape:true})), /expected user with id,email,display_name,reputation/);
await assert.rejects(probeContract(app({dropCookie:true})), /session restore: expected user/);
const declared = [{id:1,title:'Public history A'}, {id:2,title:'Public history B'}];
assert.equal((await probeContract(app({historical:declared}), {historicalQuestions:declared})).historical_questions, 2);
await assert.rejects(probeContract(app({historical:declared.slice(0, 1)}), {historicalQuestions:declared}),
  /Declared initial public questions are absent from search:.*Public history B/);
await assert.rejects(probeContract(app({historical:declared,brokenDetail:true}), {historicalQuestions:declared}),
  /GET \/api\/questions\/1: HTTP 500/);
console.log('Backend contract checks passed: public reads, cookie flow, credentials, sessions, HTTP failures, response shape.');
