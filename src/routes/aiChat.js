const express = require('express');
const prisma = require('../db');
const { buildGuiderContext } = require('../guiderContext');
const rateLimit = require('express-rate-limit');
const { requireAuth } = require('../middleware/auth');

const { isProUser } = require('../pro');

// Free members get a taste: one question a day. Pro members are unlimited. The count lives on the
// server (one row per member per day, created at startup like the other small tables), so it cannot
// be reset from the browser. Days are UTC.
const FREE_QUESTIONS_PER_DAY = 1;
let tableReady = false;
async function ensureGuiderTable() {
  for (let attempt = 0; attempt < 3 && !tableReady; attempt++) {
    try {
      await prisma.$executeRawUnsafe(`CREATE TABLE IF NOT EXISTS "GuiderFreeUse" (
        "userId" TEXT NOT NULL,
        "day" TEXT NOT NULL,
        "n" INTEGER NOT NULL DEFAULT 0,
        CONSTRAINT "GuiderFreeUse_pkey" PRIMARY KEY ("userId", "day"),
        CONSTRAINT "GuiderFreeUse_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
      )`);
      tableReady = true;
      console.log('Guider free-use table ready.');
    } catch (err) {
      console.error('Guider free-use table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return tableReady;
}
function todayUtc() { return new Date().toISOString().slice(0, 10); }
async function freeUsedToday(userId) {
  if (!tableReady) return 0;
  const rows = await prisma.$queryRawUnsafe(`SELECT "n" FROM "GuiderFreeUse" WHERE "userId" = $1::text AND "day" = $2::text`, userId, todayUtc());
  return rows[0] ? rows[0].n : 0;
}
async function countFreeUse(userId) {
  if (!tableReady) return;
  await prisma.$executeRawUnsafe(
    `INSERT INTO "GuiderFreeUse" ("userId", "day", "n") VALUES ($1::text, $2::text, 1)
     ON CONFLICT ("userId", "day") DO UPDATE SET "n" = "GuiderFreeUse"."n" + 1`, userId, todayUtc());
}

const router = express.Router();
router.use(requireAuth);

// ---------- GET /api/ai-chat/free ----------
// How many free questions this member has left today (Pro members: unlimited).
router.get('/free', async (req, res) => {
  const pro = await isProUser(req.user.id);
  res.set('Cache-Control', 'no-store');
  if (pro) return res.json({ pro: true, unlimited: true, left: null, limit: null });
  const used = await freeUsedToday(req.user.id);
  res.json({ pro: false, unlimited: false, left: Math.max(0, FREE_QUESTIONS_PER_DAY - used), limit: FREE_QUESTIONS_PER_DAY });
});

// Real API calls cost real money, so this needs a tighter limit than most
// other routes — enough for a normal back-and-forth conversation, not
// enough to let one account run up a large bill. Counted per member (this runs after
// requireAuth), so people sharing one network (an office, a school, a phone carrier)
// don't use up each other's messages, and one member can't get more by changing networks.
const aiChatLimiter = rateLimit({
  windowMs: 60 * 60 * 1000, // 1 hour
  max: 40,
  keyGenerator: (req) => 'member:' + req.user.id,
  message: { error: 'Too many messages this hour. Please try again later.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(aiChatLimiter);

const MAX_MESSAGE_CHARS = 8000;

// ---------- POST /api/ai-chat ----------
// This is the ONLY place that ever talks to Anthropic's API — the frontend
// never sees or holds an API key. It sends the chapter context and the
// recent conversation; this route builds the system prompt and forwards it.
router.post('/', async (req, res) => {
  const { messages, course } = req.body;
  // The chapter's name and one-line description go into The Guider's instructions; the app's
  // longest are well under these caps, so anything longer is trimmed rather than paid for.
  const nicheName = typeof req.body.nicheName === 'string' ? req.body.nicheName.trim().slice(0, 100) : '';
  const nicheDescription = typeof req.body.nicheDescription === 'string' ? req.body.nicheDescription.trim().slice(0, 400) : '';
  // People using the app in Spanish get their answers in Spanish.
  const spanish = req.body.lang === 'es';

  if (!nicheName || !Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: 'Missing required fields (nicheName, messages).' });
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    console.warn('ANTHROPIC_API_KEY is not set — The Guider cannot respond.');
    return res.status(503).json({ error: 'The Guider is not configured yet.' });
  }

  // Only forward role/content — never trust anything else the client sends,
  // and cap how much conversation history gets sent per request.
  const pro = await isProUser(req.user.id);
  let freeLeft = null;
  if (!pro) {
    if (!tableReady) return res.status(503).json({ error: 'The Guider is not ready yet. Try again in a minute.' });
    const used = await freeUsedToday(req.user.id);
    if (used >= FREE_QUESTIONS_PER_DAY) {
      return res.status(403).json({ error: "You've used today's free question. It comes back tomorrow, or go Pro for unlimited questions.", upgrade: true, left: 0, limit: FREE_QUESTIONS_PER_DAY });
    }
    freeLeft = FREE_QUESTIONS_PER_DAY - used - 1;
  }

  // Pro members get their recent conversation; a free question stands on its own.
  const safeMessages = messages
    .filter(m => (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
    .slice(pro ? -20 : -1)
    // a Guider answer is at most ~1000 tokens (~5,000 characters); anything longer
    // is not from the app, so trim it rather than pay to send it
    .map(m => ({ role: m.role, content: m.content.slice(0, MAX_MESSAGE_CHARS) }));

  if (safeMessages.length === 0 || safeMessages[safeMessages.length - 1].role !== 'user') {
    return res.status(400).json({ error: 'No valid messages to send.' });
  }

  // What this person has actually done is read from their own saved record, not
  // from the request — the browser only tells us which chapter's lessons exist.
  let about = '';
  try {
    const me = await prisma.user.findUnique({ where: { id: req.user.id }, select: { dataBlob: true } });
    const shape = (course && typeof course === 'object') ? {
      id: typeof course.id === 'string' ? course.id : '',
      guides: Array.isArray(course.guides) ? course.guides.slice(0, 400)
        .filter(g => g && typeof g.title === 'string')
        .map(g => ({ title: g.title.slice(0, 200), mod: Number(g.mod) || 0 })) : [],
      modules: Array.isArray(course.modules) ? course.modules.slice(0, 40)
        .map(m => ({ title: m && typeof m.title === 'string' ? m.title.slice(0, 200) : '' })) : [],
    } : null;
    about = buildGuiderContext(me && me.dataBlob, shape && shape.id ? shape : null);
  } catch (err) {
    console.error('Could not read the learner context for The Guider:', err.message);
  }

  const systemPrompt = `You are "The Guider," a knowledgeable, practical business advisor specializing in ${nicheName} businesses${nicheDescription ? ` (${nicheDescription})` : ''}, speaking to someone inside The Guide app. If asked your name, you're The Guider. The person wants specific, actionable advice for running a ${nicheName} business — not generic platitudes. Keep answers reasonably concise (a few short paragraphs at most) and practical. If asked something entirely unrelated to running this kind of business, gently steer the conversation back.${spanish ? ' Always answer in Spanish (neutral Latin American Spanish, using informal "tú"), whatever language the question is written in. Keep the names The Guide, The Guider and Pro as they are, and keep prices in US dollars.' : ''}${about}`;

  try {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: 'claude-sonnet-4-6',
        max_tokens: 1000,
        system: systemPrompt,
        messages: safeMessages,
      }),
    });

    if (!response.ok) {
      const errBody = await response.text();
      console.error('Anthropic API error:', response.status, errBody);
      return res.status(502).json({ error: "Couldn't reach The Guider right now. Please try again." });
    }

    const data = await response.json();
    const textBlock = (data.content || []).find(b => b.type === 'text');
    const replyText = textBlock ? textBlock.text : "Sorry, I didn't get a usable response — try asking again.";

    if (!pro) { try { await countFreeUse(req.user.id); } catch (e) { console.error('[guider] could not count the free question:', e.message); } }
    res.json({ reply: replyText, left: freeLeft, limit: pro ? null : FREE_QUESTIONS_PER_DAY });
  } catch (err) {
    console.error('AI chat request failed:', err);
    res.status(502).json({ error: "Couldn't reach The Guider right now. Please check your connection and try again." });
  }
});

module.exports = router;
module.exports.ensureGuiderTable = ensureGuiderTable;
