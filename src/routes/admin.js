const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

const adminLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 60,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(adminLimiter);

function requireOwner(req, res, next) {
  const isOwner = process.env.OWNER_EMAIL &&
    req.user.email.toLowerCase() === process.env.OWNER_EMAIL.toLowerCase();
  if (!isOwner) return res.status(403).json({ error: 'Not authorized.' });
  next();
}
router.use(requireOwner);

const MONTHLY_PRICE = 12.99;

router.get('/stats', async (req, res) => {
  const now = new Date();
  const sevenDaysAgo = new Date(now - 7 * 24 * 60 * 60 * 1000);
  const thirtyDaysAgo = new Date(now - 30 * 24 * 60 * 60 * 1000);

  const [
    totalUsers,
    proUsers,
    monthlyUsers,
    lifetimeUsers,
    signupsLast7Days,
    signupsLast30Days,
    recentUsers,
    mentorProfileCount,
  ] = await Promise.all([
    prisma.user.count(),
    prisma.user.count({ where: { isPro: true } }),
    prisma.user.count({ where: { planType: 'monthly' } }),
    prisma.user.count({ where: { planType: 'lifetime' } }),
    prisma.user.count({ where: { createdAt: { gte: sevenDaysAgo } } }),
    prisma.user.count({ where: { createdAt: { gte: thirtyDaysAgo } } }),
    prisma.user.findMany({
      where: { createdAt: { gte: thirtyDaysAgo } },
      select: { createdAt: true },
    }),
    prisma.mentorProfile.count(),
  ]);

  const dayBuckets = {};
  for (let i = 29; i >= 0; i--) {
    const d = new Date(now - i * 24 * 60 * 60 * 1000);
    dayBuckets[d.toISOString().slice(0, 10)] = 0;
  }
  recentUsers.forEach(u => {
    const key = u.createdAt.toISOString().slice(0, 10);
    if (key in dayBuckets) dayBuckets[key]++;
  });
  const signupsByDay = Object.entries(dayBuckets).map(([date, count]) => ({ date, count }));

  const allUsers = await prisma.user.findMany({ select: { dataBlob: true } });
  const nicheCounts = {};
  allUsers.forEach(u => {
    const niches = (u.dataBlob && u.dataBlob.niches) || [];
    niches.forEach(n => { nicheCounts[n] = (nicheCounts[n] || 0) + 1; });
  });
  const popularChapters = Object.entries(nicheCounts)
    .map(([nicheId, count]) => ({ nicheId, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);

  const estimatedMRR = Math.round(monthlyUsers * MONTHLY_PRICE * 100) / 100;

  res.json({
    totalUsers,
    proUsers,
    freeUsers: totalUsers - proUsers,
    monthlyUsers,
    lifetimeUsers,
    signupsLast7Days,
    signupsLast30Days,
    signupsByDay,
    popularChapters,
    mentorProfileCount,
    estimatedMRR,
  });
});

module.exports = router;
