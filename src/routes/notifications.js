const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

const notificationsLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 150,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(notificationsLimiter);

// ---------- GET /api/notifications ----------
// Returns the most recent 30 notifications for the signed-in user, plus an
// unread count for the bell badge.
router.get('/', async (req, res) => {
  const [items, unreadCount] = await Promise.all([
    prisma.notification.findMany({
      where: { userId: req.user.id },
      orderBy: { createdAt: 'desc' },
      take: 30,
    }),
    prisma.notification.count({ where: { userId: req.user.id, read: false } }),
  ]);
  res.json({ items, unreadCount });
});

// ---------- POST /api/notifications/:id/read ----------
router.post('/:id/read', async (req, res) => {
  await prisma.notification.updateMany({
    where: { id: req.params.id, userId: req.user.id },
    data: { read: true },
  });
  res.json({ message: 'Marked read.' });
});

// ---------- POST /api/notifications/read-all ----------
router.post('/read-all', async (req, res) => {
  await prisma.notification.updateMany({
    where: { userId: req.user.id, read: false },
    data: { read: true },
  });
  res.json({ message: 'All marked read.' });
});

module.exports = router;
