#!/usr/bin/env node
// Backend health checks that work without a database or internet:
//   1. every file parses
//   2. every module loads (Prisma is replaced by a stand-in, so missing
//      imports, typos in require() and crashes at load time are caught)
//   3. the Prisma schema is valid
//   4. an error inside an async route gives a 500 instead of stopping the server
//   5. big-enough request sizes: saving progress and Guider chats aren't cut off at 16 KB
//   6. a host can edit a live call that has already started (to fix the link mid-call)
//   7. The Guider is told about the member's 30-day plan in that chapter (day and goal), and only that chapter
// Usage: node ops/check_backend.js   (exit 1 on any failure)
const fs = require('fs');
const path = require('path');
const Module = require('module');
const { execFileSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const problems = [];
const ok = (m) => console.log('  ✓ ' + m);
const bad = (m) => { problems.push(m); console.log('  ✗ ' + m); };

function jsFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(d => {
    const p = path.join(dir, d.name);
    if (d.isDirectory()) return jsFiles(p);
    return d.name.endsWith('.js') ? [p] : [];
  });
}

console.log('Backend checks');
const files = jsFiles(path.join(ROOT, 'src'));

// 1. syntax
let syntaxBad = 0;
for (const f of files) {
  try { execFileSync(process.execPath, ['--check', f], { stdio: 'pipe' }); }
  catch (e) { syntaxBad++; bad(`syntax error in ${path.relative(ROOT, f)}: ${String(e.stderr).split('\n').slice(0, 4).join(' ')}`); }
}
if (!syntaxBad) ok(`${files.length} files parse`);

// 2. load every module with a stand-in Prisma client
process.env.DATABASE_URL = process.env.DATABASE_URL || 'postgresql://check:check@127.0.0.1:1/check';
process.env.JWT_SECRET = process.env.JWT_SECRET || 'check';
process.env.STRIPE_SECRET_KEY = process.env.STRIPE_SECRET_KEY || 'sk_test_check';
const stub = () => new Proxy(function () {}, {
  get: (t, k) => (k === 'then' ? undefined : stub()),
  apply: () => Promise.resolve(null),
});
const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === '@prisma/client') return { PrismaClient: function () { return stub(); }, Prisma: stub() };
  return origLoad.apply(this, arguments);
};
let loadBad = 0;
for (const f of files) {
  if (path.basename(f) === 'index.js' && path.dirname(f) === path.join(ROOT, 'src')) continue; // starts the server
  if (/index-\d+\.html|\.html$/.test(f)) continue;
  try { require(f); }
  catch (e) { loadBad++; bad(`${path.relative(ROOT, f)} crashes when loaded: ${e.message.split('\n')[0]}`); }
}
if (!loadBad) ok('every module loads');

// 3. Prisma schema
try {
  const wasm = require(path.join(__dirname, 'node_modules', '@prisma', 'prisma-schema-wasm'));
  const schema = fs.readFileSync(path.join(ROOT, 'prisma', 'schema.prisma'), 'utf8');
  wasm.validate(JSON.stringify({ prismaSchema: schema, noColor: true }));
  ok('Prisma schema is valid');
} catch (e) {
  if (/Cannot find module/.test(e.message)) bad('Prisma schema not checked — run: cd ops && npm ci');
  else bad('Prisma schema invalid: ' + e.message.split('\n').slice(0, 6).join(' '));
}

Module._load = origLoad;

// 3b. posts, wins and mentor cards are shown to every member: send a name, never the poster's email
const leaks = ['discussion.js', 'wins.js', 'mentors.js'].filter(f =>
  /authorEmail\s*:/.test(fs.readFileSync(path.join(ROOT, 'src', 'routes', f), 'utf8')));
if (leaks.length) bad(`${leaks.join(', ')} send(s) the poster's email to other members — send authorName: publicName(email) instead`);
else ok("posts, wins and mentor cards send the poster's name, not their email");

// 4. an error inside an async route must give a 500, not stop the server
async function checkAsyncErrors() {
  const indexSrc = fs.readFileSync(path.join(ROOT, 'src', 'index.js'), 'utf8');
  if (!/require\(['"]\.\/asyncErrors['"]\)/.test(indexSrc)) {
    return bad('src/index.js does not load ./asyncErrors — an error in an async route would stop the server');
  }
  let express;
  try { express = require(path.join(ROOT, 'node_modules', 'express')); require(path.join(ROOT, 'src', 'asyncErrors')); }
  catch (e) { return bad('async error check skipped: ' + e.message.split('\n')[0]); }
  const app = express();
  app.get('/boom', async () => { await null; throw new Error('pretend database hiccup'); });
  app.use((err, req, res, next) => res.status(500).json({ error: 'x' }));
  let crashed = false;
  const onCrash = () => { crashed = true; };
  process.once('unhandledRejection', onCrash);
  const server = await new Promise(r => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  try {
    const res = await fetch(`http://127.0.0.1:${server.address().port}/boom`, { signal: AbortSignal.timeout(3000) });
    if (res.status === 500 && !crashed) ok('an error in an async route returns a 500 and the server keeps running');
    else bad(`async route error: got status ${res.status}${crashed ? ' and an unhandled rejection' : ''}`);
  } catch (e) {
    bad('async route error: request never answered (' + e.name + ')');
  } finally {
    process.removeListener('unhandledRejection', onCrash);
    server.close();
  }
}

// 5. request size limits: a realistic progress save (~40 KB: every lesson of the first
//    16 chapters ticked + a Guider chat) and a long Guider conversation must get through,
//    while ordinary routes still refuse oversized bodies.
async function checkBodyLimits() {
  const indexSrc = fs.readFileSync(path.join(ROOT, 'src', 'index.js'), 'utf8');
  if (!/useJsonParsers\(app, express\)/.test(indexSrc)) {
    return bad('src/index.js does not use useJsonParsers — request size limits not checked');
  }
  if (/app\.use\(express\.json\(/.test(indexSrc)) {
    return bad('src/index.js has its own express.json() — it would cut off progress saves at its limit');
  }
  const express = require(path.join(ROOT, 'node_modules', 'express'));
  const { useJsonParsers } = require(path.join(ROOT, 'src', 'bodyParsers'));
  const app = express();
  useJsonParsers(app, express);
  const echo = (req, res) => res.json({ got: JSON.stringify(req.body).length });
  app.put('/api/account', echo);
  app.post('/api/ai-chat', echo);
  app.post('/api/wins', echo);
  app.use((err, req, res, next) => res.status(err.status || 500).json({ error: err.type || 'x' }));
  const server = await new Promise(r => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const send = (method, p, body) => fetch(base + p, { method, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), signal: AbortSignal.timeout(3000) }).then(r => r.status);
  const completed = Array.from({ length: 756 }, (_, i) => `side-hustle-${i % 16}|How to do lesson number ${i} well`);
  const reply = 'A long, detailed Guider answer. '.repeat(150); // ~4.8 KB, about 1000 tokens
  const chat = Array.from({ length: 20 }, (_, i) => ({ role: i % 2 ? 'assistant' : 'user', content: i % 2 ? reply : 'How do I price my first job?' }));
  try {
    const save = await send('PUT', '/api/account', { data: { completed, aiChat: { cleaning: chat } } });
    if (save === 200) ok('a big progress save (an active learner, ~90 KB) gets through');
    else bad(`a big progress save is refused with status ${save} — people's progress would stop saving`);
    const ask = await send('POST', '/api/ai-chat', { nicheName: 'Cleaning', messages: chat });
    if (ask === 200) ok('a long Guider conversation (20 messages, ~50 KB) gets through');
    else bad(`a long Guider conversation is refused with status ${ask} — The Guider would stop answering`);
    const junk = await send('POST', '/api/wins', { text: 'x'.repeat(40 * 1024) });
    if (junk === 413) ok('other routes still refuse oversized bodies (16 KB)');
    else bad(`a 40 KB body to an ordinary route got status ${junk} instead of 413`);
  } catch (e) {
    bad('request size check: request never answered (' + e.name + ')');
  } finally {
    server.close();
  }
}

// 6. live calls: the edit form always sends the call's time back. A call that started a while ago
//    must still be editable (fixing a broken link mid-call), but a call can't be moved into the past.
function checkLiveEdit() {
  const { readCallFields } = require(path.join(ROOT, 'src', 'routes', 'live'));
  if (typeof readCallFields !== 'function') return bad('src/routes/live.js no longer exports readCallFields — live edit not checked');
  const started = new Date(Date.now() - 20 * 60 * 1000).toISOString();
  const existing = { title: 'Q&A', startsAt: started, durationMin: 45, joinUrl: 'https://meet.example.com/old' };
  const form = { title: 'Q&A', description: '', nicheId: '', durationMin: 45, startsAt: started, joinUrl: 'https://meet.example.com/new' };
  const edit = readCallFields(form, existing);
  if (edit.error) bad(`a host can't fix the link of a call that started 20 minutes ago: "${edit.error}"`);
  else ok('a host can edit a call that is already running (e.g. fix the link)');
  const moved = readCallFields(Object.assign({}, form, { startsAt: new Date(Date.now() - 60 * 60 * 1000).toISOString() }), existing);
  if (moved.error) ok('a call still can\'t be moved to a time that has passed');
  else bad('a call can be moved to a time that has already passed');
}

// 7. the 30-day plan: The Guider knows which day it is and what the member wants by day 30
function checkGuiderPlan() {
  const { buildGuiderContext } = require(path.join(ROOT, 'src', 'guiderContext'));
  const start = new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10);
  const niche = { id: 'lawn', guides: [{ title: 'A', mod: 0 }, { title: 'B', mod: 0 }], modules: [{ title: 'Start' }] };
  const blob = { completed: ['lawn|A'], dayPlan: { nicheId: 'lawn', start, goal: 'first_customer', from: 0, checkins: {} } };
  const here = buildGuiderContext(blob, niche);
  if (/day 3 of 30/.test(here) && /first paying customer/.test(here)) ok("The Guider knows the member's plan day and goal");
  else bad("The Guider isn't told about the member's 30-day plan: " + here.slice(0, 200));
  const other = buildGuiderContext(blob, Object.assign({}, niche, { id: 'cleaning' }));
  if (/30-day|of 30/.test(other)) bad("The Guider is told about a plan from another chapter");
  else ok("a plan in another chapter stays out of The Guider's notes");
}

checkAsyncErrors()
  .catch(e => bad('async error check failed: ' + e.message))
  .then(() => checkBodyLimits().catch(e => bad('request size check failed: ' + e.message)))
  .then(() => { try { checkLiveEdit(); } catch (e) { bad('live edit check failed: ' + e.message); } })
  .then(() => { try { checkGuiderPlan(); } catch (e) { bad('Guider plan check failed: ' + e.message); } })
  .finally(() => {
  console.log(problems.length ? `${problems.length} backend problem(s)` : 'Backend OK');
  process.exit(problems.length ? 1 : 0);
});
