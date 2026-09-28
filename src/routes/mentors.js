const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

// Generous, but still a real limit — mentor profiles are read a lot more
// than they're written, and this covers both.
const mentorLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(mentorLimiter);

// ---------- GET /api/mentors/:nicheId ----------
// Returns every mentor profile for this chapter — this is the one place in
// the app where one user's data is visible to every other signed-in user,
// by design (it's an opt-in public directory).
router.get('/:nicheId', async (req, res) => {
  const { nicheId } = req.params;
  const profiles = await prisma.mentorProfile.findMany({
    where: { nicheId },
    orderBy: { updatedAt: 'desc' },
    include: { author: { select: { email: true } } },
  });

  res.json({
    profiles: profiles.map(p => ({
      displayName: p.displayName,
      bio: p.bio,
      lookingFor: p.lookingFor,
      contact: p.contact,
      authorEmail: p.author.email,
      isMine: p.authorId === req.user.id,
    })),
  });
});

// ---------- PUT /api/mentors/:nicheId ----------
// Creates or updates the current user's own profile for this chapter only —
// authorId always comes from the authenticated session, never the request
// body, so nobody can create or edit a profile as someone else.
router.put('/:nicheId', async (req, res) => {
  const { nicheId } = req.params;
  const displayName = String(req.body.displayName || '').trim().slice(0, 40);
  const bio = String(req.body.bio || '').trim().slice(0, 300);
  const contact = String(req.body.contact || '').trim().slice(0, 200);
  const lookingFor = Array.isArray(req.body.lookingFor)
    ? req.body.lookingFor.filter(v => v === 'mentor' || v === 'network')
    : [];

  if (!displayName || !bio || lookingFor.length === 0) {
    return res.status(400).json({ error: 'A display name, a bio, and at least one of "mentor" or "network" are required.' });
  }

  const profile = await prisma.mentorProfile.upsert({
    where: { nicheId_authorId: { nicheId, authorId: req.user.id } },
    update: { displayName, bio, contact, lookingFor },
    create: { nicheId, authorId: req.user.id, displayName, bio, contact, lookingFor },
  });

  res.json({
    displayName: profile.displayName,
    bio: profile.bio,
    lookingFor: profile.lookingFor,
    contact: profile.contact,
    authorEmail: req.user.email,
    isMine: true,
  });
});

// ---------- DELETE /api/mentors/:nicheId ----------
// Deletes the current user's own profile for this chapter. Silently
// succeeds if there wasn't one — matches the "delete" button always
// being a safe, idempotent action from the frontend's point of view.
router.delete('/:nicheId', async (req, res) => {
  const { nicheId } = req.params;
  await prisma.mentorProfile.deleteMany({
    where: { nicheId, authorId: req.user.id },
  });
  res.json({ message: 'Profile deleted.' });
});

module.exports = router;
