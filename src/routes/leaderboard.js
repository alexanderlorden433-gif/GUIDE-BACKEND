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

// Mask email: "john@gmail.com" → "j***@g***"
function maskEmail(email) {
  const [local, domain] = email.split('@');
  return `${local.charAt(0)}***@${domain.charAt(0)}***`;
}

// ---------- GET /api/leaderboard?type=guides|streak|challenges ----------
// Computes rankings from each user's dataBlob. Paginated to avoid loading
// all users at once — pulls 200 at a time and keeps the top 25.
router.get('/', async (req, res) => {
  try {
    const type = req.query.type || 'guides';

    // For scale: paginate through users in batches rather than loading all at once.
    const BATCH_SIZE = 200;
    let cursor = undefined;
    let topEntries = [];

    while (true) {
      const batch = await prisma.user.findMany({
        take: BATCH_SIZE,
        ...(cursor ? { skip: 1, cursor: { id: cursor } } : {}),
        select: { id: true, email: true, dataBlob: true },
        orderBy: { id: 'asc' },
      });

      if (batch.length === 0) break;
      cursor = batch[batch.length - 1].id;

      const entries = batch.map(u => {
        const blob = u.dataBlob || {};
        let value = 0;
        let label = 'guides';

        if (type === 'streak') {
          value = (blob.streak && blob.streak.count) || 0;
          label = 'day streak';
        } else if (type === 'challenges') {
          value = (blob.challengeHistory || []).length;
          label = 'challenges';
        } else {
          value = Array.isArray(blob.completed) ? blob.completed.length : 0;
          label = 'guides';
        }

        if (value === 0) return null;
        return { userId: u.id, email: u.email, initial: u.email.charAt(0).toUpperCase(), value, label };
      }).filter(Boolean);

      topEntries = topEntries.concat(entries);
      // Keep only top 25 across all batches to cap memory
      topEntries.sort((a, b) => b.value - a.value);
      topEntries = topEntries.slice(0, 25);
    }

    // Mark the requesting user and mask emails
    const result = topEntries.map((r, i) => ({
      ...r,
      email: r.userId === req.user.id ? r.email : maskEmail(r.email),
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
