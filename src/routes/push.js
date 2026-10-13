// Push notifications: the app asks for the public key, then registers this device's subscription.
const express = require('express');
const crypto = require('crypto');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const push = require('../push');

const router = express.Router();
router.use(requireAuth);
router.use(rateLimit({ windowMs: 15 * 60 * 1000, max: 60, standardHeaders: true, legacyHeaders: false,
                       message: { error: 'Too many requests. Please try again shortly.' } }));

function cleanEndpoint(v) {
  const s = String(v == null ? '' : v).trim();
  if (s.length > 2000 || !/^https:\/\//i.test(s)) return null;
  try { const u = new URL(s); return u.username || u.password ? null : s; } catch (e) { return null; }
}
function cleanKey(v) {
  const s = String(v == null ? '' : v).trim();
  return /^[A-Za-z0-9_=-]{10,400}$/.test(s) ? s : null;
}

// ---------- GET /api/push/key ----------
// Whether pushes are available, the key the browser needs, and whether this device is already registered.
router.get('/key', async (req, res) => {
  const enabled = push.isReady() && push.isConfigured();
  let devices = 0;
  if (enabled) {
    const rows = await prisma.$queryRawUnsafe(`SELECT count(*)::int AS n FROM "PushSubscription" WHERE "userId" = $1::text`, req.user.id);
    devices = rows[0] ? rows[0].n : 0;
  }
  res.set('Cache-Control', 'no-store');
  res.json({ enabled, publicKey: enabled ? push.publicKey() : null, devices });
});

// ---------- POST /api/push/subscribe ----------
router.post('/subscribe', async (req, res) => {
  if (!push.isReady() || !push.isConfigured()) return res.status(503).json({ error: 'Push notifications are not switched on yet.' });
  const sub = (req.body || {}).subscription || {};
  const endpoint = cleanEndpoint(sub.endpoint);
  const p256dh = cleanKey(sub.keys && sub.keys.p256dh), auth = cleanKey(sub.keys && sub.keys.auth);
  if (!endpoint || !p256dh || !auth) return res.status(400).json({ error: 'That does not look like a push subscription.' });
  const device = String((req.body || {}).device || '').replace(/\s+/g, ' ').trim().slice(0, 80) || null;
  const count = await prisma.$queryRawUnsafe(`SELECT count(*)::int AS n FROM "PushSubscription" WHERE "userId" = $1::text`, req.user.id);
  const existing = await prisma.$queryRawUnsafe(`SELECT "userId" FROM "PushSubscription" WHERE "endpoint" = $1::text`, endpoint);
  if (!existing[0] && count[0].n >= 10) return res.status(400).json({ error: 'You can have pushes on up to 10 devices. Turn one off first.' });
  // the same browser can only belong to one account: whoever registers it last owns it
  await prisma.$executeRawUnsafe(
    `INSERT INTO "PushSubscription" ("id","userId","endpoint","p256dh","auth","device") VALUES ($1::text,$2::text,$3::text,$4::text,$5::text,$6::text)
     ON CONFLICT ("endpoint") DO UPDATE SET "userId" = EXCLUDED."userId", "p256dh" = EXCLUDED."p256dh", "auth" = EXCLUDED."auth", "device" = EXCLUDED."device"`,
    crypto.randomUUID(), req.user.id, endpoint, p256dh, auth, device);
  res.status(201).json({ ok: true });
});

// ---------- DELETE /api/push/subscribe ----------
router.delete('/subscribe', async (req, res) => {
  const endpoint = cleanEndpoint((req.body || {}).endpoint);
  if (!endpoint) return res.status(400).json({ error: 'Which device?' });
  await prisma.$executeRawUnsafe(`DELETE FROM "PushSubscription" WHERE "endpoint" = $1::text AND "userId" = $2::text`, endpoint, req.user.id);
  res.json({ ok: true });
});

// ---------- POST /api/push/test ---------- (a test push to this member's own devices)
router.post('/test', async (req, res) => {
  if (!push.isReady() || !push.isConfigured()) return res.status(503).json({ error: 'Push notifications are not switched on yet.' });
  const sent = await push.sendToUsers([req.user.id], { title: 'The Guide', body: 'Pushes are on. You will hear about live calls here.', link: { view: 'live' }, tag: 'test' });
  res.json({ sent });
});

module.exports = router;
