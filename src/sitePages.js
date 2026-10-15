// The public side of member websites: theguide.company/s/<address> and its request form.
// No login. Mounted in src/index.js before CORS, because the form is a plain HTML form (it works
// without any script) and browsers send it from the page's own address.
// See src/sites.js for what a member site is.
const express = require('express');
const crypto = require('crypto');
const prisma = require('./db');
const { isProUser } = require('./pro');
const { state, oneLine, cleanRequest, renderSitePage, renderMissingPage } = require('./sites');

const REQUESTS_PER_SITE_PER_DAY = 30;

// Netlify passes /s/* through to this server, so every visitor arrives from one of Netlify's addresses.
// Netlify puts the visitor's own address in this header; fall back to the connection when it's missing.
function visitorKey(req) {
  return oneLine(req.get('x-nf-client-connection-ip') || req.ip || '', 64);
}

// A small in-memory limiter: at most `max` hits per key in `windowMs`. Good enough for one server;
// the per-page daily cap below is the real backstop against a flood of form posts.
function limiter(max, windowMs) {
  const hits = new Map();
  setInterval(() => {
    const cut = Date.now() - windowMs;
    for (const [k, list] of hits) { const keep = list.filter(t => t > cut); if (keep.length) hits.set(k, keep); else hits.delete(k); }
  }, windowMs).unref();
  return (key) => {
    const now = Date.now(), cut = now - windowMs;
    const list = (hits.get(key) || []).filter(t => t > cut);
    if (list.length >= max) { hits.set(key, list); return false; }
    list.push(now); hits.set(key, list);
    return true;
  };
}
const viewAllowed = limiter(120, 60 * 1000);
const postAllowed = limiter(6, 60 * 60 * 1000);

const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$/;

/** The site for an address, and whether this visit may see it (live and Pro, or the owner's preview link). */
async function findSite(slug, previewKey) {
  if (!state.ready || !SLUG_RE.test(slug)) return null;
  const rows = await prisma.$queryRawUnsafe(
    `SELECT "id", "userId", "slug", "previewKey", "data", "published" FROM "MemberSite" WHERE "slug" = $1::text`, slug);
  const site = rows[0];
  if (!site) return null;
  const preview = !!previewKey && previewKey.length >= 16 && crypto.timingSafeEqual(
    crypto.createHash('sha256').update(String(previewKey)).digest(), crypto.createHash('sha256').update(site.previewKey).digest());
  if (preview) return { site, preview: true };
  if (!site.published) return null;
  if (!(await isProUser(site.userId))) return null;
  return { site, preview: false };
}

function send(res, status, html, cache) {
  res.status(status).set({ 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': cache || 'no-store' }).send(html);
}

const pages = express.Router();

// ---------- GET /s/:slug ----------
pages.get('/:slug', async (req, res) => {
  if (!viewAllowed(visitorKey(req))) return send(res, 429, renderMissingPage());
  const slug = String(req.params.slug || '').toLowerCase();
  const found = await findSite(slug, typeof req.query.preview === 'string' ? req.query.preview : '');
  if (!found) return send(res, 404, renderMissingPage(), 'public, max-age=30');
  const { site, preview } = found;
  send(res, 200, renderSitePage(site, { preview, previewKey: preview ? site.previewKey : '', sent: req.query.sent === '1' }),
    preview || req.query.sent ? 'no-store' : 'public, max-age=60');
});

// ---------- POST /s/:slug/request ----------
// A visitor asking for a quote. Plain form post; the answer is the page again (with a thank-you, or
// what to fix). Bots that fill the hidden "website" box get the thank-you and nothing is stored.
pages.post('/:slug/request', express.urlencoded({ extended: false, limit: '8kb' }), async (req, res) => {
  const slug = String(req.params.slug || '').toLowerCase();
  const previewKey = typeof req.query.preview === 'string' ? req.query.preview : '';
  const found = await findSite(slug, previewKey);
  if (!found) return send(res, 404, renderMissingPage());
  const { site, preview } = found;
  const again = (extra) => send(res, 200, renderSitePage(site, Object.assign({ preview, previewKey: preview ? site.previewKey : '' }, extra)));
  const back = `/s/${site.slug}?${preview ? `preview=${encodeURIComponent(site.previewKey)}&` : ''}sent=1#ask`;

  const body = req.body || {};
  if (oneLine(body.website, 200)) return res.redirect(303, back);
  const r = cleanRequest(body);
  if (r.error) return again({ error: r.error, form: r });
  if (!postAllowed(visitorKey(req) + '|' + site.id)) {
    return again({ error: 'Too many requests from here. Please try again later, or call or email instead.', form: r });
  }
  const today = await prisma.$queryRawUnsafe(
    `SELECT COUNT(*)::int AS n FROM "SiteRequest" WHERE "siteId" = $1::text AND "createdAt" > NOW() - INTERVAL '1 day'`, site.id);
  if ((today[0] && today[0].n) >= REQUESTS_PER_SITE_PER_DAY) {
    return again({ error: 'This page has had a lot of requests today. Please try again tomorrow, or call or email instead.', form: r });
  }
  await prisma.$executeRawUnsafe(
    `INSERT INTO "SiteRequest" ("id", "siteId", "name", "contact", "service", "message") VALUES ($1::text, $2::text, $3::text, $4::text, $5::text, $6::text)`,
    crypto.randomUUID(), site.id, r.name, r.contact, r.service || null, r.message || null);
  try {
    await prisma.notification.create({
      data: {
        userId: site.userId,
        type: 'site_request',
        title: 'New request from your website',
        body: `${r.name} asked about ${r.service && r.service !== 'Something else' ? r.service : 'your services'}.`,
        link: { view: 'website' },
      },
    });
  } catch (err) {
    console.error('[sites] could not add the bell notification:', err.message);
  }
  res.redirect(303, back);
});

module.exports = { pages, findSite };
