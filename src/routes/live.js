const express = require('express');
const crypto = require('crypto');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { notifyUser, notifyUsers } = require('../notifications');
const { ensureLiveTables, isReady, viewerFor, ownerDisplayName } = require('../live');

const router = express.Router();
router.use(requireAuth);

const liveLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 150,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(liveLimiter);

// The room opens this long before the start, and stays open this long after the planned end.
const OPENS_MIN_BEFORE = 10;
const STAYS_OPEN_MIN_AFTER = 30;

// Every route needs the tables and to know who is asking.
router.use(async (req, res, next) => {
  if (!isReady() && !(await ensureLiveTables())) {
    return res.status(503).json({ error: 'Live calls are starting up. Please try again in a minute.' });
  }
  req.viewer = await viewerFor(req.user.id);
  if (!req.viewer) return res.status(404).json({ error: 'Account not found.' });
  next();
});

// ---------------------------------------------------------------- cleaning what people type
// Same idea as analytics.js: no control characters and no lone half-emoji, which the database driver rejects.
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;
function oneLine(v, max) {
  return String(v == null ? '' : v).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, max).replace(LONE_SURROGATE, '');
}
function paragraphs(v, max) {
  return String(v == null ? '' : v).replace(/\r/g, '').replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, ' ')
    .replace(/\n{3,}/g, '\n\n').trim().slice(0, max).replace(LONE_SURROGATE, '');
}
function cleanUrl(v) {
  try {
    const u = new URL(String(v == null ? '' : v).trim());
    if (u.protocol !== 'https:' || u.username || u.password || !u.hostname.includes('.')) return null;
    return u.href.length <= 500 ? u.href : null;
  } catch (e) { return null; }
}
function cleanEmail(v) {
  const e = String(v == null ? '' : v).trim().toLowerCase();
  return e.length <= 200 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e) ? e : null;
}
function cleanNiche(v) {
  const s = String(v == null ? '' : v).trim();
  return /^[a-z0-9-]{1,60}$/i.test(s) ? s : null;
}

const ISO = `to_char(c."startsAt", 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')`;
const NOW_UTC = `(now() at time zone 'UTC')`;

async function findCall(id) {
  const rows = await prisma.$queryRawUnsafe(
    `SELECT c."id", c."title", c."description", c."nicheId", c."hostEmail", c."hostName", c."durationMin",
            c."joinUrl", c."replayUrl", c."status", ${ISO} AS "startsAt",
            (c."startsAt" - interval '${OPENS_MIN_BEFORE} minutes' <= ${NOW_UTC}
              AND c."startsAt" + (c."durationMin" + ${STAYS_OPEN_MIN_AFTER}) * interval '1 minute' > ${NOW_UTC}) AS "open",
            (c."startsAt" + (c."durationMin" + ${STAYS_OPEN_MIN_AFTER}) * interval '1 minute' > ${NOW_UTC}) AS "notOver",
            (c."startsAt" + c."durationMin" * interval '1 minute' <= ${NOW_UTC}) AS "ended"
     FROM "LiveCall" c WHERE c."id" = $1::text`, String(id).slice(0, 80));
  return rows[0] || null;
}

function proOnly(res) {
  return res.status(403).json({ error: 'Live calls are for Pro members.', upgrade: true });
}

// What a host may change a call to, checked the same way for creating and editing.
function readCallFields(b, existing) {
  const out = {};
  const now = Date.now();
  if (!existing || b.title !== undefined) {
    out.title = oneLine(b.title, 80);
    if (out.title.length < 3) return { error: 'Give the call a title (at least 3 letters).' };
  }
  if (!existing || b.description !== undefined) out.description = paragraphs(b.description, 600) || null;
  if (!existing || b.nicheId !== undefined) out.nicheId = cleanNiche(b.nicheId);
  if (!existing || b.startsAt !== undefined) {
    const t = new Date(b.startsAt);
    if (isNaN(t.getTime())) return { error: 'Pick a date and time for the call.' };
    // Editing a call that has already started (e.g. to fix the link mid-call) sends its time back unchanged: that's fine.
    const sameTime = existing && t.getTime() === new Date(existing.startsAt).getTime();
    if (!sameTime && t.getTime() < now - 5 * 60 * 1000) return { error: 'That time has already passed. Pick a time in the future.' };
    if (t.getTime() > now + 180 * 24 * 60 * 60 * 1000) return { error: 'Calls can be scheduled up to 6 months ahead.' };
    out.startsAt = t.toISOString();
  }
  if (!existing || b.durationMin !== undefined) {
    const d = parseInt(b.durationMin, 10);
    out.durationMin = Number.isFinite(d) ? Math.min(180, Math.max(15, d)) : 45;
  }
  if (!existing || b.joinUrl !== undefined) {
    out.joinUrl = cleanUrl(b.joinUrl);
    if (!out.joinUrl) return { error: 'Paste the call link. It must start with https://' };
  }
  if (existing && b.replayUrl !== undefined) {
    const raw = String(b.replayUrl == null ? '' : b.replayUrl).trim();
    out.replayUrl = raw ? cleanUrl(raw) : null;
    if (raw && !out.replayUrl) return { error: 'The replay link must start with https://' };
  }
  return { fields: out };
}

const MAX_QUESTION = 300;
const MAX_QUESTIONS_PER_MEMBER = 3;

// ---------- GET /api/live ----------
// Upcoming and in-progress calls. Free members see the schedule; only Pro members (and the host) can join.
router.get('/', async (req, res) => {
  const v = req.viewer;
  const rows = await prisma.$queryRawUnsafe(
    `SELECT c."id", c."title", c."description", c."nicheId", c."hostEmail", c."hostName", h."headline",
            ${ISO} AS "startsAt", c."durationMin", c."joinUrl",
            (SELECT count(*)::int FROM "LiveRsvp" r WHERE r."callId" = c."id") AS "going",
            EXISTS (SELECT 1 FROM "LiveRsvp" r WHERE r."callId" = c."id" AND r."userId" = $1::text) AS "iGo",
            (SELECT count(*)::int FROM "LiveQuestion" q WHERE q."callId" = c."id") AS "questions",
            (SELECT count(*)::int FROM "LiveQuestion" q WHERE q."callId" = c."id" AND q."userId" = $1::text) AS "myQuestions",
            (c."startsAt" - interval '${OPENS_MIN_BEFORE} minutes' <= ${NOW_UTC}) AS "open"
     FROM "LiveCall" c LEFT JOIN "LiveHost" h ON h."email" = c."hostEmail"
     WHERE c."status" = 'scheduled'
       AND c."startsAt" + (c."durationMin" + ${STAYS_OPEN_MIN_AFTER}) * interval '1 minute' > ${NOW_UTC}
       AND c."startsAt" < ${NOW_UTC} + interval '90 days'
     ORDER BY c."startsAt" ASC LIMIT 60`, v.id);
  // calls that already happened and have a replay link (last 90 days), newest first
  const replayRows = await prisma.$queryRawUnsafe(
    `SELECT c."id", c."title", c."hostEmail", c."hostName", c."nicheId", ${ISO} AS "startsAt", c."durationMin", c."replayUrl"
     FROM "LiveCall" c
     WHERE c."status" = 'scheduled' AND c."replayUrl" IS NOT NULL
       AND c."startsAt" + c."durationMin" * interval '1 minute' <= ${NOW_UTC}
       AND c."startsAt" > ${NOW_UTC} - interval '90 days'
     ORDER BY c."startsAt" DESC LIMIT 20`);
  // a host's own finished calls (the owner sees everyone's) from the last 45 days, so they can add a replay link
  let past = [];
  if (v.canHost) {
    past = await prisma.$queryRawUnsafe(
      `SELECT c."id", c."title", c."hostEmail", c."hostName", ${ISO} AS "startsAt", c."replayUrl",
              (SELECT count(*)::int FROM "LiveQuestion" q WHERE q."callId" = c."id") AS "questions"
       FROM "LiveCall" c
       WHERE c."status" = 'scheduled'
         AND c."startsAt" + (c."durationMin" + ${STAYS_OPEN_MIN_AFTER}) * interval '1 minute' <= ${NOW_UTC}
         AND c."startsAt" > ${NOW_UTC} - interval '45 days'
         AND ($1::boolean OR c."hostEmail" = $2::text)
       ORDER BY c."startsAt" DESC LIMIT 30`, v.owner, v.email);
  }
  res.set('Cache-Control', 'no-store');
  res.json({
    isPro: v.pro,
    canHost: v.canHost,
    isOwner: v.owner,
    replays: replayRows.map(c => {
      const mine = c.hostEmail === v.email;
      return { id: c.id, title: c.title, hostName: c.hostName, nicheId: c.nicheId, startsAt: c.startsAt, durationMin: c.durationMin, mine,
               replayUrl: (v.pro || mine) ? c.replayUrl : null };
    }),
    past: past.map(c => ({ id: c.id, title: c.title, hostName: c.hostName, startsAt: c.startsAt, replayUrl: c.replayUrl || null,
                           mine: c.hostEmail === v.email, questions: c.questions })),
    calls: rows.map(c => {
      const mine = c.hostEmail === v.email;
      return {
        id: c.id, title: c.title, description: c.description, nicheId: c.nicheId,
        hostName: c.hostName, hostHeadline: c.headline || null,
        startsAt: c.startsAt, durationMin: c.durationMin,
        going: c.going, iGo: !!c.iGo, mine,
        questions: c.questions, myQuestions: c.myQuestions,
        canJoin: (v.pro || mine) && !!c.open,
        // the link itself only goes to the people who run the call, so they can edit it
        joinUrl: (v.owner || mine) ? c.joinUrl : undefined,
      };
    }),
  });
});

// ---------- hosts (owner only) ----------
// Declared before the /:id routes so "hosts" is never mistaken for a call id.
function requireOwner(req, res, next) {
  if (!req.viewer.owner) return res.status(403).json({ error: 'Not authorized.' });
  next();
}

router.get('/hosts', requireOwner, async (req, res) => {
  const rows = await prisma.$queryRawUnsafe(`SELECT "email", "name", "headline" FROM "LiveHost" ORDER BY "addedAt" ASC LIMIT 200`);
  res.json({ hosts: rows });
});

router.post('/hosts', requireOwner, async (req, res) => {
  const b = req.body || {};
  const email = cleanEmail(b.email);
  const name = oneLine(b.name, 60);
  const headline = oneLine(b.headline, 80) || null;
  if (!email) return res.status(400).json({ error: 'Enter the expert\'s email address.' });
  if (name.length < 2) return res.status(400).json({ error: 'Enter the name members will see.' });
  await prisma.$executeRawUnsafe(
    `INSERT INTO "LiveHost" ("email", "name", "headline") VALUES ($1::text, $2::text, $3::text)
     ON CONFLICT ("email") DO UPDATE SET "name" = EXCLUDED."name", "headline" = EXCLUDED."headline"`,
    email, name, headline);
  // If they already have an account, tell them. If not, it applies the day they sign up with this email.
  const user = await prisma.user.findUnique({ where: { email }, select: { id: true } });
  if (user) {
    await notifyUser(user.id, {
      type: 'live_host', title: 'You can now host live calls',
      body: 'Open Community, then Live, to schedule a call for the members.', link: { view: 'live' },
    });
  }
  res.status(201).json({ ok: true, accountFound: !!user });
});

router.delete('/hosts/:email', requireOwner, async (req, res) => {
  const email = cleanEmail(req.params.email); // Express has already decoded it
  if (!email) return res.status(400).json({ error: 'That email does not look right.' });
  await prisma.$executeRawUnsafe(`DELETE FROM "LiveHost" WHERE "email" = $1::text`, email);
  res.json({ ok: true });
});

// ---------- POST /api/live ---------- (owner or an approved host)
router.post('/', async (req, res) => {
  const v = req.viewer;
  if (!v.canHost) return res.status(403).json({ error: 'Only approved hosts can schedule calls.' });
  const b = req.body || {};
  const parsed = readCallFields(b, null);
  if (parsed.error) return res.status(400).json({ error: parsed.error });
  const f = parsed.fields;

  // who is hosting: an approved host is always themselves; the owner can pick one of the approved hosts
  let hostEmail = v.email;
  let hostName = v.host ? v.host.name : ownerDisplayName();
  if (v.owner) {
    const own = await prisma.$queryRawUnsafe(`SELECT "name" FROM "LiveHost" WHERE "email" = $1::text`, v.email);
    if (own[0]) hostName = own[0].name;
    const pick = b.hostEmail ? cleanEmail(b.hostEmail) : null;
    if (pick && pick !== v.email) {
      const rows = await prisma.$queryRawUnsafe(`SELECT "name" FROM "LiveHost" WHERE "email" = $1::text`, pick);
      if (!rows[0]) return res.status(400).json({ error: 'Add that person as a host first.' });
      hostEmail = pick; hostName = rows[0].name;
    }
  }

  const id = crypto.randomUUID();
  await prisma.$executeRawUnsafe(
    `INSERT INTO "LiveCall" ("id","title","description","nicheId","hostEmail","hostName","startsAt","durationMin","joinUrl")
     VALUES ($1::text,$2::text,$3::text,$4::text,$5::text,$6::text,($7::timestamptz AT TIME ZONE 'UTC'),$8::int,$9::text)`,
    id, f.title, f.description, f.nicheId, hostEmail, hostName, f.startsAt, f.durationMin, f.joinUrl);

  // Tell the Pro members there is a new call (best effort, never blocks the host).
  try {
    const pros = await prisma.user.findMany({
      where: { OR: [{ isPro: true }, { bonusProUntil: { gt: new Date() } }], NOT: { id: v.id } },
      select: { id: true },
    });
    await notifyUsers(pros.map(u => u.id), {
      type: 'live_new', title: `New live call: ${f.title}`,
      body: `With ${hostName}. Open Live to see the time and set a reminder.`, link: { view: 'live' },
    });
  } catch (err) { console.error('[live] could not notify members:', err.message); }

  res.status(201).json({ id });
});

// ---------- PATCH /api/live/:id ---------- (the call's host, or the owner)
router.patch('/:id', async (req, res) => {
  const v = req.viewer;
  const call = await findCall(req.params.id);
  if (!call || call.status !== 'scheduled') return res.status(404).json({ error: 'That call is not on the schedule.' });
  if (!v.owner && call.hostEmail !== v.email) return res.status(403).json({ error: 'Only the host can change this call.' });
  const parsed = readCallFields(req.body || {}, call);
  if (parsed.error) return res.status(400).json({ error: parsed.error });
  const f = Object.assign({}, {
    title: call.title, description: call.description, nicheId: call.nicheId,
    startsAt: call.startsAt, durationMin: call.durationMin, joinUrl: call.joinUrl, replayUrl: call.replayUrl || null,
  }, parsed.fields);
  const replayAdded = !!f.replayUrl && f.replayUrl !== (call.replayUrl || null);
  // a new time means people should be reminded again
  const timeChanged = parsed.fields.startsAt !== undefined && parsed.fields.startsAt !== new Date(call.startsAt).toISOString();
  await prisma.$executeRawUnsafe(
    `UPDATE "LiveCall" SET "title" = $2::text, "description" = $3::text, "nicheId" = $4::text,
            "startsAt" = ($5::timestamptz AT TIME ZONE 'UTC'), "durationMin" = $6::int, "joinUrl" = $7::text,
            "remindedAt" = CASE WHEN $8::boolean THEN NULL ELSE "remindedAt" END, "replayUrl" = $9::text
     WHERE "id" = $1::text`,
    call.id, f.title, f.description, f.nicheId, f.startsAt, f.durationMin, f.joinUrl, timeChanged, f.replayUrl);
  if (replayAdded) {
    const rows = await prisma.$queryRawUnsafe(
      `SELECT "userId" FROM "LiveRsvp" WHERE "callId" = $1::text UNION SELECT "userId" FROM "LiveQuestion" WHERE "callId" = $1::text`, call.id);
    await notifyUsers(rows.map(r => r.userId).filter(id => id !== v.id), {
      type: 'live_replay', title: `Replay is up: ${f.title}`,
      body: 'Missed it, or want to watch again? Open Live and tap Watch replay.', link: { view: 'live' },
    });
  }
  if (timeChanged) {
    const rows = await prisma.$queryRawUnsafe(`SELECT "userId" FROM "LiveRsvp" WHERE "callId" = $1::text`, call.id);
    await notifyUsers(rows.map(r => r.userId), {
      type: 'live_changed', title: `New time: ${f.title}`,
      body: 'The host moved this call. Open Live to see the new time.', link: { view: 'live' },
    });
  }
  res.json({ ok: true });
});

// ---------- DELETE /api/live/:id ---------- (cancels the call; nothing is erased)
router.delete('/:id', async (req, res) => {
  const v = req.viewer;
  const call = await findCall(req.params.id);
  if (!call || call.status !== 'scheduled') return res.status(404).json({ error: 'That call is not on the schedule.' });
  if (!v.owner && call.hostEmail !== v.email) return res.status(403).json({ error: 'Only the host can cancel this call.' });
  await prisma.$executeRawUnsafe(`UPDATE "LiveCall" SET "status" = 'cancelled' WHERE "id" = $1::text`, call.id);
  const rows = await prisma.$queryRawUnsafe(`SELECT "userId" FROM "LiveRsvp" WHERE "callId" = $1::text`, call.id);
  await notifyUsers(rows.map(r => r.userId), {
    type: 'live_cancelled', title: `Call cancelled: ${call.title}`,
    body: `${call.hostName} cancelled this call.`, link: { view: 'live' },
  });
  res.json({ ok: true });
});

// ---------- POST/DELETE /api/live/:id/rsvp ---------- ("Remind me")
router.post('/:id/rsvp', async (req, res) => {
  const v = req.viewer;
  if (!v.pro) return proOnly(res);
  const call = await findCall(req.params.id);
  if (!call || call.status !== 'scheduled' || !call.notOver) return res.status(404).json({ error: 'That call is not on the schedule.' });
  await prisma.$executeRawUnsafe(
    `INSERT INTO "LiveRsvp" ("callId", "userId") VALUES ($1::text, $2::text) ON CONFLICT DO NOTHING`, call.id, v.id);
  res.status(201).json({ ok: true });
});

router.delete('/:id/rsvp', async (req, res) => {
  await prisma.$executeRawUnsafe(
    `DELETE FROM "LiveRsvp" WHERE "callId" = $1::text AND "userId" = $2::text`, String(req.params.id).slice(0, 80), req.viewer.id);
  res.json({ ok: true });
});

// ---------- POST /api/live/:id/questions ---------- (Pro members send a question in before the call)
router.post('/:id/questions', async (req, res) => {
  const v = req.viewer;
  const call = await findCall(req.params.id);
  if (!call || call.status !== 'scheduled') return res.status(404).json({ error: 'That call is not on the schedule.' });
  const mine = call.hostEmail === v.email;
  if (!v.pro && !mine) return proOnly(res);
  if (call.ended) return res.status(400).json({ error: 'This call has already happened.' });
  const body = paragraphs((req.body || {}).body, MAX_QUESTION).replace(/[ \t]{2,}/g, ' ');
  if (!body || body.length < 5) return res.status(400).json({ error: 'Write your question first (at least 5 letters).' });
  const count = await prisma.$queryRawUnsafe(
    `SELECT count(*)::int AS n FROM "LiveQuestion" WHERE "callId" = $1::text AND "userId" = $2::text`, call.id, v.id);
  if (count[0].n >= MAX_QUESTIONS_PER_MEMBER) return res.status(400).json({ error: `You can send up to ${MAX_QUESTIONS_PER_MEMBER} questions per call.` });
  const id = crypto.randomUUID();
  await prisma.$executeRawUnsafe(
    `INSERT INTO "LiveQuestion" ("id","callId","userId","body") VALUES ($1::text,$2::text,$3::text,$4::text)`, id, call.id, v.id, body);
  res.status(201).json({ id, body });
});

// ---------- GET /api/live/:id/questions ---------- (the host and the owner see every question; a member sees their own)
router.get('/:id/questions', async (req, res) => {
  const v = req.viewer;
  const call = await findCall(req.params.id);
  if (!call) return res.status(404).json({ error: 'That call is not on the schedule.' });
  const host = v.owner || call.hostEmail === v.email;
  if (!host && !v.pro) return proOnly(res);
  const rows = await prisma.$queryRawUnsafe(
    `SELECT q."id", q."body", q."userId", to_char(q."createdAt", 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS "createdAt", u."email"
     FROM "LiveQuestion" q JOIN "User" u ON u."id" = q."userId"
     WHERE q."callId" = $1::text AND ($2::boolean OR q."userId" = $3::text)
     ORDER BY q."createdAt" ASC LIMIT 200`, call.id, host, v.id);
  // the host sees an initial, never the email
  res.json({ questions: rows.map(q => ({ id: q.id, body: q.body, createdAt: q.createdAt, mine: q.userId === v.id,
                                         from: (q.email || '?').charAt(0).toUpperCase() })) });
});

// ---------- DELETE /api/live/:id/questions/:qid ---------- (the asker, the host, or the owner)
router.delete('/:id/questions/:qid', async (req, res) => {
  const v = req.viewer;
  const call = await findCall(req.params.id);
  if (!call) return res.status(404).json({ error: 'That call is not on the schedule.' });
  const host = v.owner || call.hostEmail === v.email;
  const n = await prisma.$executeRawUnsafe(
    `DELETE FROM "LiveQuestion" WHERE "id" = $1::text AND "callId" = $2::text AND ($3::boolean OR "userId" = $4::text)`,
    String(req.params.qid).slice(0, 80), call.id, host, v.id);
  if (!n) return res.status(404).json({ error: 'Question not found.' });
  res.json({ ok: true });
});

// ---------- GET /api/live/:id/join ----------
// The only place the call link leaves the server for a member: Pro only, and only while the room is open.
router.get('/:id/join', async (req, res) => {
  const v = req.viewer;
  const call = await findCall(req.params.id);
  if (!call || call.status !== 'scheduled' || !call.notOver) return res.status(404).json({ error: 'That call is not on the schedule anymore.' });
  const mine = v.owner || call.hostEmail === v.email;
  if (!v.pro && !mine) return proOnly(res);
  if (!mine && !call.open) return res.status(403).json({ error: `The room opens ${OPENS_MIN_BEFORE} minutes before the call.` });
  res.set('Cache-Control', 'no-store');
  res.json({ joinUrl: call.joinUrl, title: call.title, hostName: call.hostName });
});

module.exports = router;
module.exports.readCallFields = readCallFields; // for ops/check_backend.js
