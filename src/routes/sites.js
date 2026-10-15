// The member's side of member websites (account menu → My website): read and save the page, put it
// live, and look after the requests visitors send through it. See src/sites.js.
const express = require('express');
const crypto = require('crypto');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { isProUser } = require('../pro');
const { SITE_ORIGIN, COLORS, state, oneLine, slugify, slugProblem, cleanSiteData, publishProblem } = require('../sites');

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

// ---------- GET /api/sites/mine ----------
// The member's page (or null), the latest requests from it, and the colours a page can have.
router.get('/mine', async (req, res) => {
  res.set('Cache-Control', 'no-store');
  const [site, pro] = await Promise.all([mySite(req.user.id), isProUser(req.user.id)]);
  if (!site) return res.json({ site: null, requests: [], unseen: 0, pro, colors: COLORS });
  const requests = await prisma.$queryRawUnsafe(
    `SELECT * FROM "SiteRequest" WHERE "siteId" = $1::text ORDER BY "createdAt" DESC LIMIT 100`, site.id);
  res.json({ site: siteShape(site), requests: requests.map(requestShape), unseen: requests.filter(r => !r.seen).length, pro, colors: COLORS });
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
