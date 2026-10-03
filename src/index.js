require('dotenv').config();
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');

const authRoutes = require('./routes/auth');
const accountRoutes = require('./routes/account');
const billingRoutes = require('./routes/billing');
const mentorAlertRoutes = require('./routes/mentorAlert');
const aiChatRoutes = require('./routes/aiChat');
const mentorsRoutes = require('./routes/mentors');
const adminRoutes = require('./routes/admin');
const partnersRoutes = require('./routes/partners');
const notificationsRoutes = require('./routes/notifications');
const discussionRoutes = require('./routes/discussion');
const winsRoutes = require('./routes/wins');
const leaderboardRoutes = require('./routes/leaderboard');
const networkRoutes = require('./routes/networking');
const analyticsRoutes = require('./routes/analytics');
const { ensureAnalyticsTables, pruneOldEvents, drain: drainAnalytics } = require('./analytics');
const { scheduleWeeklyDigest } = require('./digest');
const { scheduleStreakReminders } = require('./streakReminder');

const app = express();

// Railway (like most hosts) sits behind a proxy. Without this, every visitor
// looks like the same IP address to the rate limiters — so one busy hour
// could lock everyone out of signing up. Trust the one proxy hop in front.
app.set('trust proxy', 1);

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

// Security headers — protects against clickjacking, MIME-sniffing, XSS, etc.
app.use(helmet());

app.use(cors({
  origin: (origin, callback) => {
    if (!origin || origin === 'null' || normalizeOrigin(origin) === normalizeOrigin(process.env.APP_URL)) {
      callback(null, true);
    } else {
      callback(new Error('Not allowed by CORS'));
    }
  },
  credentials: true,
  // Let browsers reuse the CORS preflight answer for 10 minutes instead of
  // asking before every single API call.
  maxAge: 600,
}));

// IMPORTANT: the Stripe webhook route needs the raw request body to verify
// the signature, so it must be mounted with express.raw() BEFORE the
// general express.json() parser below (which would otherwise consume it).
app.use('/api/billing/webhook', express.raw({ type: 'application/json' }));
app.use(express.json({ limit: '16kb' }));

app.get('/api/health', (req, res) => res.json({ ok: true }));

app.use('/api/auth', authRoutes);
app.use('/api/account', accountRoutes);
app.use('/api/billing', billingRoutes);
app.use('/api/mentor-alert', mentorAlertRoutes);
app.use('/api/ai-chat', aiChatRoutes);
app.use('/api/mentors', mentorsRoutes);
app.use('/api/admin', adminRoutes);
app.use('/api/partners', partnersRoutes);
app.use('/api/notifications', notificationsRoutes);
app.use('/api/discussion', discussionRoutes);
app.use('/api/wins', winsRoutes);
app.use('/api/leaderboard', leaderboardRoutes);
app.use('/api/network', networkRoutes);
app.use('/api/analytics', analyticsRoutes);

// Fallback error handler
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ error: 'Something went wrong on our end.' });
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`The Guide backend running on port ${PORT}`);
  scheduleWeeklyDigest();
  scheduleStreakReminders();
  ensureAnalyticsTables().then(ok => { if (ok) pruneOldEvents(); });
  setInterval(pruneOldEvents, 24 * 60 * 60 * 1000).unref();
});

// Write any buffered analytics events before the process exits on a redeploy.
process.on('SIGTERM', () => {
  drainAnalytics(2500).finally(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000).unref();
});
