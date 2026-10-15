// The free 7-day course: the landing page posts an email here; the unsubscribe link in the
// emails comes back here. Both are public (no login), both rate-limited.
const express = require('express');
const rateLimit = require('express-rate-limit');
const leads = require('../leads');

const router = express.Router();

// ---------- POST /api/leads ----------
// Never says whether an email was already on the list (same answer either way).
const joinLimiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 10, standardHeaders: true, legacyHeaders: false,
                                message: { error: 'Too many tries. Please wait a few minutes.' } });
router.post('/', joinLimiter, async (req, res) => {
  if (!leads.isReady()) return res.status(503).json({ error: 'Not ready yet. Try again in a minute.' });
  const b = req.body || {};
  if (b.website) return res.json({ ok: true }); // honeypot field: bots fill it, people never see it
  const email = leads.cleanEmail(b.email);
  if (!email) return res.status(400).json({ error: 'Enter a real email address.' });
  const source = String(b.source || 'landing').replace(/[^a-z0-9_-]/gi, '').slice(0, 40) || 'landing';
  await leads.addLead(email, source);
  res.json({ ok: true });
});

// ---------- GET /api/leads/unsubscribe?t=TOKEN ----------
const unsubLimiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 30, standardHeaders: true, legacyHeaders: false });
router.get('/unsubscribe', unsubLimiter, async (req, res) => {
  const ok = leads.isReady() && await leads.unsubscribe(req.query.t);
  res.set('Content-Type', 'text/html; charset=utf-8');
  res.status(200).send(
    `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>The Guide</title>` +
    `<body style="margin:0;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#0C1310;color:#EAF0EC;display:grid;place-items:center;min-height:100vh;padding:24px;text-align:center">` +
    `<div><h1 style="font-size:22px;margin:0 0 10px">${ok ? 'You’re unsubscribed.' : 'That link has already been used.'}</h1>` +
    `<p style="margin:0;color:#8CA196">No more course emails will be sent to you.</p>` +
    `<p style="margin:18px 0 0"><a href="${(process.env.APP_URL || 'https://theguide.company').replace(/\/$/, '')}" style="color:#3FCB93">theguide.company</a></p></div></body>`);
});

module.exports = router;
