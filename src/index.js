require('dotenv').config();
const express = require('express');
const cors = require('cors');

const authRoutes = require('./routes/auth');
const accountRoutes = require('./routes/account');
const billingRoutes = require('./routes/billing');
const mentorAlertRoutes = require('./routes/mentorAlert');
const aiChatRoutes = require('./routes/aiChat');
const mentorsRoutes = require('./routes/mentors');

const app = express();

// Browsers send no Origin header, OR the literal string "null", for a
// locally-opened HTML file (double-clicked, not served from a real web
// address) — both are expected while testing this file directly rather
// than hosting it somewhere. We allow that case alongside the real
// configured frontend URL, which is still the only *cross-origin* web
// request that gets through.
//
// A browser's Origin header never has a trailing slash, but it's an easy
// typo to leave one on APP_URL when copying a URL from a browser's address
// bar — so we strip it from both sides before comparing, rather than
// silently rejecting every request until someone spots the mismatch.
const normalizeOrigin = (value) => (value || '').replace(/\/+$/, '');

app.use(cors({
  origin: (origin, callback) => {
    if (!origin || origin === 'null' || normalizeOrigin(origin) === normalizeOrigin(process.env.APP_URL)) {
      callback(null, true);
    } else {
      callback(new Error('Not allowed by CORS'));
    }
  },
  credentials: true,
}));

// IMPORTANT: the Stripe webhook route needs the raw request body to verify
// the signature, so it must be mounted with express.raw() BEFORE the
// general express.json() parser below (which would otherwise consume it).
app.use('/api/billing/webhook', express.raw({ type: 'application/json' }));
app.use(express.json());

app.get('/api/health', (req, res) => res.json({ ok: true }));

app.use('/api/auth', authRoutes);
app.use('/api/account', accountRoutes);
app.use('/api/billing', billingRoutes);
app.use('/api/mentor-alert', mentorAlertRoutes);
app.use('/api/ai-chat', aiChatRoutes);
app.use('/api/mentors', mentorsRoutes);

// Fallback error handler
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ error: 'Something went wrong on our end.' });
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`The Guide backend running on port ${PORT}`);
});
