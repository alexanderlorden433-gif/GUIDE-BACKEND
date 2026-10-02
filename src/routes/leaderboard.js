const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

const lbLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 120,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(lbLimiter);

// ---------- GET /api/leaderboard?type=guides|streak|challenges ----------
// Computes rankings from each user's dataBlob. Since everything lives in a
// JSON column, this is computed in JS rather than a SQL aggregate — fine for
// the current user base, easy to move to a materialized view later.
router.get('/', async (req, res) => {
  try {
    const type = req.query.type || 'guides';
    const users = await prisma.user.findMany({
      select: { id: true, email: true, dataBlob: true },
    });

    let ranked;

    if (type === 'streak') {
      ranked = users.map(u => {
        const blob = u.dataBlob || {};
        return {
          userId: u.id,
          email: u.email,
          initial: u.email.charAt(0).toUpperCase(),
          value: (blob.streak && blob.streak.count) || 0,
          label: 'day streak',
        };
      });
    } else if (type === 'challenges') {
      ranked = users.map(u => {
        const blob = u.dataBlob || {};
        const challengesDone = (blob.challengeHistory || []).length;
        return {
          userId: u.id,
          email: u.email,
          initial: u.email.charAt(0).toUpperCase(),
          value: challengesDone,
          label: 'challenges',
        };
      });
    } else {
      // Default: guides completed
      ranked = users.map(u => {
        const blob = u.dataBlob || {};
        const completed = Array.isArray(blob.completed) ? blob.completed.length : 0;
        return {
          userId: u.id,
          email: u.email,
          initial: u.email.charAt(0).toUpperCase(),
          value: completed,
          label: 'guides',
        };
      });
    }

    // Sort descending, take top 25, filter out zero-value entries
    ranked = ranked
      .filter(r => r.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 25);

    // Mark the requesting user
    const result = ranked.map((r, i) => ({
      ...r,
      rank: i + 1,
      isYou: r.userId === req.user.id,
    }));

    res.json({ leaderboard: result, type });
  } catch (err) {
    console.error('Leaderboard error:', err);
    res.status(500).json({ error: 'Failed to load leaderboard.' });
  }
});

module.exports = router;
