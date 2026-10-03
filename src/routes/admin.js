const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { sendWeeklyDigests } = require('../digest');
const { sendStreakReminders } = require('../streakReminder');

const router = express.Router();
router.use(requireAuth);

// This is only ever used by one person (you), so a light limit is plenty —
// it just guards against something looping and hammering the DB by mistake.
const adminLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 60,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(adminLimiter);

// Every route below is owner-only. This checks on every request — never
// trusts a client-supplied flag — the same pattern as the Pro override in
// account.js.
function requireOwner(req, res, next) {
  const isOwner = process.env.OWNER_EMAIL &&
    req.user.email.toLowerCase() === process.env.OWNER_EMAIL.toLowerCase();
  if (!isOwner) return res.status(403).json({ error: 'Not authorized.' });
  next();
}
router.use(requireOwner);

const MONTHLY_PRICE = 12.99;

// ---------- GET /api/admin/stats ----------
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
    // Only what's needed for the two aggregates below — never full account data.
    prisma.user.findMany({
      where: { createdAt: { gte: thirtyDaysAgo } },
      select: { createdAt: true },
    }),
    prisma.mentorProfile.count(),
  ]);

  // Signups per day, last 30 days
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

  // Popular chapters, streak stats, and completion stats — computed from
  // dataBlob. Paginated to avoid loading all users into memory at once.
  const BATCH_SIZE = 500;
  let dbCursor = undefined;
  const nicheCounts = {};
  let totalStreakSum = 0;
  let maxStreak = 0;
  let totalCompletedSum = 0;
  let userCount = 0;

  while (true) {
    const batch = await prisma.user.findMany({
      take: BATCH_SIZE,
      ...(dbCursor ? { skip: 1, cursor: { id: dbCursor } } : {}),
      select: { id: true, dataBlob: true },
      orderBy: { id: 'asc' },
    });
    if (batch.length === 0) break;
    dbCursor = batch[batch.length - 1].id;

    for (const u of batch) {
      userCount++;
      const blob = u.dataBlob || {};

      // Niche counts
      const niches = blob.niches || [];
      niches.forEach(n => { nicheCounts[n] = (nicheCounts[n] || 0) + 1; });

      // Streak
      const streak = (blob.streak && blob.streak.count) || 0;
      totalStreakSum += streak;
      if (streak > maxStreak) maxStreak = streak;

      // Completed
      const completed = Array.isArray(blob.completed) ? blob.completed.length : 0;
      totalCompletedSum += completed;
    }
  }

  const popularChapters = Object.entries(nicheCounts)
    .map(([nicheId, count]) => ({ nicheId, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);

  const estimatedMRR = Math.round(monthlyUsers * MONTHLY_PRICE * 100) / 100;
  const lifetimeRevenue = Math.round(lifetimeUsers * 84.99 * 100) / 100;
  const conversionRate = totalUsers > 0 ? Math.round((proUsers / totalUsers) * 10000) / 100 : 0;

  // Engagement: users active in last 7 days (updated their account)
  const [activeUsersLast7, activeUsersLast30] = await Promise.all([
    prisma.user.count({ where: { updatedAt: { gte: sevenDaysAgo } } }),
    prisma.user.count({ where: { updatedAt: { gte: thirtyDaysAgo } } }),
  ]);

  const avgStreak = userCount > 0 ? Math.round(totalStreakSum / userCount * 10) / 10 : 0;
  const avgCompleted = userCount > 0 ? Math.round(totalCompletedSum / userCount * 10) / 10 : 0;
  const totalCompleted = totalCompletedSum;

  // Recent signups (last 10 users with basic info)
  const recentSignups = await prisma.user.findMany({
    orderBy: { createdAt: 'desc' },
    take: 15,
    select: { email: true, createdAt: true, isPro: true, planType: true, dataBlob: true }
  });
  const recentSignupsList = recentSignups.map(u => ({
    email: u.email,
    createdAt: u.createdAt,
    isPro: u.isPro,
    planType: u.planType,
    niches: (u.dataBlob && u.dataBlob.niches) || [],
    guidesCompleted: Array.isArray(u.dataBlob && u.dataBlob.completed) ? u.dataBlob.completed.length : 0,
    streak: (u.dataBlob && u.dataBlob.streak && u.dataBlob.streak.count) || 0,
  }));

  // Network & community stats
  let networkRequestCount = 0;
  let winCount = 0;
  try {
    networkRequestCount = await prisma.networkRequest.count();
  } catch(e) { /* model may not exist yet */ }
  try {
    winCount = await prisma.win.count();
  } catch(e) { /* model may not exist yet */ }

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
    lifetimeRevenue,
    conversionRate,
    activeUsersLast7,
    activeUsersLast30,
    avgStreak,
    maxStreak,
    avgCompleted,
    totalCompleted,
    recentSignupsList,
    networkRequestCount,
    winCount,
  });
});

// ---------- POST /api/admin/send-digest-now ----------
// Manually fires the weekly digest immediately, instead of waiting for
// Monday 9am UTC — handy for testing after deploying a change to it.
router.post('/send-digest-now', async (req, res) => {
  try {
    const result = await sendWeeklyDigests();
    res.json(result);
  } catch (err) {
    console.error('Manual digest trigger failed:', err);
    res.status(500).json({ error: 'Digest run failed — check server logs.' });
  }
});

// ---------- POST /api/admin/send-streak-reminders-now ----------
router.post('/send-streak-reminders-now', async (req, res) => {
  try {
    const result = await sendStreakReminders();
    res.json(result);
  } catch (err) {
    console.error('Manual streak reminder trigger failed:', err);
    res.status(500).json({ error: 'Streak reminder run failed — check server logs.' });
  }
});

module.exports = router;
