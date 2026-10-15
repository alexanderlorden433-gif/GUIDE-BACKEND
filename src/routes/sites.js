// The member's side of member websites (account menu → My website): read and save the page, put it
// live, and look after the requests visitors send through it. See src/sites.js.
const express = require('express');
const crypto = require('crypto');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { isProUser } = require('../pro');
const { SITE_ORIGIN, COLORS, state, oneLine, slugify, slugProblem, cleanSiteData, publishProblem } = require('../sites');
const { writePage, currentModel } = require('../siteAi');
const credits = require('../siteCredits');
const { stripe, createCreditsCheckout } = require('../stripe');

const router = express.Router();
router.use(requireAuth);
router.use(rateLimit({ windowMs: 15 * 60 * 1000, max: 150, standardHeaders: true, legacyHeaders: false,
                       message: { error: 'Too many requests. Please try again shortly.' } }));
router.use((req, res, next) => {
  if (!state.ready) return res.status(503).json({ error: 'Websites are not ready yet. Try again in a minute.' });
  next();
});

function siteShape(s) {
  return { slug: s.slug, url: `${SITE_ORIGIN}/s/${s.slug}`, previewKey: s.previewKey, published: !!s.published,
           data: cleanSiteData(s.data), updatedAt: s.updatedAt };
}
function requestShape(r) {
  return { id: r.id, name: r.name, contact: r.contact, service: r.service || '', message: r.message || '', seen: !!r.seen, createdAt: r.createdAt };
}
async function mySite(userId) {
  const rows = await prisma.$queryRawUnsafe(`SELECT * FROM "MemberSite" WHERE "userId" = $1::text`, userId);
  return rows[0] || null;
}

// ---------- GET /api/sites/mine?tz=America/Chicago ----------
// The member's page (or null), the latest requests from it, the colours a page can have, and the AI writer's
// state: credits, Pro's daily hour (worked out in the member's time zone), and the packs.
router.get('/mine', async (req, res) => {
  res.set('Cache-Control', 'no-store');
  const [site, pro, mine, hour] = await Promise.all([mySite(req.user.id), isProUser(req.user.id), credits.getCredits(req.user.id),
    credits.hourState(req.user.id, req.query.tz)]);
  const ai = { ready: !!process.env.ANTHROPIC_API_KEY, model: currentModel(), credits: mine, hour, packs: credits.packsForApp() };
  if (!site) return res.json({ site: null, requests: [], unseen: 0, pro, colors: COLORS, ai });
  const requests = await prisma.$queryRawUnsafe(
    `SELECT * FROM "SiteRequest" WHERE "siteId" = $1::text ORDER BY "createdAt" DESC LIMIT 100`, site.id);
  res.json({ site: siteShape(site), requests: requests.map(requestShape), unseen: requests.filter(r => !r.seen).length, pro, colors: COLORS, ai });
});

// ---------- POST /api/sites/ai ----------
// The AI writes the page {mode: "write"|"improve", description, draft, chapter: {name, description, tips}, lang, tz}.
// Free during a Pro member's daily AI hour, otherwise uses one AI credit. Answers {draft, tips, model, paidWith,
// credits, hour}; nothing is saved here, the app shows it in the editor first. Out of both: 402 {buy: true, …}.
// A write takes up to a minute, so on top of the daily limit there's a short-term one per member.
const aiBurst = rateLimit({ windowMs: 10 * 60 * 1000, max: 8, standardHeaders: true, legacyHeaders: false,
                            keyGenerator: (req) => 'site-ai:' + req.user.id,
                            message: { error: 'Too many tries in a row. Wait a few minutes, then try again.' } });
router.post('/ai', aiBurst, async (req, res) => {
  const b = req.body || {};
  const r = await writePage({ userId: req.user.id, mode: b.mode, description: b.description, draft: b.draft,
                              chapter: b.chapter, lang: b.lang, tz: b.tz });
  res.status(r.status).json(r.body);
});

// ---------- POST /api/sites/credits/checkout ----------
// {pack: "small"|"medium"|"large"} → {url} of a Stripe Checkout page for that pack of AI credits.
router.post('/credits/checkout', async (req, res) => {
  const pack = credits.packById((req.body || {}).pack);
  if (!pack) return res.status(400).json({ error: 'Pick a pack.' });
  const user = await prisma.user.findUnique({ where: { id: req.user.id } });
  if (!user) return res.status(404).json({ error: 'Account not found.' });
  try {
    const session = await createCreditsCheckout({ user, pack });
    res.json({ url: session.url });
  } catch (err) {
    console.error('[credits] checkout error:', err.message);
    res.status(500).json({ error: 'Could not start checkout. Please try again.' });
  }
});

// ---------- POST /api/sites/credits/confirm ----------
// {session: "cs_…"} when the member comes back from checkout: adds the credits now rather than waiting for
// Stripe's webhook (whichever comes first adds them; the other finds them already added). Only the member who
// paid can confirm their own checkout. Answers {added, credits}.
router.post('/credits/confirm', async (req, res) => {
  const id = String((req.body || {}).session || '');
  if (!/^cs_(test|live)_[A-Za-z0-9]{10,200}$/.test(id)) return res.status(400).json({ error: 'That checkout link looks wrong.' });
  let session;
  try { session = await stripe.checkout.sessions.retrieve(id); }
  catch (err) { return res.status(404).json({ error: 'Checkout not found.' }); }
  if (!session.metadata || session.metadata.kind !== 'site_credits' || session.metadata.userId !== req.user.id) {
    return res.status(404).json({ error: 'Checkout not found.' });
  }
  const g = await credits.grantFromCheckout(session);
  if (!g.ok) return res.status(409).json({ error: 'The payment has not gone through yet. Your credits will show up as soon as it does.', credits: await credits.getCredits(req.user.id) });
  const pack = credits.packById(g.pack);
  res.json({ added: g.added, pack: pack ? pack.credits : 0, credits: await credits.getCredits(req.user.id) });
});

// ---------- PUT /api/sites/mine ----------
// Saves the page: {slug, data, published}. Anyone can save a draft; going live needs Pro.
router.put('/mine', async (req, res) => {
  const b = req.body || {};
  const data = cleanSiteData(b.data);
  const slug = slugify(b.slug || data.name);
  const problem = slugProblem(slug);
  if (problem) return res.status(400).json({ error: problem, field: 'slug' });
  const published = b.published === true;
  if (published) {
    if (!(await isProUser(req.user.id))) return res.status(403).json({ error: 'Putting your page live is part of Pro.', upgrade: true });
    const missing = publishProblem(data);
    if (missing) return res.status(400).json({ error: missing });
  }
  const taken = await prisma.$queryRawUnsafe(
    `SELECT "userId" FROM "MemberSite" WHERE "slug" = $1::text AND "userId" <> $2::text`, slug, req.user.id);
  if (taken[0]) return res.status(409).json({ error: 'That web address is taken. Try another one.', field: 'slug' });

  const existing = await mySite(req.user.id);
  try {
    if (existing) {
      await prisma.$executeRawUnsafe(
        `UPDATE "MemberSite" SET "slug" = $1::text, "data" = $2::jsonb, "published" = $3::boolean, "updatedAt" = CURRENT_TIMESTAMP WHERE "id" = $4::text`,
        slug, JSON.stringify(data), published, existing.id);
    } else {
      await prisma.$executeRawUnsafe(
        `INSERT INTO "MemberSite" ("id", "userId", "slug", "previewKey", "data", "published") VALUES ($1::text, $2::text, $3::text, $4::text, $5::jsonb, $6::boolean)`,
        crypto.randomUUID(), req.user.id, slug, crypto.randomBytes(18).toString('base64url'), JSON.stringify(data), published);
    }
  } catch (err) {
    // two members saving the same new address at the same moment: the unique index decides
    if (/unique|duplicate/i.test(err.message)) return res.status(409).json({ error: 'That web address is taken. Try another one.', field: 'slug' });
    throw err;
  }
  res.json({ site: siteShape(await mySite(req.user.id)) });
});

// ---------- PUT /api/sites/requests/:id ----------
// {seen: true|false}
router.put('/requests/:id', async (req, res) => {
  const site = await mySite(req.user.id);
  if (!site) return res.status(404).json({ error: 'Request not found.' });
  const n = await prisma.$executeRawUnsafe(
    `UPDATE "SiteRequest" SET "seen" = $1::boolean WHERE "id" = $2::text AND "siteId" = $3::text`,
    (req.body || {}).seen !== false, oneLine(req.params.id, 80), site.id);
  if (!n) return res.status(404).json({ error: 'Request not found.' });
  res.json({ ok: true });
});

// ---------- DELETE /api/sites/requests/:id ----------
router.delete('/requests/:id', async (req, res) => {
  const site = await mySite(req.user.id);
  if (!site) return res.status(404).json({ error: 'Request not found.' });
  const n = await prisma.$executeRawUnsafe(
    `DELETE FROM "SiteRequest" WHERE "id" = $1::text AND "siteId" = $2::text`, oneLine(req.params.id, 80), site.id);
  if (!n) return res.status(404).json({ error: 'Request not found.' });
  res.json({ ok: true });
});

module.exports = router;
