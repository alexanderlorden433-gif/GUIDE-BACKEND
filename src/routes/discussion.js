const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { notifyUser } = require('../notifications');

const router = express.Router();
router.use(requireAuth);

// Reads happen a lot more than writes, so give them plenty of room.
const readLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 200,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});

// Posting is capped harder — this is public content every signed-in user
// sees, so it's worth a stricter limit against spam than a read-only route.
const writeLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 30,
  message: { error: 'You\'re posting quickly -- please slow down and try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});

function requireOwner(req) {
  return !!(process.env.OWNER_EMAIL &&
    req.user.email.toLowerCase() === process.env.OWNER_EMAIL.toLowerCase());
}

function serializePost(p, currentUserId, isOwner) {
  return {
    id: p.id,
    body: p.body,
    authorEmail: p.author.email,
    isMine: p.authorId === currentUserId,
    canDelete: p.authorId === currentUserId || isOwner,
    createdAt: p.createdAt,
    replies: (p.replies || [])
      .sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt))
      .map(r => ({
        id: r.id,
        body: r.body,
        authorEmail: r.author.email,
        isMine: r.authorId === currentUserId,
        canDelete: r.authorId === currentUserId || isOwner,
        createdAt: r.createdAt,
      })),
  };
}

// ---------- GET /api/discussion/:nicheId ----------
router.get('/:nicheId', readLimiter, async (req, res) => {
  const { nicheId } = req.params;
  const posts = await prisma.discussionPost.findMany({
    where: { nicheId, parentId: null },
    orderBy: { createdAt: 'desc' },
    take: 100,
    include: {
      author: { select: { email: true } },
      replies: { include: { author: { select: { email: true } } } },
    },
  });
  const isOwner = requireOwner(req);
  res.json({ posts: posts.map(p => serializePost(p, req.user.id, isOwner)), isOwner });
});

// ---------- POST /api/discussion/:nicheId ----------
// A new top-level post.
router.post('/:nicheId', writeLimiter, async (req, res) => {
  const { nicheId } = req.params;
  const body = String(req.body.body || '').trim().slice(0, 1000);
  if (!body) return res.status(400).json({ error: 'Write something before posting.' });

  const post = await prisma.discussionPost.create({
    data: { nicheId, authorId: req.user.id, body },
    include: { author: { select: { email: true } }, replies: true },
  });
  res.status(201).json(serializePost(post, req.user.id, requireOwner(req)));
});

// ---------- POST /api/discussion/:nicheId/:postId/reply ----------
router.post('/:nicheId/:postId/reply', writeLimiter, async (req, res) => {
  const { nicheId, postId } = req.params;
  const body = String(req.body.body || '').trim().slice(0, 500);
  if (!body) return res.status(400).json({ error: 'Write something before replying.' });

  const parent = await prisma.discussionPost.findUnique({ where: { id: postId } });
  if (!parent || parent.nicheId !== nicheId) {
    return res.status(404).json({ error: 'Post not found.' });
  }
  if (parent.parentId) {
    return res.status(400).json({ error: 'Replies can only be added to a top-level post.' });
  }

  const reply = await prisma.discussionPost.create({
    data: { nicheId, authorId: req.user.id, body, parentId: postId },
    include: { author: { select: { email: true } } },
  });

  if (parent.authorId !== req.user.id) {
    notifyUser(parent.authorId, {
      type: 'discussion_reply',
      title: 'Someone replied to your post',
      body: body.slice(0, 140),
      link: { view: 'niche', nicheId, tab: 'discussion' },
    }).catch(() => {});
  }

  res.status(201).json({
    id: reply.id,
    body: reply.body,
    authorEmail: reply.author.email,
    isMine: true,
    canDelete: true,
    createdAt: reply.createdAt,
  });
});

// ---------- DELETE /api/discussion/post/:postId ----------
// Deletes a post (and, if it's a top-level post, its replies cascade via
// the schema's onDelete: Cascade). Only the author or the owner can delete.
router.delete('/post/:postId', writeLimiter, async (req, res) => {
  const post = await prisma.discussionPost.findUnique({ where: { id: req.params.postId } });
  if (!post) return res.status(404).json({ error: 'Post not found.' });
  if (post.authorId !== req.user.id && !requireOwner(req)) {
    return res.status(403).json({ error: 'Not authorized.' });
  }
  await prisma.discussionPost.delete({ where: { id: req.params.postId } });
  res.json({ message: 'Post deleted.' });
});

module.exports = router;
