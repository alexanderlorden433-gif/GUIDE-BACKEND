/**
 * Weekly progress digest — a Monday-morning email nudging users back with
 * where they stand (guides completed, streak) and which chapters other
 * members are currently active in.
 *
 * Runs in-process on a cron schedule inside the same always-on Node service
 * (see scheduleWeeklyDigest(), called once from index.js at startup) rather
 * than as a separate Railway cron job, so there's nothing extra to deploy.
 *
 * Honesty note: we don't currently log a history of when each guide was
 * completed, so this can't report a precise "here's what you did *this
 * week*" delta -- only a user's all-time totals. "Trending chapters" is a
 * proxy too: it's which chapters are most followed across all users right
 * now, not a true weekly trend. Both are still a genuinely useful nudge,
 * just worth knowing the limitation if this grows later.
 */

const cron = require('node-cron');
const prisma = require('./db');
const { sendEmail } = require('./email');

function pickTopNiches(users, limit = 3) {
  const nicheCounts = {};
  users.forEach(u => {
    const niches = (u.dataBlob && u.dataBlob.niches) || [];
    niches.forEach(n => { nicheCounts[n] = (nicheCounts[n] || 0) + 1; });
  });
  return Object.entries(nicheCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([nicheId]) => nicheId);
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function sendWeeklyDigests() {
  console.log('[digest] Starting weekly digest run...');
  const users = await prisma.user.findMany({
    select: { id: true, email: true, dataBlob: true },
  });
  const topNicheIds = pickTopNiches(users);

  let sent = 0, skipped = 0, failed = 0;

  for (const user of users) {
    const blob = user.dataBlob || {};
    if (blob.weeklyDigestOptOut) { skipped++; continue; }

    const completedCount = Array.isArray(blob.completed) ? blob.completed.length : 0;
    const streak = (blob.streak && blob.streak.count) || 0;

    // Don't nag someone who hasn't engaged at all yet -- nothing to report.
    if (completedCount === 0 && streak === 0) { skipped++; continue; }

    const topNicheLine = topNicheIds.length
      ? `Other members are especially active in: ${topNicheIds.join(', ')} right now.`
      : '';

    const appUrl = process.env.APP_URL || 'https://theguide.app';

    try {
      const result = await sendEmail({
        to: user.email,
        subject: `Your progress on The Guide — ${completedCount} guide${completedCount === 1 ? '' : 's'} completed`,
        text:
          `Here's where you stand:\n\n` +
          `- ${completedCount} guide${completedCount === 1 ? '' : 's'} completed\n` +
          `- ${streak}-day streak\n\n` +
          (topNicheLine ? `${topNicheLine}\n\n` : '') +
          `Jump back in: ${appUrl}\n\n` +
          `Don't want these weekly emails? Turn them off from Account settings.`,
        html:
          `<p>Here's where you stand:</p>` +
          `<ul><li><strong>${completedCount}</strong> guide${completedCount === 1 ? '' : 's'} completed</li>` +
          `<li><strong>${streak}</strong>-day streak</li></ul>` +
          (topNicheLine ? `<p>${topNicheLine}</p>` : '') +
          `<p><a href="${appUrl}">Jump back in →</a></p>` +
          `<p style="color:#888;font-size:12px;">Don't want these weekly emails? Turn them off from Account settings.</p>`,
      });
      if (result.sent) sent++; else failed++;
    } catch (err) {
      console.error(`[digest] Failed to email ${user.email}:`, err.message);
      failed++;
    }

    // A small pacing delay so a large user base doesn't burst past Resend's
    // rate limit all at once.
    await sleep(150);
  }

  console.log(`[digest] Done. Sent: ${sent}, skipped: ${skipped}, failed: ${failed}`);
  return { sent, skipped, failed };
}

function scheduleWeeklyDigest() {
  // Every Monday at 9am UTC.
  cron.schedule('0 9 * * 1', () => {
    sendWeeklyDigests().catch(err => console.error('[digest] Unhandled error:', err));
  });
  console.log('[digest] Weekly digest scheduled for Mondays 9am UTC.');
}

module.exports = { scheduleWeeklyDigest, sendWeeklyDigests };
