// Push notifications to the phone (Web Push through the app's service worker).
//
// Off until the keys are set. Alexander creates them once with
//   node -e "console.log(require('web-push').generateVAPIDKeys())"
// and puts them in Railway as VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_SUBJECT (mailto:you@…).
// Members turn pushes on per device in Account → Notifications. Today only live-call
// notifications are pushed (new call, reminder before it starts, time changed, cancelled, replay).
// The table is created at startup, like the live-call tables. Nothing existing is changed.

const prisma = require('./db');

let webpush = null;
try { webpush = require('web-push'); } catch (e) { webpush = null; }

const DDL = [
  `CREATE TABLE IF NOT EXISTS "PushSubscription" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "endpoint" TEXT NOT NULL,
    "p256dh" TEXT NOT NULL,
    "auth" TEXT NOT NULL,
    "device" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PushSubscription_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "PushSubscription_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "PushSubscription_endpoint_key" ON "PushSubscription"("endpoint")`,
  `CREATE INDEX IF NOT EXISTS "PushSubscription_userId_idx" ON "PushSubscription"("userId")`,
];

let ready = false;
async function ensurePushTable() {
  for (let attempt = 0; attempt < 3 && !ready; attempt++) {
    try {
      for (const sql of DDL) await prisma.$executeRawUnsafe(sql);
      ready = true;
      console.log('Push table ready' + (isConfigured() ? '.' : ' (pushes are off until the VAPID keys are set).'));
    } catch (err) {
      console.error('Push table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return ready;
}

function isConfigured() {
  return !!(webpush && process.env.VAPID_PUBLIC_KEY && process.env.VAPID_PRIVATE_KEY);
}
function publicKey() { return isConfigured() ? process.env.VAPID_PUBLIC_KEY.trim() : null; }
function isReady() { return ready; }

let vapidSet = false;
function setupVapid() {
  if (vapidSet || !isConfigured()) return;
  const subject = (process.env.VAPID_SUBJECT || '').trim() || 'https://theguide.company';
  webpush.setVapidDetails(subject, process.env.VAPID_PUBLIC_KEY.trim(), process.env.VAPID_PRIVATE_KEY.trim());
  vapidSet = true;
}

// Which in-app notifications also go to the phone.
const PUSHED_TYPES = new Set(['live_new', 'live_soon', 'live_changed', 'live_cancelled', 'live_replay']);
function shouldPush(type) { return PUSHED_TYPES.has(type); }

function linkToUrl(link) {
  if (!link || typeof link !== 'object') return '/';
  if (link.view === 'live') return '/?open=live';
  if (link.view) return '/?open=' + encodeURIComponent(String(link.view).slice(0, 30));
  return '/';
}

// Send one notification to every device the given members turned pushes on for.
// Dead subscriptions (the member turned them off in the browser, or the browser forgot them) are removed.
async function sendToUsers(userIds, { title, body, link, tag }) {
  if (!ready || !isConfigured() || !userIds || !userIds.length) return 0;
  setupVapid();
  const ids = [...new Set(userIds)].slice(0, 5000);
  const rows = await prisma.$queryRawUnsafe(
    `SELECT "id", "endpoint", "p256dh", "auth" FROM "PushSubscription" WHERE "userId" = ANY($1::text[])`, ids);
  if (!rows.length) return 0;
  const payload = JSON.stringify({ title: String(title || 'The Guide').slice(0, 120), body: String(body || '').slice(0, 300),
                                   url: linkToUrl(link), tag: tag || undefined });
  let sent = 0;
  const dead = [];
  await Promise.all(rows.map(async (s) => {
    try {
      await webpush.sendNotification({ endpoint: s.endpoint, keys: { p256dh: s.p256dh, auth: s.auth } }, payload, { TTL: 60 * 60 });
      sent++;
    } catch (err) {
      if (err && (err.statusCode === 404 || err.statusCode === 410)) dead.push(s.id);
      else console.error('[push] send failed:', err && err.statusCode, err && err.message);
    }
  }));
  if (dead.length) {
    try { await prisma.$executeRawUnsafe(`DELETE FROM "PushSubscription" WHERE "id" = ANY($1::text[])`, dead); } catch (e) {}
  }
  return sent;
}

module.exports = { ensurePushTable, isConfigured, isReady, publicKey, shouldPush, sendToUsers, linkToUrl };
