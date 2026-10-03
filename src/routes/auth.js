const express = require('express');
const bcrypt = require('bcryptjs');
const crypto = require('crypto');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { signToken } = require('../middleware/auth');
const { sendEmail } = require('../email');
const { makeUniqueReferralCode } = require('../referral');
const { notifyUser } = require('../notifications');
const { sendWelcomeEmail } = require('../onboardingDrip');

const router = express.Router();

// Slow down brute-force attempts on login specifically.
const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 10,
  message: { error: 'Too many login attempts. Please try again in a few minutes.' },
  standardHeaders: true,
  legacyHeaders: false,
});

// Forgot-password now sends a real email per request, so this also protects
// against someone using it to spam an inbox or burn through your email
// provider's sending quota.
const forgotPasswordLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 5,
  message: { error: 'Too many reset requests. Please try again in a few minutes.' },
  standardHeaders: true,
  legacyHeaders: false,
});

function isValidEmail(email) {
  return typeof email === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// ---------- POST /api/auth/signup ----------
router.post('/signup', async (req, res) => {
  try {
    const email = String(req.body.email || '').trim().toLowerCase();
    const password = String(req.body.password || '');

    if (!isValidEmail(email)) {
      return res.status(400).json({ error: 'Enter a valid email.' });
    }
    if (password.length < 8) {
      return res.status(400).json({ error: 'Password must be at least 8 characters.' });
    }

    const existing = await prisma.user.findUnique({ where: { email } });
    if (existing) {
      return res.status(409).json({ error: 'An account with that email already exists.' });
    }

    const referralCodeInput = String(req.body.referralCode || '').trim().toUpperCase();
    let referredByCode = null;
    let referrerId = null;
    if (referralCodeInput) {
      const referrer = await prisma.user.findUnique({ where: { referralCode: referralCodeInput } });
      if (referrer) {
        referredByCode = referrer.referralCode;
        referrerId = referrer.id;
      }
    }

    const passwordHash = await bcrypt.hash(password, 12);
    const myReferralCode = await makeUniqueReferralCode();
    const user = await prisma.user.create({
      data: {
        email,
        passwordHash,
        referralCode: myReferralCode,
        referredByCode,
        dataBlob: {
          completed: [],
          tools: {},
          niches: [],
          streak: { count: 0, lastDate: null },
          bookmarks: [],
          lastVisited: null,
          hasSeenTour: false,
        },
      },
    });

    if (referrerId) {
      notifyUser(referrerId, {
        type: 'referral_signup',
        title: 'Someone joined using your invite link',
        body: 'You\'ll get 10 days of free Pro automatically if they go Pro.',
        link: { view: 'invite' },
      }).catch(() => {});
    }

    // Fire-and-forget welcome email (first in the onboarding drip sequence)
    sendWelcomeEmail(user).catch(() => {});

    const previewEmails = (process.env.PREVIEW_EMAILS || '').split(',').map(e => e.trim().toLowerCase()).filter(Boolean);
    const isPreviewAcct = previewEmails.includes(user.email.toLowerCase());
    const isOwnerAcct = process.env.OWNER_EMAIL && user.email.toLowerCase() === process.env.OWNER_EMAIL.toLowerCase();

    const token = signToken(user);
    res.status(201).json({
      token,
      user: { id: user.id, email: user.email, isPro: (isOwnerAcct || isPreviewAcct) ? true : user.isPro },
    });
  } catch (err) {
    console.error('Signup error:', err);
    res.status(500).json({ error: 'Something went wrong creating your account.' });
  }
});

// ---------- POST /api/auth/login ----------
router.post('/login', loginLimiter, async (req, res) => {
  try {
    const email = String(req.body.email || '').trim().toLowerCase();
    const password = String(req.body.password || '');

    const user = await prisma.user.findUnique({ where: { email } });
    // Compare against a dummy hash even when no user exists, so response
    // timing doesn't reveal whether an email is registered.
    const hashToCheck = user ? user.passwordHash : '$2a$12$invalidsaltinvalidsaltinvalidsO';
    const passwordMatches = await bcrypt.compare(password, hashToCheck);

    if (!user || !passwordMatches) {
      return res.status(401).json({ error: 'Incorrect email or password.' });
    }

    const previewEmailsL = (process.env.PREVIEW_EMAILS || '').split(',').map(e => e.trim().toLowerCase()).filter(Boolean);
    const isPreviewL = previewEmailsL.includes(user.email.toLowerCase());
    const isOwnerL = process.env.OWNER_EMAIL && user.email.toLowerCase() === process.env.OWNER_EMAIL.toLowerCase();

    const token = signToken(user);
    res.json({
      token,
      user: { id: user.id, email: user.email, isPro: (isOwnerL || isPreviewL) ? true : user.isPro },
    });
  } catch (err) {
    console.error('Login error:', err);
    res.status(500).json({ error: 'Something went wrong logging you in.' });
  }
});

// ---------- POST /api/auth/forgot-password ----------
// Generates a one-time reset token and emails a reset link.
router.post('/forgot-password', forgotPasswordLimiter, async (req, res) => {
  try {
    const email = String(req.body.email || '').trim().toLowerCase();
    const user = await prisma.user.findUnique({ where: { email } });

    if (user) {
      const rawToken = crypto.randomBytes(32).toString('hex');
      const tokenHash = crypto.createHash('sha256').update(rawToken).digest('hex');

      await prisma.passwordReset.create({
        data: {
          userId: user.id,
          tokenHash,
          expiresAt: new Date(Date.now() + 60 * 60 * 1000), // 1 hour
        },
      });

      const resetLink = `${process.env.APP_URL}/reset-password?token=${rawToken}`;

      // Fire-and-forget on purpose: if the email fails to send, we still want
      // to return the same generic response as the "email not found" case
      // below, so a failed send doesn't accidentally reveal account
      // existence through a different error response.
      sendEmail({
        to: email,
        subject: 'Reset your password — The Guide',
        text:
          `Someone requested a password reset for your account.\n\n` +
          `Reset your password: ${resetLink}\n\n` +
          `This link expires in 1 hour. If you didn't request this, you can safely ignore this email — your password hasn't been changed.`,
        html:
          `<p>Someone requested a password reset for your account.</p>` +
          `<p><a href="${resetLink}">Click here to reset your password</a></p>` +
          `<p>This link expires in 1 hour. If you didn't request this, you can safely ignore this email — your password hasn't been changed.</p>`,
      }).then(result => {
        if (!result.sent) {
          console.error(`[password reset] Failed to send email to ${email}: ${result.reason}`);
        }
      });
    }

    // Always return the same response whether or not the email was found.
    res.json({ message: 'If that email is registered, a reset link has been sent.' });
  } catch (err) {
    console.error('Forgot-password error:', err);
    res.status(500).json({ error: 'Something went wrong. Please try again.' });
  }
});

// ---------- POST /api/auth/reset-password ----------
router.post('/reset-password', async (req, res) => {
  try {
    const rawToken = String(req.body.token || '');
    const newPassword = String(req.body.newPassword || '');

    if (newPassword.length < 8) {
      return res.status(400).json({ error: 'Password must be at least 8 characters.' });
    }

    const tokenHash = crypto.createHash('sha256').update(rawToken).digest('hex');
    const record = await prisma.passwordReset.findUnique({ where: { tokenHash } });

    if (!record || record.usedAt || record.expiresAt < new Date()) {
      return res.status(400).json({ error: 'This reset link is invalid or has expired.' });
    }

    const passwordHash = await bcrypt.hash(newPassword, 12);
    await prisma.$transaction([
      prisma.user.update({ where: { id: record.userId }, data: { passwordHash } }),
      prisma.passwordReset.update({ where: { id: record.id }, data: { usedAt: new Date() } }),
    ]);

    res.json({ message: 'Password updated — you can log in with your new password now.' });
  } catch (err) {
    console.error('Reset-password error:', err);
    res.status(500).json({ error: 'Something went wrong. Please try again.' });
  }
});

module.exports = router;
