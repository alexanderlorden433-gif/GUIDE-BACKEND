const express = require('express');
const bcrypt = require('bcryptjs');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

// ---------- GET /api/account ----------
// Returns everything the frontend needs on login: isPro, plan, and the full
// data blob (completed guides, tools, streak, bookmarks, etc).
router.get('/', async (req, res) => {
  const user = await prisma.user.findUnique({ where: { id: req.user.id } });
  if (!user) return res.status(404).json({ error: 'Account not found.' });

  // The app owner's account (set via OWNER_EMAIL) always has full Pro access,
  // regardless of what's actually stored — no real payment involved. This is
  // checked server-side, on every request, so it can't be spoofed by editing
  // anything in the browser.
  const isOwner = process.env.OWNER_EMAIL &&
    user.email.toLowerCase() === process.env.OWNER_EMAIL.toLowerCase();

  res.json({
    email: user.email,
    isPro: isOwner ? true : user.isPro,
    planType: isOwner ? 'lifetime' : user.planType,
    data: user.dataBlob,
  });
});

// ---------- PUT /api/account ----------
// The frontend currently saves its entire local state as one JSON object on
// every change (see saveProgress() in the app). This endpoint mirrors that
// directly so the rest of the app's logic barely has to change — it just
// calls this instead of window.storage.set().
router.put('/', async (req, res) => {
  const { data } = req.body;
  if (typeof data !== 'object' || data === null) {
    return res.status(400).json({ error: 'Missing or invalid "data" object.' });
  }

  const user = await prisma.user.update({
    where: { id: req.user.id },
    data: { dataBlob: data },
  });

  res.json({ data: user.dataBlob });
});

// ---------- PUT /api/account/password ----------
router.put('/password', async (req, res) => {
  const currentPassword = String(req.body.currentPassword || '');
  const newPassword = String(req.body.newPassword || '');

  if (newPassword.length < 8) {
    return res.status(400).json({ error: 'New password must be at least 8 characters.' });
  }

  const user = await prisma.user.findUnique({ where: { id: req.user.id } });
  const matches = await bcrypt.compare(currentPassword, user.passwordHash);
  if (!matches) {
    return res.status(401).json({ error: 'Current password is incorrect.' });
  }

  const passwordHash = await bcrypt.hash(newPassword, 12);
  await prisma.user.update({ where: { id: user.id }, data: { passwordHash } });

  res.json({ message: 'Password updated.' });
});

// ---------- DELETE /api/account ----------
// Permanently deletes the account and all its data. The frontend already
// requires a two-click confirmation before calling this.
router.delete('/', async (req, res) => {
  await prisma.user.delete({ where: { id: req.user.id } });
  res.json({ message: 'Account deleted.' });
});

module.exports = router;
