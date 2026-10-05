// Meta (Facebook / Instagram) ads measurement — the Conversions API.
//
// The browser pixel in the app reports PageView, CompleteRegistration and
// InitiateCheckout. This module sends the same events from the server (with
// the same event_id, so Meta counts each one once) and adds Purchase from the
// Stripe webhook. That lets Meta optimise ads toward people who actually sign
// up and pay, even when an ad blocker or iOS privacy settings hide the pixel.
//
// Off until META_PIXEL_ID and META_CAPI_TOKEN are set. Only visitors whose
// browser allowed ad measurement are ever sent (visitors in Europe/UK are
// asked first; anyone can turn it off in the app's privacy settings).
// Emails are SHA-256 hashed before they leave this server, as Meta requires.
const crypto = require('crypto');
const prisma = require('./db');
const { isStaffEmail } = require('./analytics');

const cfg = () => ({
  pixel: String(process.env.META_PIXEL_ID || '').trim(),
  token: String(process.env.META_CAPI_TOKEN || '').trim(),
  test: String(process.env.META_TEST_EVENT_CODE || '').trim(),
  version: String(process.env.META_API_VERSION || 'v26.0').trim(),
});
const pixelId = () => (/^\d{6,20}$/.test(cfg().pixel) ? cfg().pixel : '');
const enabled = () => !!(pixelId() && cfg().token);
const PRICES = { monthly: 28.99, yearly: 325.99 };

const sha = (v) => crypto.createHash('sha256').update(String(v).trim().toLowerCase()).digest('hex');
const printable = (v, max) => (typeof v === 'string' && v.length > 0 && v.length <= max && /^[\x20-\x7E]+$/.test(v) ? v : undefined);
const okFbp = (v) => { const x = printable(v, 120); return x && /^fb\.\d\.\d{10,16}\.\d{1,30}$/.test(x) ? x : undefined; };
const okFbc = (v) => { const x = printable(v, 600); return x && /^fb\.\d\.\d{10,16}\.[\w-]{10,500}$/.test(x) ? x : undefined; };
const okEventId = (v) => { const x = printable(v, 100); return x && /^[\w.:-]{6,100}$/.test(x) ? x : undefined; };
const siteUrl = () => String(process.env.APP_URL || '').replace(/\/+$/, '') + '/';

/** Browser info that rides along with signup / checkout: { eid, fbp, fbc, ok }. */
function fromBrowser(meta) {
  const m = meta && typeof meta === 'object' && !Array.isArray(meta) ? meta : {};
  return { eventId: okEventId(m.eid), fbp: okFbp(m.fbp), fbc: okFbc(m.fbc), consent: m.ok === true };
}

let ready = false;
async function ensureMetaTable() {
  try {
    await prisma.$executeRawUnsafe(`CREATE TABLE IF NOT EXISTS "AdMatch" (
      "userId" TEXT NOT NULL,
      "fbp" TEXT,
      "fbc" TEXT,
      "consent" BOOLEAN NOT NULL DEFAULT false,
      "ua" TEXT,
      "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT "AdMatch_pkey" PRIMARY KEY ("userId"))`);
    ready = true;
  } catch (err) {
    console.error('AdMatch table setup failed:', err.message);
  }
}

// Keeps the browser IDs + consent for a user so a later Purchase (which
// arrives from Stripe, not the browser) can still be matched to the ad.
async function remember(userId, { fbp, fbc, consent, ua }) {
  if (!ready || !userId) return;
  if (!consent) { fbp = null; fbc = null; ua = null; } // said no: keep only the "no"
  await prisma.$executeRawUnsafe(
    `INSERT INTO "AdMatch" ("userId","fbp","fbc","consent","ua","updatedAt")
     VALUES ($1::text, $2::text, $3::text, $4::boolean, $5::text, (now() at time zone 'UTC'))
     ON CONFLICT ("userId") DO UPDATE SET
       "fbp" = CASE WHEN EXCLUDED."consent" THEN COALESCE(EXCLUDED."fbp", "AdMatch"."fbp") END,
       "fbc" = CASE WHEN EXCLUDED."consent" THEN COALESCE(EXCLUDED."fbc", "AdMatch"."fbc") END,
       "consent" = EXCLUDED."consent",
       "ua" = CASE WHEN EXCLUDED."consent" THEN COALESCE(EXCLUDED."ua", "AdMatch"."ua") END,
       "updatedAt" = EXCLUDED."updatedAt"`,
    userId, fbp || null, fbc || null, !!consent, ua || null);
}

function userData({ email, userId, ip, ua, fbp, fbc }) {
  const u = {};
  if (email) u.em = [sha(email)];
  if (userId) u.external_id = [sha(userId)];
  if (ip) u.client_ip_address = ip;
  if (ua) u.client_user_agent = ua;
  if (fbp) u.fbp = fbp;
  if (fbc) u.fbc = fbc;
  return u;
}

async function send(event) {
  const c = cfg();
  const body = { data: [event] };
  if (c.test) body.test_event_code = c.test;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 6000);
  try {
    const res = await fetch(`https://graph.facebook.com/${c.version}/${pixelId()}/events?access_token=${encodeURIComponent(c.token)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctl.signal,
    });
    if (!res.ok) console.error('Meta Conversions API error', res.status, (await res.text()).slice(0, 300));
  } catch (err) {
    console.error('Meta Conversions API request failed:', err.message);
  } finally {
    clearTimeout(timer);
  }
}

const now = () => Math.floor(Date.now() / 1000);
const clientUa = (req) => printable(req.get('user-agent') || '', 512);

// ---- events ----
async function trackSignup(user, body, req) {
  try {
    if (!enabled() || !user || isStaffEmail(user.email)) return;
    const a = body && typeof body.attribution === 'object' && body.attribution ? body.attribution : {};
    const m = fromBrowser(a.meta);
    const ua = clientUa(req);
    await remember(user.id, { ...m, ua });
    if (!m.consent) return;
    await send({
      event_name: 'CompleteRegistration', event_time: now(), event_id: m.eventId || `reg_${user.id}`,
      action_source: 'website', event_source_url: siteUrl(),
      user_data: userData({ email: user.email, userId: user.id, ip: req.ip, ua, fbp: m.fbp, fbc: m.fbc }),
      custom_data: { status: 'registered' },
    });
  } catch (err) {
    console.error('Meta signup event failed:', err.message);
  }
}

async function trackCheckout(user, plan, body, req) {
  try {
    if (!enabled() || !user || isStaffEmail(user.email)) return;
    const m = fromBrowser(body && body.meta);
    const ua = clientUa(req);
    await remember(user.id, { ...m, ua });
    if (!m.consent) return;
    await send({
      event_name: 'InitiateCheckout', event_time: now(), event_id: m.eventId || `chk_${user.id}_${now()}`,
      action_source: 'website', event_source_url: siteUrl(),
      user_data: userData({ email: user.email, userId: user.id, ip: req.ip, ua, fbp: m.fbp, fbc: m.fbc }),
      custom_data: { value: PRICES[plan] || PRICES.monthly, currency: 'USD', content_name: `Pro ${plan}` },
    });
  } catch (err) {
    console.error('Meta checkout event failed:', err.message);
  }
}

// From the Stripe webhook. Only for users whose browser allowed ad measurement.
async function trackPurchase(userId, { email, value, currency, plan, eventId }) {
  try {
    if (!enabled() || !userId || !ready || isStaffEmail(email)) return;
    const rows = await prisma.$queryRawUnsafe(`SELECT "fbp","fbc","consent","ua" FROM "AdMatch" WHERE "userId" = $1::text`, userId);
    const r = rows[0];
    if (!r || !r.consent) return;
    await send({
      event_name: 'Purchase', event_time: now(), event_id: eventId || `buy_${userId}_${now()}`,
      action_source: 'website', event_source_url: siteUrl(),
      user_data: userData({ email, userId, ua: r.ua, fbp: r.fbp, fbc: r.fbc }),
      custom_data: { value: typeof value === 'number' ? value : (PRICES[plan] || PRICES.monthly), currency: String(currency || 'usd').toUpperCase(), content_name: `Pro ${plan || 'monthly'}` },
    });
  } catch (err) {
    console.error('Meta purchase event failed:', err.message);
  }
}

module.exports = { ensureMetaTable, pixelId, enabled, trackSignup, trackCheckout, trackPurchase, fromBrowser };
