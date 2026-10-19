#!/usr/bin/env node
// Backend health checks that work without a database or internet:
//   1. every file parses
//   2. every module loads (Prisma is replaced by a stand-in, so missing
//      imports, typos in require() and crashes at load time are caught)
//   3. the Prisma schema is valid
//   4. an error inside an async route gives a 500 instead of stopping the server
//   5. big-enough request sizes: saving progress and Guider chats aren't cut off at 16 KB
//   5b. The Guider's hourly message limit counts per member, not per network
//   6. a host can edit a live call that has already started (to fix the link mid-call)
//   7. The Guider is told about the member's 30-day plan in that chapter (day and goal), and only that chapter
//   8. the billing emails (trial ends tomorrow, checkout left) say the amount, how to cancel, and nothing was charged
//   9. member websites: what a member or a visitor types is shown as text, never run as page code
//  10. deleting an account stops its Stripe subscription first (and keeps the account if Stripe can't be reached)
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

// 5b. The Guider's hourly limit (it costs money per message) is counted per member. Counted per
//     network instead, people sharing one (an office, a school, a phone carrier) would block each
//     other, and one member could get around it by switching networks.
async function checkGuiderLimit() {
  const router = require(path.join(ROOT, 'src', 'routes', 'aiChat'));
  const express = require(path.join(ROOT, 'node_modules', 'express'));
  const jwt = require(path.join(ROOT, 'node_modules', 'jsonwebtoken'));
  const app = express();
  app.use('/api/ai-chat', router);
  const token = (sub) => jwt.sign({ sub, email: sub + '@b.test' }, process.env.JWT_SECRET, { issuer: 'theguide', audience: 'theguide-app' });
  const server = await new Promise(r => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
  // a path the limiter counts but no route answers, so nothing reaches the database or Anthropic
  const hit = (sub) => fetch(`http://127.0.0.1:${server.address().port}/api/ai-chat/limit-check`, { method: 'POST',
    headers: { Authorization: 'Bearer ' + token(sub) }, signal: AbortSignal.timeout(3000) }).then(r => r.status);
  try {
    let last = 0;
    for (let i = 0; i < 41; i++) last = await hit('member-a');
    if (last === 429) ok("The Guider's hourly limit stops a member after 40 messages");
    else bad(`The Guider's hourly limit did not stop a member after 40 messages (got ${last})`);
    const other = await hit('member-b');
    if (other !== 429) ok('another member on the same network can still ask The Guider');
    else bad("The Guider's limit is per network: a second member on the same network is blocked too");
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

// 9. member websites (theguide.company/s/<address>): the page is drawn from what members type, and the
//    request form shows back what visitors typed. All of it must arrive as text.
function checkMemberSites() {
  const sites = require(path.join(ROOT, 'src', 'sites'));
  const evil = '<script>alert(1)</script>"><img src=x onerror=alert(1)>';
  const data = {
    name: evil, tagline: evil, area: evil, hours: evil, about: evil, email: 'a@b.co', phone: '555 123 4567',
    services: [{ name: evil, price: evil, note: evil }], highlights: [evil], faq: [{ q: evil + '</script>', a: evil }] };
  let html = '';
  for (const lang of ['en', 'es']) {
    // a live page (with the search-engine data block) and a preview, in both languages
    html += sites.renderSitePage({ slug: 'joes-lawns', previewKey: 'k', data: Object.assign({ lang }, data) }, {});
    html += sites.renderSitePage({ slug: 'joes-lawns', previewKey: 'k', data: Object.assign({ lang }, data) }, { preview: true, previewKey: 'k', error: evil, form: { name: evil, contact: evil, message: evil, service: evil } });
  }
  const scripts = (html.match(/<script(?![^>]*application\/ld\+json)/g) || []).length;
  const closes = (html.match(/<\/script>/g) || []).length, opens = (html.match(/<script/g) || []).length;
  if (scripts || closes !== opens || /<img/i.test(html) || html.includes('<script>alert')) bad('a member website lets typed text run as page code');
  else ok("member websites show typed text as text (no code runs), including reasons and questions");
  // pages the AI designs: nothing that runs survives the cleaning, and they're served with no scripts, sandboxed
  const design = require(path.join(ROOT, 'src', 'siteDesign'));
  const dirty = '<h1>Hi</h1><script>alert(1)</script><img src="https://x.test/a.png" onerror="alert(1)"><a href="javascript:alert(1)" onclick="x()">a</a>'
    + '<iframe src="https://evil.test"></iframe><svg onload="alert(1)"><a href="javascript:alert(1)"><text>t</text></a></svg><form action="https://evil.test"></form><div style="x:y" data-guide="form"></div>';
  const clean = design.cleanHtml(dirty), cleanCss = design.cleanCss('@import url(https://evil.test/x.css);a{background:url(javascript:alert(1))}</style><script>');
  const page = sites.renderSitePage({ slug: 'joes-lawns', previewKey: 'k', data: { name: evil, services: [{ name: evil, price: '$1' }], design: { html: dirty, css: 'a{}</style><script>alert(1)</script>', fonts: ['Inter'] } } }, {});
  const pageScripts = (page.match(/<script(?![^>]*application\/ld\+json)/g) || []).length;
  if (/<script|onerror|onclick|onload|javascript:|<iframe|<form action="https:|style=/i.test(clean) || /@import|javascript:|<\/style/i.test(cleanCss) || pageScripts
      || !/default-src 'none'/.test(design.CUSTOM_CSP) || !/sandbox /.test(design.CUSTOM_CSP) || /allow-scripts|allow-same-origin/.test(design.CUSTOM_CSP)) bad('an AI-designed page could run code: ' + clean.slice(0, 200));
  else ok('pages the AI designs keep no code that runs, and go out with no scripts allowed, sandboxed');
  // the AI page writer: loads, and its answer format is one the API accepts (every object closed, no length rules)
  const siteAi = require(path.join(ROOT, 'src', 'siteAi'));
  const objs = []; (function walk(n) { if (n && typeof n === 'object') { if (n.type === 'object') objs.push(n); Object.values(n).forEach(walk); } })(siteAi.SCHEMA);
  if (objs.length && objs.every(o => o.additionalProperties === false && Object.keys(o.properties).every(k => o.required.includes(k)))
      && !/minLength|maxLength|maxItems|minimum|maximum/.test(JSON.stringify(siteAi.SCHEMA)) && siteAi.MODELS()[0]) ok('the AI page writer loads and asks for a page format the API accepts');
  else bad('the AI page writer schema would be refused by the API (every object needs additionalProperties: false and all fields required)');
  // AI credits: every pack makes a profit even if a write costs 40 cents (the top of the estimate) after Stripe's 2.9% + 30c
  const { PACKS, WELCOME } = require(path.join(ROOT, 'src', 'siteCredits'));
  const margin = (p) => (p.cents - (p.cents * 0.029 + 30) - p.credits * 40) / p.cents;
  if (PACKS.length && PACKS.every(p => margin(p) > 0.1) && WELCOME <= 3) ok('every AI credit pack makes money even at 40 cents a write, after Stripe');
  else bad('an AI credit pack would lose money at 40 cents a write (or too many free credits): ' + PACKS.map(p => p.id + ' ' + Math.round(margin(p) * 100) + '%').join(', '));
  if (sites.slugProblem('admin') && sites.slugProblem('theguide') && !sites.slugProblem('joes-lawns')) ok("member web addresses can't take The Guide's own names");
  else bad("member web address rules are off (reserved names or a normal name)");
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

// 8. billing emails: the trial reminder and the checkout note say the right things, plainly.
function checkBillingEmails() {
  const be = require(path.join(ROOT, 'src', 'billingEmails'));
  const t = be.trialEndingEmail({ endsAt: Date.parse('2026-10-16T18:00:00Z'), amountCents: 2499, currency: 'usd', interval: 'month' });
  if (/\$24\.99 a month/.test(t.text) && /Manage subscription/.test(t.text) && /stays free/.test(t.text) && !/—/.test(t.text + t.html)) ok('the trial reminder says the amount, how to cancel, and that Module 1 stays free');
  else bad('the trial-ending email is missing the amount, the way to cancel, or uses an em dash');
  const c = be.checkoutLeftEmail({ startedAt: Date.parse('2026-10-15T12:00:00Z'), prices: { monthly: { amount: 24.99, currency: 'USD' }, yearly: { amount: 149, currency: 'USD' } } });
  if (/nothing was charged/.test(c.text) && /\$24\.99 a month or \$149 a year/.test(c.text) && /only reminder/.test(c.text) && !/—/.test(c.text + c.html)) ok('the checkout note says nothing was charged, the real prices, and that it is the only reminder');
  else bad('the checkout-left email is missing "nothing was charged", the prices, or the only-reminder line');
}

// 10. deleting an account: the Stripe subscription is stopped first, so a deleted account is never charged
//     again; if Stripe can't be reached the account stays (the member is told to try again).
async function checkDeleteCancels() {
  const { cancelAllSubscriptions } = require(path.join(ROOT, 'src', 'stripe'));
  const cancelled = [];
  const fakeStripe = (fail) => ({ subscriptions: {
    list: ({ customer }) => (async function* () {
      if (fail) throw new Error('Stripe is down');
      if (customer !== 'cus_1') return;
      yield { id: 'sub_live', status: 'active' }; yield { id: 'sub_trial', status: 'trialing' };
      yield { id: 'sub_old', status: 'canceled' }; yield { id: 'sub_late', status: 'past_due' };
    })(),
    cancel: async (id) => { cancelled.push(id); return { id, status: 'canceled' }; },
  } });
  const n = await cancelAllSubscriptions('cus_1', fakeStripe(false));
  if (n === 3 && cancelled.join() === 'sub_live,sub_trial,sub_late') ok('cancelAllSubscriptions stops active, trial and overdue subscriptions (not old ones)');
  else bad(`cancelAllSubscriptions stopped ${JSON.stringify(cancelled)}, expected the 3 live ones`);
  if ((await cancelAllSubscriptions(null, fakeStripe(true))) === 0) ok('no Stripe customer: nothing to cancel');
  else bad('cancelAllSubscriptions should do nothing without a Stripe customer');

  // the route itself, with a stand-in database and Stripe
  const routeFile = require.resolve(path.join(ROOT, 'src', 'routes', 'account'));
  const stripeFile = require.resolve(path.join(ROOT, 'src', 'stripe'));
  const dbFile = require.resolve(path.join(ROOT, 'src', 'db'));
  const saved = { route: require.cache[routeFile], stripe: require.cache[stripeFile], db: require.cache[dbFile] };
  const run = async (stripeFails) => {
    const log = [];
    const fakeDb = { user: {
      findUnique: async () => ({ stripeCustomerId: 'cus_1' }),
      delete: async () => { log.push('deleted'); return {}; },
    } };
    const realStripe = require(stripeFile);
    delete require.cache[routeFile];
    require.cache[dbFile] = { id: dbFile, filename: dbFile, loaded: true, exports: fakeDb };
    require.cache[stripeFile] = { id: stripeFile, filename: stripeFile, loaded: true, exports: Object.assign({}, realStripe, {
      cancelAllSubscriptions: async (c) => { if (stripeFails) throw new Error('Stripe is down'); log.push('cancelled ' + c); return 1; } }) };
    const router = require(routeFile);
    const express = require(path.join(ROOT, 'node_modules', 'express'));
    const jwt = require(path.join(ROOT, 'node_modules', 'jsonwebtoken'));
    const app = express();
    app.use('/api/account', router);
    app.use((err, req, res, next) => res.status(500).json({ error: err.message }));
    const token = jwt.sign({ sub: 'u1', email: 'a@b.test' }, process.env.JWT_SECRET, { issuer: 'theguide', audience: 'theguide-app' });
    const server = await new Promise(r => { const s = app.listen(0, '127.0.0.1', () => r(s)); });
    try {
      const res = await fetch(`http://127.0.0.1:${server.address().port}/api/account`, { method: 'DELETE', headers: { Authorization: 'Bearer ' + token }, signal: AbortSignal.timeout(3000) });
      return { status: res.status, log };
    } finally { server.close(); }
  };
  try {
    const good = await run(false);
    if (good.status === 200 && good.log.join() === 'cancelled cus_1,deleted') ok('DELETE /api/account cancels the subscription, then deletes the account');
    else bad(`DELETE /api/account: got ${good.status}, steps ${JSON.stringify(good.log)} (should cancel the subscription before deleting)`);
    const down = await run(true);
    if (down.status === 502 && !down.log.includes('deleted')) ok('if Stripe is down, the account is kept and the member is told to try again');
    else bad(`DELETE /api/account with Stripe down: got ${down.status}, steps ${JSON.stringify(down.log)} (must not delete while still subscribed)`);
  } finally {
    for (const [k, f] of [['route', routeFile], ['stripe', stripeFile], ['db', dbFile]]) {
      if (saved[k]) require.cache[f] = saved[k]; else delete require.cache[f];
    }
  }
}

checkAsyncErrors()
  .catch(e => bad('async error check failed: ' + e.message))
  .then(() => checkBodyLimits().catch(e => bad('request size check failed: ' + e.message)))
  .then(() => checkGuiderLimit().catch(e => bad('Guider limit check failed: ' + e.message)))
  .then(() => { try { checkLiveEdit(); } catch (e) { bad('live edit check failed: ' + e.message); } })
  .then(() => { try { checkMemberSites(); } catch (e) { bad('member website check failed: ' + e.message); } })
  .then(() => { try { checkGuiderPlan(); } catch (e) { bad('Guider plan check failed: ' + e.message); } })
  .then(() => { try { checkBillingEmails(); } catch (e) { bad('billing email check failed: ' + e.message); } })
  .then(() => checkDeleteCancels().catch(e => bad('delete account check failed: ' + e.message)))
  .finally(() => {
  console.log(problems.length ? `${problems.length} backend problem(s)` : 'Backend OK');
  process.exit(problems.length ? 1 : 0);
});
