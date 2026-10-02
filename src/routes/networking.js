const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { notifyUser } = require('../notifications');

const router = express.Router();
router.use(requireAuth);

const netLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 60,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(netLimiter);

// ---------- GET /api/networking/matches ----------
// Returns potential connections: users who share at least one niche with the
// requesting user, excluding anyone they've already sent/received a request
// to/from. Returns up to 20 matches.
router.get('/matches', async (req, res) => {
  try {
    const me = await prisma.user.findUnique({
      where: { id: req.user.id },
      select: { dataBlob: true },
    });
    const myNiches = (me?.dataBlob?.niches) || [];
    if (myNiches.length === 0) {
      return res.json({ matches: [] });
    }

    // Get IDs of users we already have a connection with
    const existingRequests = await prisma.networkRequest.findMany({
      where: {
        OR: [
          { fromUserId: req.user.id },
          { toUserId: req.user.id },
        ],
      },
      select: { fromUserId: true, toUserId: true },
    });
    const excludeIds = new Set([req.user.id]);
    existingRequests.forEach(r => {
      excludeIds.add(r.fromUserId);
      excludeIds.add(r.toUserId);
    });

    // Find users who share niches
    const allUsers = await prisma.user.findMany({
      where: { id: { notIn: Array.from(excludeIds) } },
      select: { id: true, email: true, dataBlob: true },
    });

    const matches = allUsers
      .map(u => {
        const blob = u.dataBlob || {};
        const theirNiches = blob.niches || [];
        const shared = myNiches.filter(n => theirNiches.includes(n));
        if (shared.length === 0) return null;
        return {
          userId: u.id,
          email: u.email,
          initial: u.email.charAt(0).toUpperCase(),
          sharedNiches: shared,
          completedCount: Array.isArray(blob.completed) ? blob.completed.length : 0,
        };
      })
      .filter(Boolean)
      .sort((a, b) => b.sharedNiches.length - a.sharedNiches.length)
      .slice(0, 20);

    res.json({ matches });
  } catch (err) {
    console.error('Network matches error:', err);
    res.status(500).json({ error: 'Failed to load matches.' });
  }
});

// ---------- POST /api/networking/connect ----------
// Send a connection request to another user.
router.post('/connect', async (req, res) => {
  try {
    const toUserId = String(req.body.toUserId || '');
    const nicheId = req.body.nicheId || null;

    if (!toUserId || toUserId === req.user.id) {
      return res.status(400).json({ error: 'Invalid user.' });
    }

    const target = await prisma.user.findUnique({ where: { id: toUserId } });
    if (!target) return res.status(404).json({ error: 'User not found.' });

    // Check if request already exists in either direction
    const existing = await prisma.networkRequest.findFirst({
      where: {
        OR: [
          { fromUserId: req.user.id, toUserId },
          { fromUserId: toUserId, toUserId: req.user.id },
        ],
      },
    });
    if (existing) {
      return res.status(409).json({ error: 'Connection already exists.' });
    }

    const request = await prisma.networkRequest.create({
      data: { fromUserId: req.user.id, toUserId, nicheId },
    });

    // Notify the target user
    notifyUser(toUserId, {
      type: 'network_request',
      title: 'Someone wants to connect!',
      body: 'A fellow Guide member in your niche wants to network with you.',
      link: { view: 'network' },
    }).catch(() => {});

    res.status(201).json({ id: request.id, status: 'pending' });
  } catch (err) {
    console.error('Connect error:', err);
    res.status(500).json({ error: 'Failed to send connection request.' });
  }
});

// ---------- GET /api/networking/connections ----------
// Returns accepted connections and pending requests.
router.get('/connections', async (req, res) => {
  try {
    const [sent, received] = await Promise.all([
      prisma.networkRequest.findMany({
        where: { fromUserId: req.user.id },
        include: { toUser: { select: { id: true, email: true, dataBlob: true } } },
        orderBy: { createdAt: 'desc' },
      }),
      prisma.networkRequest.findMany({
        where: { toUserId: req.user.id },
        include: { fromUser: { select: { id: true, email: true, dataBlob: true } } },
        orderBy: { createdAt: 'desc' },
      }),
    ]);

    res.json({ sent, received });
  } catch (err) {
    console.error('Connections error:', err);
    res.status(500).json({ error: 'Failed to load connections.' });
  }
});

// ---------- PUT /api/networking/:id/respond ----------
// Accept or decline a connection request.
router.put('/:id/respond', async (req, res) => {
  try {
    const status = String(req.body.status || '');
    if (!['accepted', 'declined'].includes(status)) {
      return res.status(400).json({ error: 'Status must be "accepted" or "declined".' });
    }

    const request = await prisma.networkRequest.findUnique({
      where: { id: req.params.id },
    });
    if (!request) return res.status(404).json({ error: 'Request not found.' });
    if (request.toUserId !== req.user.id) {
      return res.status(403).json({ error: 'Not your request to respond to.' });
    }

    const updated = await prisma.networkRequest.update({
      where: { id: req.params.id },
      data: { status },
    });

    if (status === 'accepted') {
      notifyUser(request.fromUserId, {
        type: 'network_accepted',
        title: 'Connection accepted!',
        body: 'Your networking request was accepted.',
        link: { view: 'network' },
      }).catch(() => {});
    }

    res.json({ id: updated.id, status: updated.status });
  } catch (err) {
    console.error('Respond to request error:', err);
    res.status(500).json({ error: 'Failed to respond.' });
  }
});

module.exports = router;
