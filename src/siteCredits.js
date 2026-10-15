// AI website credits: each AI write of a member's page (My website → "Write my page" / "Make it better") uses
// one credit. Every member gets a couple of free credits to try it; after that they buy a pack through Stripe.
//
// Why these prices: one write with Claude Fable 5.1 costs roughly 15 to 40 cents in AI usage, and Stripe takes
// 2.9% + 30 cents of each payment. Even at the top of that range every pack leaves a profit, and a member who
// buys the smallest pack pays about a dollar a page, far less than a copywriter or a website builder's AI plan.
// A write that fails gives its credit back. Credits never expire.
//
// Buying credits is separate from Pro: it never makes anyone Pro, and putting a page live still needs Pro.
//
// Pro members (and members from the old Lifetime plan, for good) also get one hour of AI writing a day without
// using credits: up to 10 writes, within 60 minutes of their first write of the day (their own day, from the time
// zone the app sends). After either runs out, credits work as usual. The 10 keeps a heavy day well under what a
// month of Pro brings in; the per-member cap of writes a day in src/siteAi.js still applies on top.
//
// The tables are created in src/sites.js (SiteAiCredit, SiteAiCreditLog, SiteAiHour).
const crypto = require('crypto');
const prisma = require('./db');
const { isProUser } = require('./pro');

const WELCOME = 2;   // free credits every member starts with
const PACKS = [
  { id: 'small', credits: 5, cents: 499 },
  { id: 'medium', credits: 15, cents: 999 },
  { id: 'large', credits: 40, cents: 1999 },
];
const packById = (id) => PACKS.find(p => p.id === id) || null;

/** Free credits handed out across the whole app in a day, so a wave of new accounts can't run up the AI bill. */
const FREE_DAILY_TOTAL = () => Math.max(0, parseInt(process.env.SITE_AI_FREE_DAILY_TOTAL, 10) || 150);

/** The member's credits, creating their row (with the free ones) the first time. */
async function getCredits(userId) {
  await prisma.$executeRawUnsafe(
    `INSERT INTO "SiteAiCredit" ("userId", "free", "paid") VALUES ($1::text, $2::int, 0) ON CONFLICT ("userId") DO NOTHING`, userId, WELCOME);
  const rows = await prisma.$queryRawUnsafe(`SELECT "free", "paid" FROM "SiteAiCredit" WHERE "userId" = $1::text`, userId);
  const r = rows[0] || { free: 0, paid: 0 };
  return { free: r.free, paid: r.paid, total: r.free + r.paid };
}

async function freeUsedToday() {
  const rows = await prisma.$queryRawUnsafe(
    `SELECT COUNT(*)::int AS n FROM "SiteAiCreditLog" WHERE "kind" = 'use' AND "free" < 0 AND "createdAt" >= date_trunc('day', NOW())`);
  return rows[0] ? rows[0].n : 0;
}

/**
 * Takes one credit for a write: a free one first, otherwise a bought one. Each step is one statement, so two
 * taps at once can't spend the same credit. Returns {bucket: 'free'|'paid'} or {bucket: null, reason}.
 */
async function spendCredit(userId) {
  const c = await getCredits(userId);
  if (c.free > 0 && (await freeUsedToday()) < FREE_DAILY_TOTAL()) {
    const r = await prisma.$queryRawUnsafe(
      `UPDATE "SiteAiCredit" SET "free" = "free" - 1, "updatedAt" = CURRENT_TIMESTAMP WHERE "userId" = $1::text AND "free" > 0 RETURNING "free"`, userId);
    if (r[0]) return { bucket: 'free' };
  }
  const r = await prisma.$queryRawUnsafe(
    `UPDATE "SiteAiCredit" SET "paid" = "paid" - 1, "updatedAt" = CURRENT_TIMESTAMP WHERE "userId" = $1::text AND "paid" > 0 RETURNING "paid"`, userId);
  if (r[0]) return { bucket: 'paid' };
  return { bucket: null, reason: c.free > 0 ? 'free_busy' : 'empty' };
}

/** Gives a credit back after a write that failed. */
async function refundCredit(userId, bucket) {
  const col = bucket === 'free' ? '"free"' : '"paid"';
  await prisma.$executeRawUnsafe(`UPDATE "SiteAiCredit" SET ${col} = ${col} + 1, "updatedAt" = CURRENT_TIMESTAMP WHERE "userId" = $1::text`, userId);
}

/** Notes a finished write: which credit it used, the model, and the tokens (what it really cost). */
async function logUse(userId, bucket, model, usage) {
  // bucket: 'free' | 'paid' | 'hour' (Pro's daily hour: no credit used, but still logged for what it cost)
  const u = usage || {};
  const n = (v) => (Number.isFinite(v) ? Math.round(v) : null);
  const input = n((u.input_tokens || 0) + (u.cache_read_input_tokens || 0) + (u.cache_creation_input_tokens || 0));
  await prisma.$executeRawUnsafe(
    `INSERT INTO "SiteAiCreditLog" ("id", "userId", "kind", "free", "paid", "model", "inputTokens", "outputTokens")
     VALUES ($1::text, $2::text, 'use', $3::int, $4::int, $5::text, $6::int, $7::int)`,
    crypto.randomUUID(), userId, bucket === 'free' ? -1 : 0, bucket === 'paid' ? -1 : 0, String(model || '').slice(0, 60), input, n(u.output_tokens));
}

/**
 * Adds the credits a Stripe checkout paid for. Called from the Stripe webhook and when the member comes back
 * from checkout, whichever is first: the checkout's id is unique in the log, so the credits are added once.
 * Returns {ok, added, userId} or {ok: false, why}.
 */
async function grantFromCheckout(session) {
  const s = session || {};
  const m = s.metadata || {};
  if (m.kind !== 'site_credits') return { ok: false, why: 'not a credits checkout' };
  const pack = packById(m.pack);
  if (!pack || !m.userId || typeof s.id !== 'string') return { ok: false, why: 'missing pack or member' };
  if (s.payment_status !== 'paid') return { ok: false, why: 'not paid yet' };
  if ((s.amount_subtotal !== pack.cents && s.amount_total !== pack.cents) || String(s.currency || '').toLowerCase() !== 'usd') return { ok: false, why: 'amount does not match the pack' };
  const rows = await prisma.$queryRawUnsafe(
    `WITH ins AS (
       INSERT INTO "SiteAiCreditLog" ("id", "userId", "kind", "paid", "pack", "amountCents", "stripeSession")
       VALUES ($1::text, $2::text, 'buy', $3::int, $4::text, $5::int, $6::text)
       ON CONFLICT ("stripeSession") DO NOTHING
       RETURNING "userId", "paid")
     INSERT INTO "SiteAiCredit" ("userId", "free", "paid")
       SELECT "userId", $7::int, "paid" FROM ins
     ON CONFLICT ("userId") DO UPDATE SET "paid" = "SiteAiCredit"."paid" + EXCLUDED."paid", "updatedAt" = CURRENT_TIMESTAMP
     RETURNING "paid"`,
    crypto.randomUUID(), m.userId, pack.credits, pack.id, pack.cents, s.id, WELCOME);
  return { ok: true, added: rows[0] ? pack.credits : 0, userId: m.userId, pack: pack.id };
}

// ---------------------------------------------------------------- Pro's daily AI hour
const HOUR_MINUTES = 60;
const HOUR_WRITES = 10;
const DEFAULT_TZ = 'America/New_York';

/** A time zone name the app sent, if it's a real one. */
function cleanTz(tz) {
  tz = String(tz || '').slice(0, 64);
  if (!/^(?:UTC|[A-Za-z_]+(?:\/[A-Za-z0-9_+-]+){1,2})$/.test(tz)) return DEFAULT_TZ;
  try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return tz; } catch (e) { return DEFAULT_TZ; }
}
/** The member's date today, like 2026-10-15, in their time zone. */
function localDay(tz) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: cleanTz(tz), year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

/** Pro members, and the old Lifetime plan forever, get the daily AI hour. */
async function hasDailyHour(userId) {
  if (await isProUser(userId)) return true;
  const u = await prisma.user.findUnique({ where: { id: userId }, select: { planType: true } });
  return !!(u && u.planType === 'lifetime');
}

/**
 * Where today's hour stands: {included: false} for members without one, otherwise {included: true, minutes,
 * writes, state: 'ready' | 'active' | 'used', minutesLeft, secondsLeft, writesLeft}. 'used' means the time or
 * the writes ran out. Times are worked out in the database, so the server's and the database's clocks agree.
 */
async function hourState(userId, tz, included) {
  if (included === undefined) included = await hasDailyHour(userId);
  const base = { included: !!included, minutes: HOUR_MINUTES, writes: HOUR_WRITES };
  if (!included) return base;
  const rows = await prisma.$queryRawUnsafe(
    `SELECT GREATEST(0, EXTRACT(EPOCH FROM ("startedAt" + make_interval(mins => $3::int) - CURRENT_TIMESTAMP)))::int AS "secondsLeft", "writes"
       FROM "SiteAiHour" WHERE "userId" = $1::text AND "day" = $2::text`, userId, localDay(tz), HOUR_MINUTES);
  if (!rows[0]) return Object.assign(base, { state: 'ready', writesLeft: HOUR_WRITES });
  const secondsLeft = rows[0].secondsLeft, writesLeft = Math.max(0, HOUR_WRITES - rows[0].writes);
  if (secondsLeft > 0 && writesLeft > 0) return Object.assign(base, { state: 'active', secondsLeft, minutesLeft: Math.ceil(secondsLeft / 60), writesLeft });
  return Object.assign(base, { state: 'used', writesLeft });
}

/**
 * For a write: starts today's hour if it hasn't started, and takes one of its writes if there's time and a write
 * left (in one statement, so taps at once can't go past 10). True when this write is covered by the hour.
 */
async function useDailyHour(userId, tz) {
  if (!(await hasDailyHour(userId))) return false;
  const day = localDay(tz);
  await prisma.$executeRawUnsafe(
    `INSERT INTO "SiteAiHour" ("userId", "day") VALUES ($1::text, $2::text) ON CONFLICT ("userId", "day") DO NOTHING`, userId, day);
  const rows = await prisma.$queryRawUnsafe(
    `UPDATE "SiteAiHour" SET "writes" = "writes" + 1
      WHERE "userId" = $1::text AND "day" = $2::text AND "writes" < $3::int
        AND "startedAt" + make_interval(mins => $4::int) > CURRENT_TIMESTAMP
      RETURNING "writes"`, userId, day, HOUR_WRITES, HOUR_MINUTES);
  return !!rows[0];
}
/** Gives an hour write back after a write that failed. */
async function giveBackHourWrite(userId, tz) {
  await prisma.$executeRawUnsafe(
    `UPDATE "SiteAiHour" SET "writes" = GREATEST("writes" - 1, 0) WHERE "userId" = $1::text AND "day" = $2::text`, userId, localDay(tz));
}

/** The packs as the app shows them. */
function packsForApp() {
  return PACKS.map(p => ({ id: p.id, credits: p.credits, price: p.cents / 100, each: Math.round(p.cents / p.credits) / 100 }));
}

module.exports = { WELCOME, PACKS, packById, packsForApp, getCredits, spendCredit, refundCredit, logUse, grantFromCheckout, FREE_DAILY_TOTAL,
  HOUR_MINUTES, HOUR_WRITES, cleanTz, localDay, hasDailyHour, hourState, useDailyHour, giveBackHourWrite };
