const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

const winsLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 60,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(winsLimiter);

// ---------- GET /api/wins ----------
// Returns the most recent 50 wins with author info and reaction counts.
router.get('/', async (req, res) => {
  try {
    const wins = await prisma.win.findMany({
      orderBy: { createdAt: 'desc' },
      take: 50,
      include: {
        author: { select: { id: true, email: true } },
        reactions: { select: { id: true, userId: true, emoji: true } },
      },
    });

    const result = wins.map(w => ({
      id: w.id,
      body: w.body,
      emoji: w.emoji,
      authorId: w.authorId,
      authorEmail: w.author.email,
      authorInitial: w.author.email.charAt(0).toUpperCase(),
      createdAt: w.createdAt,
      reactions: w.reactions,
    }));

    res.json({ wins: result });
  } catch (err) {
    console.error('Get wins error:', err);
    res.status(500).json({ error: 'Failed to load wins.' });
  }
});

// ---------- POST /api/wins ----------
router.post('/', async (req, res) => {
  try {
    const body = String(req.body.body || '').trim();
    const emoji = String(req.body.emoji || '🎉');

    if (!body || body.length > 500) {
      return res.status(400).json({ error: 'Win text is required (max 500 chars).' });
    }

    const win = await prisma.win.create({
      data: { authorId: req.user.id, body, emoji },
      include: {
        author: { select: { id: true, email: true } },
        reactions: true,
      },
    });

    res.status(201).json({
      id: win.id,
      body: win.body,
      emoji: win.emoji,
      authorId: win.authorId,
      authorEmail: win.author.email,
      authorInitial: win.author.email.charAt(0).toUpperCase(),
      createdAt: win.createdAt,
      reactions: [],
    });
  } catch (err) {
    console.error('Post win error:', err);
    res.status(500).json({ error: 'Failed to post win.' });
  }
});

// ---------- POST /api/wins/:id/react ----------
// Toggle a reaction emoji on a win.
router.post('/:id/react', async (req, res) => {
  try {
    const emoji = String(req.body.emoji || '');
    const allowed = ['🔥', '👏', '💪', '❤️'];
    if (!allowed.includes(emoji)) {
      return res.status(400).json({ error: 'Invalid reaction emoji.' });
    }

    const existing = await prisma.winReaction.findUnique({
      where: { winId_userId_emoji: { winId: req.params.id, userId: req.user.id, emoji } },
    });

    if (existing) {
      await prisma.winReaction.delete({ where: { id: existing.id } });
      return res.json({ action: 'removed' });
    }

    await prisma.winReaction.create({
      data: { winId: req.params.id, userId: req.user.id, emoji },
    });
    res.json({ action: 'added' });
  } catch (err) {
    console.error('React to win error:', err);
    res.status(500).json({ error: 'Failed to react.' });
  }
});

// ---------- DELETE /api/wins/:id ----------
// Author can delete their own win.
router.delete('/:id', async (req, res) => {
  try {
    const win = await prisma.win.findUnique({ where: { id: req.params.id } });
    if (!win) return res.status(404).json({ error: 'Win not found.' });
    if (win.authorId !== req.user.id) return res.status(403).json({ error: 'Not your win.' });

    await prisma.win.delete({ where: { id: req.params.id } });
    res.json({ message: 'Win deleted.' });
  } catch (err) {
    console.error('Delete win error:', err);
    res.status(500).json({ error: 'Failed to delete.' });
  }
});

module.exports = router;
