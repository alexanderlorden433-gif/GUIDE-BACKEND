// Client status pages (Business tab → Client Portal). A Pro member makes a page for a client
// and sends them a link. The client opens web/client-status.html?t=<token>: no login, they only
// see the client name, project name, status and the note. Nothing about the member's account
// is ever returned on the public route.
//
// The table is created on startup with CREATE TABLE IF NOT EXISTS (same approach as analytics.js
// and live.js) and is also declared in prisma/schema.prisma as ClientStatusPage.
const express = require('express');
const crypto = require('crypto');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');

const STATUSES = ['Not Started', 'In Progress', 'Awaiting Feedback', 'Final Review', 'Delivered'];
const MAX_PAGES = 50;

const DDL = [
  `CREATE TABLE IF NOT EXISTS "ClientStatusPage" (
    "id" TEXT NOT NULL,
    "token" TEXT NOT NULL,
    "ownerId" TEXT NOT NULL,
    "clientName" TEXT NOT NULL,
    "projectName" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'In Progress',
    "notes" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ClientStatusPage_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "ClientStatusPage_token_key" ON "ClientStatusPage"("token")`,
  `CREATE INDEX IF NOT EXISTS "ClientStatusPage_ownerId_idx" ON "ClientStatusPage"("ownerId")`,
];

let ready = false;
async function ensureClientStatusTable() {
  for (let attempt = 0; attempt < 3 && !ready; attempt++) {
    try {
      for (const sql of DDL) await prisma.$executeRawUnsafe(sql);
      ready = true;
      console.log('Client status table ready.');
    } catch (err) {
      console.error('Client status table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return ready;
}

// ---------------------------------------------------------------- helpers
function oneLine(v, max) {
  return String(v == null ? '' : v).replace(/\s+/g, ' ').trim().slice(0, max);
}
function cleanNotes(v) {
  return String(v == null ? '' : v).replace(/\r\n?/g, '\n').trim().slice(0, 1000);
}
function cleanStatus(v) {
  const s = oneLine(v, 40);
  return STATUSES.includes(s) ? s : null;
}
function listEnv(name) {
  return (process.env[name] || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}
// Same Pro rule as /api/account: the owner, preview accounts, paying members, and referral bonuses.
async function isProUser(userId) {
  const user = await prisma.user.findUnique({ where: { id: userId }, select: { email: true, isPro: true, bonusProUntil: true } });
  if (!user) return false;
  const email = user.email.toLowerCase();
  const owner = !!(process.env.OWNER_EMAIL && email === process.env.OWNER_EMAIL.trim().toLowerCase());
  return owner || listEnv('PREVIEW_EMAILS').includes(email) || !!user.isPro || !!(user.bonusProUntil && user.bonusProUntil > new Date());
}
function publicShape(p) {
  return { clientName: p.clientName, projectName: p.projectName, status: p.status, notes: p.notes || '', updatedAt: p.updatedAt };
}
function mineShape(p) {
  return { id: p.id, token: p.token, clientName: p.clientName, projectName: p.projectName, status: p.status, notes: p.notes || '',
           createdAt: p.createdAt, updatedAt: p.updatedAt };
}

const router = express.Router();

// ---------- GET /api/client-status/public/:token (no login) ----------
// What the client sees. Tokens are long and random; guessing one is not practical, and the
// rate limit makes trying slow.
const publicLimiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 120, standardHeaders: true, legacyHeaders: false,
                                  message: { error: 'Too many requests. Please try again shortly.' } });
router.get('/public/:token', publicLimiter, async (req, res) => {
  if (!ready) return res.status(503).json({ error: 'Status pages are not ready yet. Try again in a minute.' });
  const token = oneLine(req.params.token, 80);
  if (!/^[A-Za-z0-9_-]{20,80}$/.test(token)) return res.status(404).json({ error: 'This status page does not exist.' });
  const rows = await prisma.$queryRawUnsafe(
    `SELECT "clientName", "projectName", "status", "notes", "updatedAt" FROM "ClientStatusPage" WHERE "token" = $1::text`, token);
  if (!rows[0]) return res.status(404).json({ error: 'This status page does not exist.' });
  res.json(publicShape(rows[0]));
});

// Everything below is for the member who owns the pages.
router.use(requireAuth);
router.use(rateLimit({ windowMs: 15 * 60 * 1000, max: 150, standardHeaders: true, legacyHeaders: false,
                       message: { error: 'Too many requests. Please try again shortly.' } }));
router.use(async (req, res, next) => {
  if (!ready) return res.status(503).json({ error: 'Status pages are not ready yet. Try again in a minute.' });
  if (!(await isProUser(req.user.id))) return res.status(403).json({ error: 'Client status pages are part of Pro.', upgrade: true });
  next();
});

// ---------- GET /api/client-status/mine ----------
router.get('/mine', async (req, res) => {
  const rows = await prisma.$queryRawUnsafe(
    `SELECT "id", "token", "clientName", "projectName", "status", "notes", "createdAt", "updatedAt"
       FROM "ClientStatusPage" WHERE "ownerId" = $1::text ORDER BY "createdAt" DESC LIMIT ${MAX_PAGES}`, req.user.id);
  res.json({ pages: rows.map(mineShape) });
});

// ---------- POST /api/client-status ----------
router.post('/', async (req, res) => {
  const b = req.body || {};
  const clientName = oneLine(b.clientName, 80), projectName = oneLine(b.projectName, 80);
  if (!clientName || !projectName) return res.status(400).json({ error: 'Add a client name and a project name.' });
  const status = cleanStatus(b.status) || 'In Progress';
  const notes = cleanNotes(b.notes);
  const count = await prisma.$queryRawUnsafe(`SELECT COUNT(*)::int AS n FROM "ClientStatusPage" WHERE "ownerId" = $1::text`, req.user.id);
  if ((count[0] && count[0].n) >= MAX_PAGES) return res.status(400).json({ error: `You can have up to ${MAX_PAGES} status pages. Delete one first.` });
  const id = crypto.randomUUID();
  const token = crypto.randomBytes(24).toString('base64url');
  await prisma.$executeRawUnsafe(
    `INSERT INTO "ClientStatusPage" ("id", "token", "ownerId", "clientName", "projectName", "status", "notes")
     VALUES ($1::text, $2::text, $3::text, $4::text, $5::text, $6::text, $7::text)`,
    id, token, req.user.id, clientName, projectName, status, notes || null);
  const rows = await prisma.$queryRawUnsafe(`SELECT * FROM "ClientStatusPage" WHERE "id" = $1::text`, id);
  res.status(201).json(mineShape(rows[0]));
});

// ---------- PUT /api/client-status/:id ----------
router.put('/:id', async (req, res) => {
  const b = req.body || {};
  const rows = await prisma.$queryRawUnsafe(
    `SELECT * FROM "ClientStatusPage" WHERE "id" = $1::text AND "ownerId" = $2::text`, oneLine(req.params.id, 80), req.user.id);
  const page = rows[0];
  if (!page) return res.status(404).json({ error: 'Status page not found.' });
  const clientName = b.clientName !== undefined ? oneLine(b.clientName, 80) : page.clientName;
  const projectName = b.projectName !== undefined ? oneLine(b.projectName, 80) : page.projectName;
  if (!clientName || !projectName) return res.status(400).json({ error: 'Add a client name and a project name.' });
  const status = b.status !== undefined ? cleanStatus(b.status) : page.status;
  if (!status) return res.status(400).json({ error: 'Pick a status from the list.' });
  const notes = b.notes !== undefined ? cleanNotes(b.notes) : (page.notes || '');
  await prisma.$executeRawUnsafe(
    `UPDATE "ClientStatusPage" SET "clientName" = $1::text, "projectName" = $2::text, "status" = $3::text, "notes" = $4::text,
            "updatedAt" = CURRENT_TIMESTAMP WHERE "id" = $5::text`,
    clientName, projectName, status, notes || null, page.id);
  const after = await prisma.$queryRawUnsafe(`SELECT * FROM "ClientStatusPage" WHERE "id" = $1::text`, page.id);
  res.json(mineShape(after[0]));
});

// ---------- DELETE /api/client-status/:id ----------
router.delete('/:id', async (req, res) => {
  const n = await prisma.$executeRawUnsafe(
    `DELETE FROM "ClientStatusPage" WHERE "id" = $1::text AND "ownerId" = $2::text`, oneLine(req.params.id, 80), req.user.id);
  if (!n) return res.status(404).json({ error: 'Status page not found.' });
  res.json({ message: 'Deleted. The link no longer works.' });
});

module.exports = router;
module.exports.ensureClientStatusTable = ensureClientStatusTable;
module.exports.STATUSES = STATUSES;
