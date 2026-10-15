// Member wins on the public landing page.
//
// A member can tick "Show this on the website" when they post a win. It then waits for
// Alexander to approve it on the owner dashboard; only approved wins appear on the landing
// page, with the member's public name (the part of their email before the "@", the same name
// other members already see) and never their email. Deleting the win removes it everywhere.
//
//   GET  /api/public-wins            approved wins for the landing page (no login)
//   GET  /api/public-wins/review     owner: waiting, approved and hidden
//   PUT  /api/public-wins/:winId     owner: { status: "approved" | "hidden" }
//
// Table created at startup with CREATE TABLE IF NOT EXISTS; declared in prisma/schema.prisma too.
const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { isOwnerEmail } = require('../pro');
const { publicName } = require('../publicName');

const DDL = [
  `CREATE TABLE IF NOT EXISTS "WinPublic" (
    "winId" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'waiting',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "reviewedAt" TIMESTAMP(3),
    CONSTRAINT "WinPublic_pkey" PRIMARY KEY ("winId"),
    CONSTRAINT "WinPublic_winId_fkey" FOREIGN KEY ("winId") REFERENCES "Win"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  `CREATE INDEX IF NOT EXISTS "WinPublic_status_idx" ON "WinPublic"("status")`,
];

let ready = false;
async function ensurePublicWinsTable() {
  for (let attempt = 0; attempt < 3 && !ready; attempt++) {
    try {
      for (const sql of DDL) await prisma.$executeRawUnsafe(sql);
      ready = true;
      console.log('WinPublic table ready.');
    } catch (err) {
      console.error('WinPublic table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return ready;
}

// Called by POST /api/wins when the member ticked "Show this on the website".
async function offerWin(winId) {
  if (!ready) return false;
  await prisma.$executeRawUnsafe(`INSERT INTO "WinPublic" ("winId") VALUES ($1::text) ON CONFLICT ("winId") DO NOTHING`, winId);
  return true;
}

const router = express.Router();
const publicLimiter = rateLimit({ windowMs: 60 * 1000, max: 60, standardHeaders: true, legacyHeaders: false });

let cache = { at: 0, wins: null };
router.get('/', publicLimiter, async (req, res) => {
  if (!ready) return res.json({ wins: [] });
  if (!cache.wins || Date.now() - cache.at > 5 * 60 * 1000) {
    const rows = await prisma.$queryRawUnsafe(
      `SELECT w."id", w."body", w."createdAt", u."email" FROM "WinPublic" p
         JOIN "Win" w ON w."id" = p."winId" JOIN "User" u ON u."id" = w."authorId"
        WHERE p."status" = 'approved' ORDER BY w."createdAt" DESC LIMIT 6`);
    cache = { at: Date.now(), wins: rows.map(r => ({ id: r.id, body: r.body, name: publicName(r.email), createdAt: r.createdAt })) };
  }
  res.set('Cache-Control', 'public, max-age=300');
  res.json({ wins: cache.wins });
});

const ownerOnly = (req, res, next) => (isOwnerEmail(req.user && req.user.email) ? next() : res.status(403).json({ error: 'Not authorized.' }));

router.get('/review', requireAuth, ownerOnly, async (req, res) => {
  if (!ready) return res.status(503).json({ error: 'Not ready yet.' });
  const rows = await prisma.$queryRawUnsafe(
    `SELECT p."winId", p."status", p."createdAt", w."body", u."email" FROM "WinPublic" p
       JOIN "Win" w ON w."id" = p."winId" JOIN "User" u ON u."id" = w."authorId"
      ORDER BY (p."status" = 'waiting') DESC, p."createdAt" DESC LIMIT 100`);
  res.json({ wins: rows.map(r => ({ winId: r.winId, status: r.status, body: r.body, name: publicName(r.email), createdAt: r.createdAt })) });
});

router.put('/:winId', requireAuth, ownerOnly, async (req, res) => {
  if (!ready) return res.status(503).json({ error: 'Not ready yet.' });
  const status = req.body && req.body.status;
  if (!['approved', 'hidden'].includes(status)) return res.status(400).json({ error: 'Status must be "approved" or "hidden".' });
  const n = await prisma.$executeRawUnsafe(
    `UPDATE "WinPublic" SET "status" = $2::text, "reviewedAt" = CURRENT_TIMESTAMP WHERE "winId" = $1::text`, String(req.params.winId), status);
  if (!n) return res.status(404).json({ error: 'That win is not waiting for the website.' });
  cache = { at: 0, wins: null };
  res.json({ ok: true, status });
});

module.exports = router;
module.exports.ensurePublicWinsTable = ensurePublicWinsTable;
module.exports.offerWin = offerWin;
