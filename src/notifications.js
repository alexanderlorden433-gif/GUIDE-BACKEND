/**
 * In-app notifications -- a lightweight feed, separate from the email
 * reminders in digest.js / streakReminder.js. Other route files call the
 * helpers below at the moment something notification-worthy happens
 * (a referral signs up, a partner is added, a mentor joins a chapter you
 * follow) rather than polling for it later.
 */

const prisma = require('./db');

async function notifyUser(userId, { type, title, body, link }) {
  try {
    await prisma.notification.create({
      data: { userId, type, title, body, link: link || undefined },
    });
  } catch (err) {
    // Notifications are best-effort -- never let a failure here break the
    // real action (signup, partner creation, etc.) that triggered it.
    console.error(`[notifications] Failed to notify user ${userId}:`, err.message);
  }
}

async function notifyUsers(userIds, { type, title, body, link }) {
  if (!userIds || userIds.length === 0) return;
  try {
    await prisma.notification.createMany({
      data: userIds.map(userId => ({ userId, type, title, body, link: link || undefined })),
    });
  } catch (err) {
    console.error('[notifications] Bulk notify failed:', err.message);
  }
}

async function notifyAllUsers({ type, title, body, link }, excludeUserId) {
  const users = await prisma.user.findMany({ select: { id: true } });
  const ids = users.map(u => u.id).filter(id => id !== excludeUserId);
  await notifyUsers(ids, { type, title, body, link });
}

module.exports = { notifyUser, notifyUsers, notifyAllUsers };
