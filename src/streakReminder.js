/**
 * Streak-save reminder — a same-day nudge to anyone whose streak is about
 * to break because they haven't completed a guide yet today.
 *
 * Timezone note: the frontend stores streak.lastDate as a plain YYYY-MM-DD
 * string in the user's own local date, with no timezone attached. This job
 * runs on a fixed UTC schedule and compares against UTC "today"/"yesterday",
 * so it's an approximation -- accurate for users near UTC, up to a day off
 * at the extremes. Still a useful nudge, not a promise of precise timing.
 *
 * Self-limiting by design: this only matches a user on the one day their
 * streak is actually at risk (lastDate === yesterday). If they still don't
 * come back, lastDate falls further behind "yesterday" the next day and
 * they stop matching -- no repeated nagging after a streak has lapsed.
 */

const cron = require('node-cron');
const prisma = require('./db');
const { sendEmail } = require('./email');

function utcDateStr(date) {
  return date.toISOString().slice(0, 10);
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function sendStreakReminders() {
  console.log('[streak-reminder] Starting run...');
  const now = new Date();
  const todayUtc = utcDateStr(now);
  const yesterdayUtc = utcDateStr(new Date(now.getTime() - 24 * 60 * 60 * 1000));
  const appUrl = process.env.APP_URL || 'https://theguide.app';

  const users = await prisma.user.findMany({
    select: { id: true, email: true, dataBlob: true },
  });

  let sent = 0, skipped = 0, failed = 0;

  for (const user of users) {
    const blob = user.dataBlob || {};
    if (blob.streakReminderOptOut) { skipped++; continue; }

    const streak = blob.streak || {};
    const count = streak.count || 0;
    const lastDate = streak.lastDate || null;

    // Only worth a nudge for a real streak (2+ days) that hasn't already
    // been extended today and is exactly one day from lapsing.
    if (count < 2 || lastDate === todayUtc || lastDate !== yesterdayUtc) {
      skipped++;
      continue;
    }

    try {
      const result = await sendEmail({
        to: user.email,
        subject: `🔥 Your ${count}-day streak ends today — keep it going`,
        text:
          `You're on a ${count}-day streak on The Guide, but you haven't completed a guide yet today.\n\n` +
          `Finish just one guide before the day ends to keep it alive: ${appUrl}\n\n` +
          `Don't want these reminders? Turn them off from Account settings.`,
        html:
          `<p>You're on a <strong>${count}-day streak</strong> on The Guide, but you haven't completed a guide yet today.</p>` +
          `<p>Finish just one guide before the day ends to keep it alive.</p>` +
          `<p><a href="${appUrl}">Keep my streak going →</a></p>` +
          `<p style="color:#888;font-size:12px;">Don't want these reminders? Turn them off from Account settings.</p>`,
      });
      if (result.sent) sent++; else failed++;
    } catch (err) {
      console.error(`[streak-reminder] Failed to email ${user.email}:`, err.message);
      failed++;
    }

    await sleep(150);
  }

  console.log(`[streak-reminder] Done. Sent: ${sent}, skipped: ${skipped}, failed: ${failed}`);
  return { sent, skipped, failed };
}

function scheduleStreakReminders() {
  // 6pm UTC daily -- late enough that most people have had a chance to act,
  // early enough to still be useful before "today" rolls over for them.
  cron.schedule('0 18 * * *', () => {
    sendStreakReminders().catch(err => console.error('[streak-reminder] Unhandled error:', err));
  });
  console.log('[streak-reminder] Scheduled daily for 6pm UTC.');
}

module.exports = { scheduleStreakReminders, sendStreakReminders };
