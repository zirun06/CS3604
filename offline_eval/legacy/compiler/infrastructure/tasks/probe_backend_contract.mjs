// Exercise the shared core contract in a disposable in-memory application.
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { existsSync, readFileSync } from 'node:fs';

export async function probeContract(app, { historicalQuestions = [] } = {}) {
  const server = app.listen(0, '127.0.0.1');
  await new Promise((resolve, reject) => server.once('listening', resolve).once('error', reject));
  const base = 'http://127.0.0.1:' + server.address().port;
  const jar = new Map();
  const email = 'compiler-probe+' + randomUUID() + '@example.com';
  const password = 'CompilerProbe123!';
  async function request(method, path, body) {
    const response = await fetch(base + path, { method,
      headers: { 'Content-Type': 'application/json',
        Cookie: [...jar].map(([key, value]) => key + '=' + value).join('; ') },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(4000) });
    for (const cookie of response.headers.getSetCookie()) {
      const pair = cookie.split(';', 1)[0];
      const equals = pair.indexOf('=');
      if (equals > 0) jar.set(pair.slice(0, equals), pair.slice(equals + 1));
    }
    const text = await response.text();
    if (!response.ok) throw new Error(`${method} ${path}: HTTP ${response.status}\n${text.slice(0, 1300)}`);
    try { return JSON.parse(text); }
    catch { throw new Error(`${method} ${path}: expected JSON, received ${text.slice(0, 200)}`); }
  }
  function user(result, stage) {
    const value = result.user;
    if (!value?.id || value.email !== email || value.display_name !== email ||
        typeof value.reputation !== 'number') {
      throw new Error(`${stage}: expected user with id,email,display_name,reputation; got ${JSON.stringify(result).slice(0, 900)}`);
    }
    return value;
  }
  try {
    for (const [path, key] of [['/api/questions', 'questions'], ['/api/tags', 'tags'], ['/api/users', 'users']]) {
      const result = await request('GET', path);
      if (!Array.isArray(result[key])) throw new Error(`GET ${path}: expected {${key}:array}`);
    }
    const missing = [];
    for (const question of historicalQuestions) {
      const result = await request('GET', '/api/search?q=' + encodeURIComponent(question.title));
      const found = Array.isArray(result.questions) && result.questions.find(row => row.title === question.title);
      if (!found) {
        missing.push(question.title);
      } else {
        if (!found.id) throw new Error('Search returned a historical question without its ID: ' + question.title);
        await request('GET', '/api/questions/' + encodeURIComponent(found.id));
      }
    }
    if (missing.length) throw new Error('Declared initial public questions are absent from search: ' +
      JSON.stringify(missing) + '. Seed the declared_initial_world records before handling public requests.');
    const created = user(await request('POST', '/api/auth/signup', { email, password }), 'signup');
    if (user(await request('GET', '/api/auth/me'), 'session restore').id !== created.id) {
      throw new Error('Session restoration changed account identity');
    }
    await request('POST', '/api/auth/logout');
    if ((await request('GET', '/api/auth/me')).user !== null) throw new Error('Logout did not clear authentication');
    if (user(await request('POST', '/api/auth/login', { email, password }), 'login').id !== created.id) {
      throw new Error('Login did not restore the registered account');
    }
    if (user(await request('GET', '/api/auth/me'), 'login session restore').id !== created.id) {
      throw new Error('Login session changed account identity');
    }
    return { public_reads: 3, registration_login_session: 'passed',
      ...(historicalQuestions.length ? { historical_questions: historicalQuestions.length } : {}) };
  } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

async function main(workspace) {
  const load = path => import(pathToFileURL(resolve(workspace, path)).href);
  const { createApp } = await load('backend/dist/app.js');
  const { createDatabaseClient } = await load('backend/dist/db/client.js');
  const { initializeDatabase } = await load('backend/dist/db/initialize.js');
  const db = createDatabaseClient(':memory:');
  const manifest = resolve(workspace, '.arc/initial_world.json');
  const world = existsSync(manifest) ? JSON.parse(readFileSync(manifest, 'utf8')) : {};
  try { initializeDatabase(db); console.log(JSON.stringify(await probeContract(createApp(db),
    { historicalQuestions: world.historical_questions ?? [] }))); }
  finally { db.close(); }
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  main(resolve(process.argv[2])).catch(error => { console.error(error.message); process.exitCode = 1; });
}
