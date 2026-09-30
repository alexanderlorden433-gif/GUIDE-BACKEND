const prisma = require('./db');

// Avoids visually-ambiguous characters (0/O, 1/I/L) since people read these
// off a screen and type them into a link or a box.
const REFERRAL_CHARS = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';

function randomReferralCode() {
  let code = '';
  for (let i = 0; i < 7; i++) {
    code += REFERRAL_CHARS[Math.floor(Math.random() * REFERRAL_CHARS.length)];
  }
  return code;
}

async function makeUniqueReferralCode() {
  for (let i = 0; i < 8; i++) {
    const code = randomReferralCode();
    const existing = await prisma.user.findUnique({ where: { referralCode: code } });
    if (!existing) return code;
  }
  // Astronomically unlikely to be reached, but never loop forever.
  return randomReferralCode() + Date.now().toString(36).toUpperCase();
}

// Existing accounts (created before the referral feature shipped) have
// referralCode = null. This backfills one lazily on first read instead of
// requiring a data migration against the live database.
async function ensureReferralCode(user) {
  if (user.referralCode) return user;
  const referralCode = await makeUniqueReferralCode();
  return prisma.user.update({
    where: { id: user.id },
    data: { referralCode },
  });
}

module.exports = { randomReferralCode, makeUniqueReferralCode, ensureReferralCode };
