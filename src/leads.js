// The free 7-day email course ("Start your side business in 7 days").
//
// Someone on the landing page leaves their email and gets one short lesson a day for seven
// days, each with one thing to do. It is the way to reach people who are not ready to sign
// up yet. Day 1 goes out right away; the rest go out once a day from a cron (same pattern
// as digest.js). A lead stops getting the course the moment they unsubscribe, and once they
// have an account (the onboarding emails take over then).
//
// Table created at startup with CREATE TABLE IF NOT EXISTS; declared in prisma/schema.prisma too.
// Nothing here reads or changes member data; the table only holds the email, the day reached,
// and an unsubscribe token.
const crypto = require('crypto');
const cron = require('node-cron');
const prisma = require('./db');
const { sendEmail } = require('./email');

const appUrl = () => (process.env.APP_URL || 'https://theguide.company').replace(/\/$/, '');
const apiUrl = () => (process.env.API_URL || 'https://guide-backend-production.up.railway.app/api').replace(/\/$/, '');

const DDL = [
  `CREATE TABLE IF NOT EXISTS "Lead" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "source" TEXT,
    "token" TEXT NOT NULL,
    "day" INTEGER NOT NULL DEFAULT 0,
    "lastSentAt" TIMESTAMP(3),
    "unsubscribedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Lead_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "Lead_email_key" ON "Lead"("email")`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "Lead_token_key" ON "Lead"("token")`,
];

let ready = false;
async function ensureLeadTable() {
  for (let attempt = 0; attempt < 3 && !ready; attempt++) {
    try {
      for (const sql of DDL) await prisma.$executeRawUnsafe(sql);
      ready = true;
      console.log('Lead table ready.');
    } catch (err) {
      console.error('Lead table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return ready;
}
function isReady() { return ready; }

// ---------------------------------------------------------------- the seven emails
// One idea, one action each. Plain words, no income promises.
const LESSONS = [
  { subject: 'Day 1 of 7: pick one lane',
    lead: 'Most people never start because they are choosing between five ideas. Today you pick one.',
    body: [
      'Write down the three things people have paid you for, or asked you to do for free, in the last two years. Editing a video. Fixing a laptop. Planning a trip. Cleaning a garage. That list is your short list.',
      'Pick the one you could do this month without buying anything. Not the most exciting, the most ready.',
      'That is your lane for the next six months. You can change later. You cannot build on five things at once.',
    ],
    action: 'Write one sentence: "For the next six months I am a ___ who helps ___."',
  },
  { subject: 'Day 2 of 7: your first offer',
    lead: 'A business is one clear offer. Not a menu.',
    body: [
      'Take yesterday\'s sentence and turn it into something a person can say yes to: what they get, how long it takes, and what it costs.',
      'Example: "A 30-second product video for your Instagram, delivered in 5 days, $150." Example: "Weekly lawn cut and edge, $45, same day every week."',
      'If you cannot write it in one line, it is not ready yet. Shrink it until it fits.',
    ],
    action: 'Write your offer in one line: what, how long, how much.',
  },
  { subject: 'Day 3 of 7: price it so you can say it out loud',
    lead: 'The first price is the one you can say without flinching. Then you raise it.',
    body: [
      'Find three people already selling what you sell, in your area or your niche. Write down their prices. You now know the range.',
      'Start in the lower middle, never the bottom. The cheapest option looks like the riskiest one to a buyer.',
      'Make three versions: a small one, the one you want to sell, and a bigger one. Most people pick the middle.',
    ],
    action: 'Write three prices: small, standard, bigger. Say the middle one out loud.',
  },
  { subject: 'Day 4 of 7: your first ten customers are people you already know',
    lead: 'Your first customers are not strangers on the internet. They are two steps away.',
    body: [
      'List 20 people who know you and might know someone who needs your offer. Friends, old coworkers, your barber, your cousin with the restaurant.',
      'Send each one the same short message: what you are doing now, the one-line offer, and "do you know anyone who needs this?" Not "please buy." Asking for a referral is easier for both of you.',
      'Ten messages a day for two days. Expect two or three replies. One of them is your first customer.',
    ],
    action: 'Send ten messages today. Copy the same text, change only the name.',
  },
  { subject: 'Day 5 of 7: the three things you actually need',
    lead: 'You do not need a logo, a website or an LLC to get paid this week. You need three things.',
    body: [
      'One: a way to get paid that is not your personal account. A free business account or a separate account at your bank, opened today.',
      'Two: a one-page agreement. What you will deliver, by when, for how much, and what happens if they cancel. One page. Both of you sign it.',
      'Three: an invoice that looks like a real invoice. Numbered, dated, with your offer written exactly as you agreed.',
      'Everything else can wait until you have been paid three times.',
    ],
    action: 'Open the account. Write the one-page agreement. Keep both for Day 6.',
  },
  { subject: 'Day 6 of 7: one real step a day',
    lead: 'A side business is built in the evenings, one step at a time. The step is the whole system.',
    body: [
      'Pick a time you can keep: 30 minutes, same time every day. Put it in your calendar for the next 14 days.',
      'Each day, one step that moves money closer: a message sent, a quote written, a job delivered, an invoice paid. Not "research." Not "planning." Something a customer could notice.',
      'Keep a streak. When you miss a day, start again the next day. Nobody is counting but you.',
    ],
    action: 'Block 30 minutes a day for 14 days, starting tomorrow.',
  },
  { subject: 'Day 7 of 7: where to go from here',
    lead: 'In six days you picked a lane, wrote an offer, priced it, reached out, got the paperwork ready and set your rhythm. That is further than most people get in a year.',
    body: [
      'The Guide is the long version of this week: a full course for your business, lesson by lesson, in the same style. One real step a day, with the templates, trackers and checklists done for you.',
      'The first module of every course is free, with no card. If you already know your lane, start there today.',
      'If you want the whole course, Pro opens every lesson, the templates, the client trackers, unlimited questions to the AI mentor and the live calls, and it starts with a free trial.',
    ],
    action: 'Open your course and finish lesson one tonight.',
    cta: 'Start Module 1 free',
  },
];

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function renderLesson(n, lead) {
  const L = LESSONS[n - 1];
  const link = `${appUrl()}/?utm_source=course&utm_medium=email&utm_campaign=7day&utm_content=day${n}`;
  const unsub = `${apiUrl()}/leads/unsubscribe?t=${encodeURIComponent(lead.token)}`;
  const cta = L.cta || 'Open The Guide';
  const text =
    `${L.lead}\n\n${L.body.join('\n\n')}\n\nToday: ${L.action}\n\n${cta}: ${link}\n\n` +
    `Day ${n} of 7 · The Guide · theguide.company\nStop these emails: ${unsub}`;
  const html =
    `<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px 20px;color:#14211A;background:#FFFFFF;line-height:1.6;font-size:16px">` +
    `<p style="margin:0 0 6px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#6B7B72">Start your side business in 7 days · Day ${n}</p>` +
    `<h1 style="margin:0 0 18px;font-size:24px;line-height:1.25;color:#0C1310">${esc(L.subject.replace(/^Day \d of 7: /, ''))}</h1>` +
    `<p style="margin:0 0 16px;font-size:17px;color:#0C1310"><strong>${esc(L.lead)}</strong></p>` +
    L.body.map(p => `<p style="margin:0 0 16px">${esc(p)}</p>`).join('') +
    `<div style="margin:22px 0;padding:16px 18px;border-radius:12px;background:#F1F7F4;border:1px solid #D7E8DF"><p style="margin:0 0 4px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#1F7A52;font-weight:700">Today</p><p style="margin:0;font-weight:600">${esc(L.action)}</p></div>` +
    `<p style="margin:0 0 26px"><a href="${link}" style="display:inline-block;padding:13px 22px;background:#3FCB93;color:#0C1310;text-decoration:none;border-radius:10px;font-weight:700">${esc(cta)} →</a></p>` +
    `<p style="margin:0;font-size:12.5px;color:#6B7B72;border-top:1px solid #E6EEE9;padding-top:14px">Day ${n} of 7 · The Guide · <a href="${appUrl()}" style="color:#6B7B72">theguide.company</a><br>Don’t want these? <a href="${unsub}" style="color:#6B7B72">Stop the emails</a>.</p>` +
    `</div>`;
  return { subject: L.subject, text, html };
}

// ---------------------------------------------------------------- data
function cleanEmail(v) {
  const s = String(v == null ? '' : v).trim().toLowerCase();
  if (s.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(s)) return null;
  return s;
}
async function findLead(email) {
  const rows = await prisma.$queryRawUnsafe(`SELECT * FROM "Lead" WHERE "email" = $1::text`, email);
  return rows[0] || null;
}
// Adds the lead (or quietly re-activates an unsubscribed one who asks again) and sends day 1.
async function addLead(email, source) {
  let lead = await findLead(email);
  if (lead && !lead.unsubscribedAt) return { lead, created: false };
  if (lead) {
    await prisma.$executeRawUnsafe(`UPDATE "Lead" SET "unsubscribedAt" = NULL, "day" = 0, "lastSentAt" = NULL, "source" = $2::text WHERE "id" = $1::text`, lead.id, source || lead.source);
  } else {
    await prisma.$executeRawUnsafe(
      `INSERT INTO "Lead" ("id","email","source","token") VALUES ($1::text,$2::text,$3::text,$4::text)`,
      crypto.randomUUID(), email, source || null, crypto.randomBytes(24).toString('base64url'));
  }
  lead = await findLead(email);
  await sendDay(lead, 1);
  return { lead, created: true };
}
async function unsubscribe(token) {
  if (!/^[A-Za-z0-9_-]{20,80}$/.test(String(token || ''))) return false;
  const n = await prisma.$executeRawUnsafe(`UPDATE "Lead" SET "unsubscribedAt" = CURRENT_TIMESTAMP WHERE "token" = $1::text AND "unsubscribedAt" IS NULL`, token);
  return n > 0;
}
async function sendDay(lead, n) {
  const mail = renderLesson(n, lead);
  const r = await sendEmail({ to: lead.email, subject: mail.subject, html: mail.html, text: mail.text });
  // count the day as sent even when email is not configured, so a misconfigured server never loops
  await prisma.$executeRawUnsafe(`UPDATE "Lead" SET "day" = $2::int, "lastSentAt" = CURRENT_TIMESTAMP WHERE "id" = $1::text`, lead.id, n);
  return r;
}
// The daily pass: everyone who is mid-course and whose last email was at least 20 hours ago
// gets the next one. Stops at day 7, on unsubscribe, and once they have an account.
async function processCourse() {
  if (!ready) return { sent: 0, skipped: 0 };
  const due = await prisma.$queryRawUnsafe(
    `SELECT * FROM "Lead" WHERE "unsubscribedAt" IS NULL AND "day" >= 1 AND "day" < 7
       AND ("lastSentAt" IS NULL OR "lastSentAt" < NOW() - INTERVAL '20 hours') ORDER BY "createdAt" ASC LIMIT 500`);
  let sent = 0, skipped = 0;
  for (const lead of due) {
    const member = await prisma.user.findUnique({ where: { email: lead.email }, select: { id: true } });
    if (member) { await prisma.$executeRawUnsafe(`UPDATE "Lead" SET "day" = 7 WHERE "id" = $1::text`, lead.id); skipped++; continue; }
    try { await sendDay(lead, lead.day + 1); sent++; }
    catch (err) { console.error('[course] send failed for a lead:', err.message); }
  }
  if (sent || skipped) console.log(`[course] sent ${sent}, closed ${skipped}`);
  return { sent, skipped };
}
function scheduleLeadCourse() {
  cron.schedule('30 13 * * *', () => { processCourse().catch(err => console.error('[course] error:', err)); }); // 9:30am New York
  console.log('[course] 7-day course scheduled daily.');
}

module.exports = { ensureLeadTable, isReady, addLead, unsubscribe, processCourse, scheduleLeadCourse, renderLesson, cleanEmail, LESSONS };
