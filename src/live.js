// Live calls: scheduled group calls hosted by the owner and by experts the owner approves.
// Pro members can join. Members get an in-app reminder shortly before a call they said they'd come to.
//
// Design notes
// - Tables are created on startup with CREATE TABLE IF NOT EXISTS (same approach as analytics.js), so
//   this works no matter how the database schema is normally applied. The same tables are also
//   declared in prisma/schema.prisma so `prisma db push` keeps them instead of treating them as strays.
// - Only new tables. Nothing that already exists is changed or deleted.
// - All times are stored in UTC.
// - The call link (joinUrl) is only handed to Pro members (and the host/owner), and only shortly
//   before the call starts. See routes/live.js.

const cron = require('node-cron');
const prisma = require('./db');
const { notifyUsers } = require('./notifications');

const DDL = [
  `CREATE TABLE IF NOT EXISTS "LiveHost" (
    "email" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "headline" TEXT,
    "addedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "LiveHost_pkey" PRIMARY KEY ("email")
  )`,
  `CREATE TABLE IF NOT EXISTS "LiveCall" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT,
    "nicheId" TEXT,
    "hostEmail" TEXT NOT NULL,
    "hostName" TEXT NOT NULL,
    "startsAt" TIMESTAMP(3) NOT NULL,
    "durationMin" INTEGER NOT NULL DEFAULT 45,
    "joinUrl" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'scheduled',
    "remindedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "LiveCall_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE INDEX IF NOT EXISTS "LiveCall_startsAt_idx" ON "LiveCall"("startsAt")`,
  // added later: a replay link the host can add after the call (only ever adds a column)
  `ALTER TABLE "LiveCall" ADD COLUMN IF NOT EXISTS "replayUrl" TEXT`,
  `CREATE TABLE IF NOT EXISTS "LiveRsvp" (
    "callId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "LiveRsvp_pkey" PRIMARY KEY ("callId", "userId"),
    CONSTRAINT "LiveRsvp_callId_fkey" FOREIGN KEY ("callId") REFERENCES "LiveCall"("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "LiveRsvp_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  // questions members send in before a call, for the host to answer live
  `CREATE TABLE IF NOT EXISTS "LiveQuestion" (
    "id" TEXT NOT NULL,
    "callId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "body" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "LiveQuestion_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "LiveQuestion_callId_fkey" FOREIGN KEY ("callId") REFERENCES "LiveCall"("id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "LiveQuestion_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  `CREATE INDEX IF NOT EXISTS "LiveQuestion_callId_idx" ON "LiveQuestion"("callId")`,
];

let ready = false;
async function ensureLiveTables() {
  for (let attempt = 0; attempt < 3 && !ready; attempt++) {
    try {
      for (const sql of DDL) await prisma.$executeRawUnsafe(sql);
      ready = true;
      console.log('Live call tables ready.');
    } catch (err) {
      // Two instances starting at once can race on CREATE ... IF NOT EXISTS; a short retry settles it.
      console.error('Live call table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return ready;
}
function isReady() { return ready; }

// ---------------------------------------------------------------- who is asking
function listEnv(name) {
  return (process.env[name] || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}
function isOwnerEmail(email) {
  return !!(process.env.OWNER_EMAIL && String(email || '').toLowerCase() === process.env.OWNER_EMAIL.trim().toLowerCase());
}
// What the owner is called on a call when they host it themselves.
function ownerDisplayName() {
  return String(process.env.OWNER_NAME || 'The Guide team').trim().slice(0, 60) || 'The Guide team';
}

// Everything a route needs to know about the person asking: are they Pro (same rules as /api/account),
// the owner, or an approved host. Checked on the server on every request, never from anything the browser sends.
async function viewerFor(userId) {
  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: { id: true, email: true, isPro: true, bonusProUntil: true },
  });
  if (!user) return null;
  const email = user.email.toLowerCase();
  const owner = isOwnerEmail(email);
  const preview = listEnv('PREVIEW_EMAILS').includes(email);
  const pro = owner || preview || !!user.isPro || !!(user.bonusProUntil && user.bonusProUntil > new Date());
  let host = null;
  if (!owner) {
    const rows = await prisma.$queryRawUnsafe(
      `SELECT "email", "name", "headline" FROM "LiveHost" WHERE "email" = $1::text`, email);
    host = rows[0] || null;
  }
  return { id: user.id, email, owner, pro, host, canHost: owner || !!host };
}

// ---------------------------------------------------------------- reminders
// About 15 minutes before a call, everyone who tapped "Remind me" gets an in-app notification.
// The UPDATE claims each call exactly once, even if two copies of the server are running.
async function sendLiveReminders() {
  if (!ready) return;
  const claimed = await prisma.$queryRawUnsafe(
    `UPDATE "LiveCall" SET "remindedAt" = (now() at time zone 'UTC')
     WHERE "status" = 'scheduled' AND "remindedAt" IS NULL
       AND "startsAt" <= (now() at time zone 'UTC') + interval '15 minutes'
       AND "startsAt" > (now() at time zone 'UTC') - interval '5 minutes'
     RETURNING "id", "title", "hostName"`);
  for (const c of claimed) {
    const rows = await prisma.$queryRawUnsafe(`SELECT "userId" FROM "LiveRsvp" WHERE "callId" = $1::text`, c.id);
    await notifyUsers(rows.map(r => r.userId), {
      type: 'live_soon',
      title: `Starting soon: ${c.title}`,
      body: `Live with ${c.hostName} in about 15 minutes. Tap to join.`,
      link: { view: 'live' },
    });
  }
}

function scheduleLiveReminders() {
  cron.schedule('* * * * *', () => {
    sendLiveReminders().catch(err => console.error('[live] reminder run failed:', err.message));
  });
}

module.exports = {
  ensureLiveTables, isReady, viewerFor, isOwnerEmail, ownerDisplayName,
  sendLiveReminders, scheduleLiveReminders,
};
