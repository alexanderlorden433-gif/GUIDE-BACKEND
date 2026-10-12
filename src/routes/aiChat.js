const express = require('express');
const prisma = require('../db');
const { buildGuiderContext } = require('../guiderContext');
const rateLimit = require('express-rate-limit');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

// Real API calls cost real money, so this needs a tighter limit than most
// other routes — enough for a normal back-and-forth conversation, not
// enough to let one account run up a large bill.
const aiChatLimiter = rateLimit({
  windowMs: 60 * 60 * 1000, // 1 hour
  max: 40,
  message: { error: 'Too many messages this hour. Please try again later.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(aiChatLimiter);

// ---------- POST /api/ai-chat ----------
// This is the ONLY place that ever talks to Anthropic's API — the frontend
// never sees or holds an API key. It sends the chapter context and the
// recent conversation; this route builds the system prompt and forwards it.
router.post('/', async (req, res) => {
  const { nicheName, nicheDescription, messages, course } = req.body;

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
  const safeMessages = messages
    .filter(m => (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
    .slice(-20)
    .map(m => ({ role: m.role, content: m.content }));

  if (safeMessages.length === 0) {
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
        .map(g => ({ title: g.title, mod: Number(g.mod) || 0 })) : [],
      modules: Array.isArray(course.modules) ? course.modules.slice(0, 40)
        .map(m => ({ title: m && typeof m.title === 'string' ? m.title : '' })) : [],
    } : null;
    about = buildGuiderContext(me && me.dataBlob, shape && shape.id ? shape : null);
  } catch (err) {
    console.error('Could not read the learner context for The Guider:', err.message);
  }

  const systemPrompt = `You are "The Guider," a knowledgeable, practical business advisor specializing in ${nicheName} businesses${nicheDescription ? ` (${nicheDescription})` : ''}, speaking to someone inside The Guide app. If asked your name, you're The Guider. The person wants specific, actionable advice for running a ${nicheName} business — not generic platitudes. Keep answers reasonably concise (a few short paragraphs at most) and practical. If asked something entirely unrelated to running this kind of business, gently steer the conversation back.${about}`;

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

    res.json({ reply: replyText });
  } catch (err) {
    console.error('AI chat request failed:', err);
    res.status(502).json({ error: "Couldn't reach The Guider right now. Please check your connection and try again." });
  }
});

module.exports = router;
