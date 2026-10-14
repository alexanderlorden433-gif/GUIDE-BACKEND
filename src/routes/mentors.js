const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { publicName } = require('../publicName');
const { requireAuth } = require('../middleware/auth');
const { notifyUsers } = require('../notifications');

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

// ---------- GET /api/mentors/all/search?q= ----------
// Searches mentor display names/bios across every chapter at once, for the
// global search bar. Must be declared before '/:nicheId' so Express doesn't
// treat "all" as a nicheId. Same visibility rule as the per-chapter list —
// these profiles are already public to every signed-in user.
router.get('/all/search', async (req, res) => {
  const q = String(req.query.q || '').trim();
  if (!q) return res.json({ results: [] });

  const profiles = await prisma.mentorProfile.findMany({
    where: {
      OR: [
        { displayName: { contains: q, mode: 'insensitive' } },
        { bio: { contains: q, mode: 'insensitive' } },
      ],
    },
    orderBy: { updatedAt: 'desc' },
    take: 20,
  });

  res.json({
    results: profiles.map(p => ({
      nicheId: p.nicheId,
      displayName: p.displayName,
      bio: p.bio,
      lookingFor: p.lookingFor,
    })),
  });
});

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
      authorName: publicName(p.author.email),
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

  const existing = await prisma.mentorProfile.findUnique({
    where: { nicheId_authorId: { nicheId, authorId: req.user.id } },
  });

  const profile = await prisma.mentorProfile.upsert({
    where: { nicheId_authorId: { nicheId, authorId: req.user.id } },
    update: { displayName, bio, contact, lookingFor },
    create: { nicheId, authorId: req.user.id, displayName, bio, contact, lookingFor },
  });

  // Only notify on a genuinely new profile, not every edit, and only the
  // people already following this chapter -- not the whole user base.
  if (!existing) {
    const followers = await prisma.user.findMany({ select: { id: true, dataBlob: true } });
    const followerIds = followers
      .filter(u => u.id !== req.user.id && Array.isArray(u.dataBlob?.niches) && u.dataBlob.niches.includes(nicheId))
      .map(u => u.id);
    notifyUsers(followerIds, {
      type: 'new_mentor',
      title: `New mentor in your chapter: ${displayName}`,
      body: bio.slice(0, 140),
      link: { view: 'niche', nicheId, tab: 'mentors' },
    }).catch(() => {});
  }

  res.json({
    displayName: profile.displayName,
    bio: profile.bio,
    lookingFor: profile.lookingFor,
    contact: profile.contact,
    authorName: publicName(req.user.email),
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
