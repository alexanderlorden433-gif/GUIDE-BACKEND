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
  // Creator payouts: a code can carry a share of what its members pay (e.g. 30%), paid out by hand each month.
  `ALTER TABLE "PromoCode" ADD COLUMN IF NOT EXISTS "commissionPct" INTEGER`,
  `CREATE TABLE IF NOT EXISTS "PartnerPayout" (
    "id" TEXT NOT NULL,
    "codeId" TEXT NOT NULL,
    "month" TEXT NOT NULL,
    "amount" DOUBLE PRECISION NOT NULL,
    "paidAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PartnerPayout_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "PartnerPayout_codeId_fkey" FOREIGN KEY ("codeId") REFERENCES "PromoCode"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "PartnerPayout_codeId_month_key" ON "PartnerPayout"("codeId", "month")`,
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
           expiresAt: c.expiresAt, createdAt: c.createdAt, commissionPct: c.commissionPct == null ? null : Number(c.commissionPct) };
}
// A creator's share, as a whole percent from 1 to 90; blank or 0 means no share.
function cleanPct(v) {
  if (v == null || v === '') return { ok: true, pct: null };
  const n = Math.round(Number(v));
  if (n === 0) return { ok: true, pct: null };
  return n >= 1 && n <= 90 ? { ok: true, pct: n } : { ok: false };
}
// "2026-10" -> [start, end) as Dates in UTC
function monthRange(m) {
  const mm = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(String(m || ''));
  if (!mm) return null;
  const start = new Date(Date.UTC(+mm[1], +mm[2] - 1, 1));
  const end = new Date(Date.UTC(+mm[1], +mm[2], 1));
  return { start, end };
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
  const share = cleanPct(b.commissionPct);
  if (!share.ok) return res.status(400).json({ error: 'The creator share is a percent from 1 to 90, or blank.' });
  const id = crypto.randomUUID();
  await prisma.$executeRawUnsafe(
    `INSERT INTO "PromoCode" ("id","code","label","days","maxUses","expiresAt","commissionPct") VALUES ($1::text,$2::text,$3::text,$4::int,$5::int,$6::timestamp,$7::int)`,
    id, code, label, days, maxUses, expiresAt, share.pct);
  const rows = await prisma.$queryRawUnsafe(`SELECT * FROM "PromoCode" WHERE "id" = $1::text`, id);
  res.status(201).json(Object.assign(shape(rows[0]), { state: codeState(rows[0]) }));
});

// ---------- PUT /api/codes/:id ---------- { active } turns a code on or off, { commissionPct } sets the creator's share
router.put('/:id', async (req, res) => {
  const b = req.body || {};
  const id = String(req.params.id || '').slice(0, 80);
  let n = 0;
  if ('commissionPct' in b) {
    const share = cleanPct(b.commissionPct);
    if (!share.ok) return res.status(400).json({ error: 'The creator share is a percent from 1 to 90, or blank.' });
    n = await prisma.$executeRawUnsafe(`UPDATE "PromoCode" SET "commissionPct" = $1::int WHERE "id" = $2::text`, share.pct, id);
  }
  if ('active' in b || !('commissionPct' in b)) {
    n = await prisma.$executeRawUnsafe(`UPDATE "PromoCode" SET "active" = $1::boolean WHERE "id" = $2::text`, !!b.active, id);
  }
  if (!n) return res.status(404).json({ error: 'Code not found.' });
  const rows = await prisma.$queryRawUnsafe(`SELECT * FROM "PromoCode" WHERE "id" = $1::text`, id);
  res.json(Object.assign(shape(rows[0]), { state: codeState(rows[0]) }));
});

// ---------- GET /api/codes/payouts?month=YYYY-MM ----------
// For every code with a creator share: the members it brought in (credited to the first code a member
// used), how many are paying now, what they paid that month (purchases and renewals, from the money
// events the Stripe webhook already records), and the creator's cut. Refunds are not subtracted.
router.get('/payouts', async (req, res) => {
  const range = monthRange(req.query.month);
  if (!range) return res.status(400).json({ error: 'Month must look like 2026-10.' });
  let rows;
  try {
    rows = await prisma.$queryRawUnsafe(
      `WITH firsts AS (
         SELECT DISTINCT ON (r."userId") r."userId", r."codeId", r."createdAt" FROM "PromoRedemption" r ORDER BY r."userId", r."createdAt" ASC
       ), pay AS (
         SELECT f."codeId", COUNT(e."id")::int AS payments, COALESCE(SUM(e."value"), 0)::float AS revenue
           FROM firsts f JOIN "AnalyticsEvent" e ON e."userId" = f."userId"
          WHERE e."type" IN ('purchase', 'renewal') AND e."value" > 0 AND e."createdAt" >= f."createdAt"
            AND e."createdAt" >= $1::timestamp AND e."createdAt" < $2::timestamp
          GROUP BY f."codeId"
       ), mem AS (
         SELECT f."codeId", COUNT(*)::int AS members,
                COUNT(*) FILTER (WHERE u."isPro" AND u."stripeSubscriptionId" IS NOT NULL)::int AS paying
           FROM firsts f JOIN "User" u ON u."id" = f."userId" GROUP BY f."codeId"
       )
       SELECT c."id", c."code", c."label", c."commissionPct", COALESCE(m.members, 0) AS members, COALESCE(m.paying, 0) AS paying,
              COALESCE(p.payments, 0) AS payments, COALESCE(p.revenue, 0) AS revenue, po."amount" AS "paidAmount", po."paidAt"
         FROM "PromoCode" c
         LEFT JOIN mem m ON m."codeId" = c."id"
         LEFT JOIN pay p ON p."codeId" = c."id"
         LEFT JOIN "PartnerPayout" po ON po."codeId" = c."id" AND po."month" = $3::text
        WHERE c."commissionPct" IS NOT NULL AND c."commissionPct" > 0
        ORDER BY COALESCE(p.revenue, 0) DESC, c."createdAt" DESC`, range.start, range.end, req.query.month);
  } catch (err) {
    // the money events table is created by analytics.js; until it exists there is nothing to report
    console.error('Payout report failed:', err.message);
    return res.status(503).json({ error: 'Payment history is not ready yet. Try again in a minute.' });
  }
  const payouts = rows.map(r => {
    const revenue = Math.round(Number(r.revenue) * 100) / 100;
    return { codeId: r.id, code: r.code, label: r.label, commissionPct: Number(r.commissionPct), members: Number(r.members), paying: Number(r.paying),
             payments: Number(r.payments), revenue, owed: Math.round(revenue * Number(r.commissionPct)) / 100,
             paid: r.paidAmount == null ? null : { amount: Number(r.paidAmount), at: r.paidAt } };
  });
  res.json({ month: req.query.month, payouts, totalOwed: Math.round(payouts.reduce((s, p) => s + (p.paid ? 0 : p.owed), 0) * 100) / 100 });
});

// ---------- POST /api/codes/:id/payouts ---------- { month, amount }: note that you paid the creator
router.post('/:id/payouts', async (req, res) => {
  const b = req.body || {};
  if (!monthRange(b.month)) return res.status(400).json({ error: 'Month must look like 2026-10.' });
  const amount = Math.round(Number(b.amount) * 100) / 100;
  if (!(amount >= 0 && amount <= 1000000)) return res.status(400).json({ error: 'Enter the amount you paid.' });
  const id = String(req.params.id || '').slice(0, 80);
  const found = await prisma.$queryRawUnsafe(`SELECT "id" FROM "PromoCode" WHERE "id" = $1::text`, id);
  if (!found[0]) return res.status(404).json({ error: 'Code not found.' });
  await prisma.$executeRawUnsafe(
    `INSERT INTO "PartnerPayout" ("id","codeId","month","amount") VALUES ($1::text,$2::text,$3::text,$4::float)
     ON CONFLICT ("codeId","month") DO UPDATE SET "amount" = EXCLUDED."amount", "paidAt" = CURRENT_TIMESTAMP`,
    crypto.randomUUID(), id, b.month, amount);
  res.json({ ok: true, month: b.month, amount });
});

module.exports = router;
module.exports.ensureCodeTables = ensureCodeTables;
