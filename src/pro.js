// Who counts as Pro, in one place (the same rule /api/account uses):
// the owner, preview accounts, paying members, and referral bonuses that have not expired.
const prisma = require('./db');

function listEnv(name) {
  return (process.env[name] || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}
function isOwnerEmail(email) {
  return !!(process.env.OWNER_EMAIL && String(email || '').toLowerCase() === process.env.OWNER_EMAIL.trim().toLowerCase());
}
async function isProUser(userId) {
  const user = await prisma.user.findUnique({ where: { id: userId }, select: { email: true, isPro: true, bonusProUntil: true } });
  if (!user) return false;
  const email = user.email.toLowerCase();
  return isOwnerEmail(email) || listEnv('PREVIEW_EMAILS').includes(email) || !!user.isPro ||
    !!(user.bonusProUntil && user.bonusProUntil > new Date());
}

module.exports = { isProUser, isOwnerEmail, listEnv };
