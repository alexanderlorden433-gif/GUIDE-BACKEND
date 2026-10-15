// Partner codes: a code a partner (a newsletter, a podcast, a creator) gives their audience,
// worth a number of free Pro days. Redeeming one extends bonusProUntil, the same grant the
// referral reward uses, so it expires on its own and never touches Stripe.
//
// Alexander creates codes from the owner dashboard. Each code has a day count, an optional
// use limit and an optional expiry; a member can redeem a given code once.
// Tables are created at startup with CREATE TABLE IF NOT EXISTS (same approach as live.js)
// and are also declared in prisma/schema.prisma.
const express = require('express');
const crypto = require('crypto');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { isOwnerEmail } = require('../pro');
const { notifyUser } = require('../notifications');

const DDL = [
  `CREATE TABLE IF NOT EXISTS "PromoCode" (
    "id" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "days" INTEGER NOT NULL,
    "maxUses" INTEGER,
    "uses" INTEGER NOT NULL DEFAULT 0,
    "active" BOOLEAN NOT NULL DEFAULT TRUE,
    "expiresAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PromoCode_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "PromoCode_code_key" ON "PromoCode"("code")`,
  `CREATE TABLE IF NOT EXISTS "PromoRedemption" (
    "id" TEXT NOT NULL,
    "codeId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PromoRedemption_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "PromoRedemption_codeId_fkey" FOREIGN KEY ("codeId") REFERENCES "PromoCode"("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "PromoRedemption_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "PromoRedemption_codeId_userId_key" ON "PromoRedemption"("codeId", "userId")`,
];

let ready = false;
async function ensureCodeTables() {
  for (let attempt = 0; attempt < 3 && !ready; attempt++) {
    try {
      for (const sql of DDL) await prisma.$executeRawUnsafe(sql);
      ready = true;
      console.log('Partner code tables ready.');
    } catch (err) {
      console.error('Partner code table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return ready;
}

// ---------------------------------------------------------------- helpers
const CODE_RE = /^[A-Z0-9][A-Z0-9-]{2,23}$/;
function cleanCode(v) {
  const s = String(v == null ? '' : v).trim().toUpperCase().replace(/\s+/g, '');
  return CODE_RE.test(s) ? s : null;
}
function randomCode(prefix) {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let s = '';
  for (let i = 0; i < 6; i++) s += alphabet[crypto.randomInt(alphabet.length)];
  return (prefix ? prefix + '-' : '') + s;
}
function shape(c) {
  return { id: c.id, code: c.code, label: c.label, days: c.days, maxUses: c.maxUses, uses: c.uses, active: !!c.active,
           expiresAt: c.expiresAt, createdAt: c.createdAt };
}
function codeState(c) {
  if (!c.active) return 'inactive';
  if (c.expiresAt && new Date(c.expiresAt) < new Date()) return 'expired';
  if (c.maxUses != null && c.uses >= c.maxUses) return 'used_up';
  return 'ok';
}

const router = express.Router();
router.use(requireAuth);
router.use(async (req, res, next) => {
  if (!ready) return res.status(503).json({ error: 'Codes are not ready yet. Try again in a minute.' });
  next();
});

// ---------- POST /api/codes/redeem ----------
// A tight limit so nobody can sit and guess codes.
const redeemLimiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 12, standardHeaders: true, legacyHeaders: false,
                                  message: { error: 'Too many tries. Please wait a few minutes.' } });
router.post('/redeem', redeemLimiter, async (req, res) => {
  const code = cleanCode((req.body || {}).code);
  if (!code) return res.status(400).json({ error: 'Enter the code exactly as it was given to you.' });
  const rows = await prisma.$queryRawUnsafe(`SELECT * FROM "PromoCode" WHERE "code" = $1::text`, code);
  const c = rows[0];
  if (!c) return res.status(404).json({ error: 'That code does not exist. Check the spelling.' });
  const state = codeState(c);
  if (state === 'expired') return res.status(410).json({ error: 'That code has expired.' });
  if (state !== 'ok') return res.status(410).json({ error: 'That code is no longer available.' });
  const already = await prisma.$queryRawUnsafe(
    `SELECT "id" FROM "PromoRedemption" WHERE "codeId" = $1::text AND "userId" = $2::text`, c.id, req.user.id);
  if (already[0]) return res.status(409).json({ error: 'You have already used this code.' });

  const user = await prisma.user.findUnique({ where: { id: req.user.id }, select: { bonusProUntil: true } });
  const base = user.bonusProUntil && user.bonusProUntil > new Date() ? user.bonusProUntil : new Date();
  const until = new Date(base.getTime() + c.days * 24 * 60 * 60 * 1000);
  // record first; the unique index makes a double tap a no-op
  try {
    await prisma.$executeRawUnsafe(`INSERT INTO "PromoRedemption" ("id","codeId","userId") VALUES ($1::text,$2::text,$3::text)`,
      crypto.randomUUID(), c.id, req.user.id);
  } catch (e) {
    return res.status(409).json({ error: 'You have already used this code.' });
  }
  await prisma.$executeRawUnsafe(`UPDATE "PromoCode" SET "uses" = "uses" + 1 WHERE "id" = $1::text`, c.id);
  await prisma.user.update({ where: { id: req.user.id }, data: { bonusProUntil: until } });
  notifyUser(req.user.id, {
    type: 'referral_bonus',
    title: `${c.days} days of Pro are on 🎉`,
    body: `Your ${c.label} code is applied. Pro is open until ${until.toLocaleDateString('en-US', { month: 'long', day: 'numeric' })}.`,
    link: { view: 'home' },
  }).catch(() => {});
  res.json({ ok: true, days: c.days, label: c.label, bonusProUntil: until });
});

// Everything below is the owner's.
router.use((req, res, next) => {
  if (!isOwnerEmail(req.user.email)) return res.status(403).json({ error: 'Not authorized.' });
  next();
});

// ---------- GET /api/codes ----------
router.get('/', async (req, res) => {
  const rows = await prisma.$queryRawUnsafe(`SELECT * FROM "PromoCode" ORDER BY "createdAt" DESC LIMIT 200`);
  res.json({ codes: rows.map(c => Object.assign(shape(c), { state: codeState(c) })) });
});

// ---------- POST /api/codes ----------
router.post('/', async (req, res) => {
  const b = req.body || {};
  const label = String(b.label || '').replace(/\s+/g, ' ').trim().slice(0, 60);
  const days = Math.round(Number(b.days));
  if (!label) return res.status(400).json({ error: 'Give the code a label (who it is for).' });
  if (!(days >= 1 && days <= 365)) return res.status(400).json({ error: 'Days must be between 1 and 365.' });
  let maxUses = b.maxUses == null || b.maxUses === '' ? null : Math.round(Number(b.maxUses));
  if (maxUses != null && !(maxUses >= 1 && maxUses <= 100000)) return res.status(400).json({ error: 'Max uses must be between 1 and 100,000, or blank.' });
  let expiresAt = null;
  if (b.expiresAt) {
    expiresAt = new Date(b.expiresAt);
    if (isNaN(expiresAt.getTime())) return res.status(400).json({ error: 'That expiry date does not look right.' });
    expiresAt.setHours(23, 59, 59, 999);
  }
  let code = b.code ? cleanCode(b.code) : randomCode(String(b.prefix || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 8));
  if (!code) return res.status(400).json({ error: 'Codes are 3 to 24 letters, numbers or dashes.' });
  const dup = await prisma.$queryRawUnsafe(`SELECT "id" FROM "PromoCode" WHERE "code" = $1::text`, code);
  if (dup[0]) return res.status(409).json({ error: 'That code already exists. Pick another.' });
  const id = crypto.randomUUID();
  await prisma.$executeRawUnsafe(
    `INSERT INTO "PromoCode" ("id","code","label","days","maxUses","expiresAt") VALUES ($1::text,$2::text,$3::text,$4::int,$5::int,$6::timestamp)`,
    id, code, label, days, maxUses, expiresAt);
  const rows = await prisma.$queryRawUnsafe(`SELECT * FROM "PromoCode" WHERE "id" = $1::text`, id);
  res.status(201).json(Object.assign(shape(rows[0]), { state: codeState(rows[0]) }));
});

// ---------- PUT /api/codes/:id ---------- (turn a code on or off)
router.put('/:id', async (req, res) => {
  const active = !!(req.body || {}).active;
  const id = String(req.params.id || '').slice(0, 80);
  const n = await prisma.$executeRawUnsafe(`UPDATE "PromoCode" SET "active" = $1::boolean WHERE "id" = $2::text`, active, id);
  if (!n) return res.status(404).json({ error: 'Code not found.' });
  const rows = await prisma.$queryRawUnsafe(`SELECT * FROM "PromoCode" WHERE "id" = $1::text`, id);
  res.json(Object.assign(shape(rows[0]), { state: codeState(rows[0]) }));
});

module.exports = router;
module.exports.ensureCodeTables = ensureCodeTables;
