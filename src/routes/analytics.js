// Analytics API
//   Public (called by the app itself):
//     POST /api/analytics/collect   page views + funnel events, with traffic source
//     POST /api/analytics/ping      "still here" heartbeat for the live online count
//   Staff (owner, plus anyone listed in MARKETING_EMAILS):
//     GET  /api/analytics/access            which dashboards this account can open
//     GET  /api/analytics/live              Server-Sent Events stream — instant updates
//     GET  /api/analytics/marketing/report  traffic sources, campaigns, conversions
//   Owner only:
//     GET  /api/analytics/owner/overview    users, revenue, engagement, growth

const express = require('express');
const rateLimit = require('express-rate-limit');
const { requireAuth, optionalAuth } = require('../middleware/auth');
const A = require('../analytics');

const router = express.Router();

const collectLimiter = rateLimit({
  windowMs: 60 * 1000, max: 120, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many requests.' },
});
const pingLimiter = rateLimit({
  windowMs: 60 * 1000, max: 30, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many requests.' },
});
const staffLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, max: 400, standardHeaders: true, legacyHeaders: false,
  message: { error: 'Too many requests. Please try again shortly.' },
});

const EVENT_TYPES = new Set(['pageview', 'paywall', 'checkout']);

// The app sends these as text/plain (navigator.sendBeacon) so the browser
// skips the CORS preflight and still delivers them while a tab is closing.
const beaconBody = [
  express.text({ type: 'text/plain', limit: '8kb' }),
  (req, res, next) => {
    if (typeof req.body === 'string') {
      try { req.body = JSON.parse(req.body); } catch (e) { req.body = {}; }
    }
    if (!req.body || typeof req.body !== 'object') req.body = {};
    next();
  },
];

// ---------- POST /collect ----------
// Body: { v: visitorId, s: sessionId, ns: newSession?, t: type, p: path, lp: landingPath,
//         touch: { src, med, cmp, trm, cnt, ck: {gclid...}, ref, rc }, tz, tch: touchScreen? }
// Beacons are "no-cors" requests; helmet's same-origin resource policy would
// make the browser log a (harmless) blocked-response error for each one.
const beaconHeaders = (res) => res.set('Cross-Origin-Resource-Policy', 'cross-origin');

router.post('/collect', collectLimiter, beaconBody, optionalAuth, (req, res) => {
  beaconHeaders(res);
  res.status(204).end(); // never make the visitor wait on analytics
  try {
    const b = req.body || {};
    const ua = req.get('user-agent') || '';
    if (A.isBot(ua)) return;
    if (req.user && A.isStaffEmail(req.user.email)) return;
    const visitorId = A.s(b.v, 64), sessionId = A.s(b.s, 64);
    if (!visitorId || !sessionId || !EVENT_TYPES.has(b.t)) return;
    const tz = A.validTz(b.tz);
    const cls = A.classify(b.touch, ua);
    const path = A.s(b.p, 200);
    const dev = A.parseUA(ua, !!b.tch);
    const country = A.countryFromTz(tz);
    A.recordEvent(b.t, {
      cls, visitorId, sessionId, userId: req.user ? req.user.id : null, path, ua, touchScreen: !!b.tch, tz,
      landing: A.s(b.lp, 200), newSession: !!b.ns, email: req.user ? req.user.email : null,
    });
    A.touchPresence(visitorId, {
      sessionId, userId: req.user ? req.user.id : null, path, channel: cls.channel, source: cls.source,
      device: dev.device, country,
    });
  } catch (err) {
    console.error('collect failed:', err.message);
  }
});

// ---------- POST /ping ----------
// Body: { v, s, p, leave?, touch?, tz?, tch? } — keeps the "online now" count exact.
router.post('/ping', pingLimiter, beaconBody, optionalAuth, (req, res) => {
  beaconHeaders(res);
  res.status(204).end();
  try {
    const b = req.body || {};
    const ua = req.get('user-agent') || '';
    if (A.isBot(ua) || (req.user && A.isStaffEmail(req.user.email))) return;
    const visitorId = A.s(b.v, 64);
    if (!visitorId) return;
    if (b.leave) { A.leavePresence(visitorId); return; }
    const cls = A.classify(b.touch, ua);
    A.touchPresence(visitorId, {
      sessionId: A.s(b.s, 64), userId: req.user ? req.user.id : null, path: A.s(b.p, 200),
      channel: cls.channel, source: cls.source, device: A.parseUA(ua, !!b.tch).device, country: A.countryFromTz(A.validTz(b.tz)),
    });
  } catch (err) {
    console.error('ping failed:', err.message);
  }
});

// ---------- staff routes ----------
function requireRole(kind) {
  return (req, res, next) => {
    const role = A.roleFor(req.user.email);
    if (kind === 'owner' ? role.owner : role.marketing) { req.role = role; return next(); }
    res.status(403).json({ error: 'Not authorized.' });
  };
}

router.get('/access', staffLimiter, requireAuth, (req, res) => {
  res.json(A.roleFor(req.user.email));
});

router.get('/owner/overview', staffLimiter, requireAuth, requireRole('owner'), async (req, res) => {
  try {
    res.json(await A.ownerOverview(req.query.tz));
  } catch (err) {
    console.error('owner overview failed:', err);
    res.status(500).json({ error: 'Could not load the dashboard.' });
  }
});

router.get('/marketing/report', staffLimiter, requireAuth, requireRole('marketing'), async (req, res) => {
  try {
    res.json(await A.marketingReport({ range: req.query.range, tz: req.query.tz, model: req.query.model }));
  } catch (err) {
    console.error('marketing report failed:', err);
    res.status(500).json({ error: 'Could not load the report.' });
  }
});

// ---------- GET /live (Server-Sent Events) ----------
// The browser reads this with fetch() so it can send the auth header. Every
// tracked event is pushed the moment it happens; a fresh snapshot of the
// counters follows every 2 seconds.
const subs = new Set();
let loop = null;
let pvPending = 0;

function send(sub, event, data) {
  if (!sub.alive) return;
  try { sub.res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`); } catch (e) { sub.alive = false; }
}

A.bus.on('event', (item) => { for (const sub of subs) send(sub, 'event', A.scrubFor(sub.role, item)); });
A.bus.on('pv', () => { pvPending++; });

let ticking = false;
async function tick() {
  if (!subs.size) { clearInterval(loop); loop = null; return; }
  if (ticking) return;
  ticking = true;
  try { await tickInner(); } finally { ticking = false; }
}
async function tickInner() {
  if (pvPending) { const n = pvPending; pvPending = 0; for (const sub of subs) send(sub, 'pv', { n }); }
  const now = Date.now();
  const groups = new Map();
  for (const sub of subs) {
    if (now - (sub.lastSnap || 0) < 2000) continue;
    const key = `${sub.tz}|${sub.role.owner ? 'o' : 'm'}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(sub);
  }
  for (const [, list] of groups) {
    try {
      const snap = await A.liveSnapshot(list[0].tz, list[0].role);
      for (const sub of list) { sub.lastSnap = now; send(sub, 'snapshot', snap); }
    } catch (err) {
      console.error('live snapshot failed:', err.message);
    }
  }
}

router.get('/live', staffLimiter, requireAuth, requireRole('marketing'), async (req, res) => {
  const tz = A.validTz(req.query.tz);
  res.status(200).set({
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.flushHeaders();
  res.write('retry: 1500\n\n');
  const sub = { res, role: req.role, tz, alive: true, lastSnap: 0 };
  subs.add(sub);
  // Hosting proxies don't love hour-long requests; end politely every few
  // minutes and the dashboard reconnects instantly.
  const life = setTimeout(() => { try { res.end(); } catch (e) {} }, 4 * 60 * 1000);
  req.on('close', () => { sub.alive = false; subs.delete(sub); clearTimeout(life); });
  try {
    sub.lastSnap = Date.now();
    send(sub, 'snapshot', await A.liveSnapshot(tz, req.role));
  } catch (err) {
    console.error('live first snapshot failed:', err.message);
    send(sub, 'oops', { message: 'Live data is warming up — retrying.' });
  }
  if (!loop) loop = setInterval(tick, 500);
});

module.exports = router;
