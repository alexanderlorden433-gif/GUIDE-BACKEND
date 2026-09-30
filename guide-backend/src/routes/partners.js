const express = require('express');
const rateLimit = require('express-rate-limit');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

const partnersLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 100,
  message: { error: 'Too many requests. Please try again shortly.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(partnersLimiter);

function isOwner(req) {
  return !!(process.env.OWNER_EMAIL &&
    req.user.email.toLowerCase() === process.env.OWNER_EMAIL.toLowerCase());
}
function requireOwner(req, res, next) {
  if (!isOwner(req)) return res.status(403).json({ error: 'Not authorized.' });
  next();
}

// ---------- GET /api/partners ----------
// Visible to every signed-in user -- this is a public showcase, not
// user-generated content.
router.get('/', async (req, res) => {
  const partners = await prisma.partner.findMany({
    orderBy: [{ sortOrder: 'asc' }, { createdAt: 'asc' }],
  });
  res.json({ partners, isOwner: isOwner(req) });
});

// ---------- POST /api/partners ----------
router.post('/', requireOwner, async (req, res) => {
  const name = String(req.body.name || '').trim().slice(0, 80);
  const description = String(req.body.description || '').trim().slice(0, 400);
  const websiteUrl = String(req.body.websiteUrl || '').trim().slice(0, 300);
  const emoji = String(req.body.emoji || '🤝').trim().slice(0, 8) || '🤝';
  const sortOrder = Number.isFinite(req.body.sortOrder) ? req.body.sortOrder : 0;

  if (!name || !description) {
    return res.status(400).json({ error: 'A name and description are required.' });
  }
  if (websiteUrl && !/^https?:\/\//i.test(websiteUrl)) {
    return res.status(400).json({ error: 'Website URL must start with http:// or https://.' });
  }

  const partner = await prisma.partner.create({
    data: { name, description, websiteUrl: websiteUrl || null, emoji, sortOrder },
  });
  res.status(201).json(partner);
});

// ---------- PUT /api/partners/:id ----------
router.put('/:id', requireOwner, async (req, res) => {
  const name = String(req.body.name || '').trim().slice(0, 80);
  const description = String(req.body.description || '').trim().slice(0, 400);
  const websiteUrl = String(req.body.websiteUrl || '').trim().slice(0, 300);
  const emoji = String(req.body.emoji || '🤝').trim().slice(0, 8) || '🤝';
  const sortOrder = Number.isFinite(req.body.sortOrder) ? req.body.sortOrder : 0;

  if (!name || !description) {
    return res.status(400).json({ error: 'A name and description are required.' });
  }
  if (websiteUrl && !/^https?:\/\//i.test(websiteUrl)) {
    return res.status(400).json({ error: 'Website URL must start with http:// or https://.' });
  }

  try {
    const partner = await prisma.partner.update({
      where: { id: req.params.id },
      data: { name, description, websiteUrl: websiteUrl || null, emoji, sortOrder },
    });
    res.json(partner);
  } catch (e) {
    res.status(404).json({ error: 'Partner not found.' });
  }
});

// ---------- DELETE /api/partners/:id ----------
router.delete('/:id', requireOwner, async (req, res) => {
  try {
    await prisma.partner.delete({ where: { id: req.params.id } });
    res.json({ message: 'Partner deleted.' });
  } catch (e) {
    res.status(404).json({ error: 'Partner not found.' });
  }
});

module.exports = router;
