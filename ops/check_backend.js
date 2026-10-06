#!/usr/bin/env node
// Backend health checks that work without a database or internet:
//   1. every file parses
//   2. every module loads (Prisma is replaced by a stand-in, so missing
//      imports, typos in require() and crashes at load time are caught)
//   3. the Prisma schema is valid
//   4. an error inside an async route gives a 500 instead of stopping the server
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

checkAsyncErrors().catch(e => bad('async error check failed: ' + e.message)).finally(() => {
  console.log(problems.length ? `${problems.length} backend problem(s)` : 'Backend OK');
  process.exit(problems.length ? 1 : 0);
});
