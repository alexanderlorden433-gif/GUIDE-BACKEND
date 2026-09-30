const express = require('express');
const rateLimit = require('express-rate-limit');
const { requireAuth } = require('../middleware/auth');
const { sendEmail } = require('../email');

const router = express.Router();
router.use(requireAuth);

// This just triggers a notification email — it doesn't need to be called
// often, so a modest limit is plenty to stop it being used to spam the
// configured admin inbox.
const alertLimiter = rateLimit({
  windowMs: 60 * 60 * 1000, // 1 hour
  max: 20,
  message: { error: 'Too many requests. Please try again later.' },
  standardHeaders: true,
  legacyHeaders: false,
});
router.use(alertLimiter);

// ---------- POST /api/mentor-alert ----------
// Called by the frontend whenever someone creates or updates a mentor
// profile in the Mentor Directory. Sends a notification email to whoever is
// configured as ADMIN_ALERT_EMAIL so the team knows a new mentor listing
// went up, without needing to check the app itself.
//
// This intentionally does NOT store the mentor profile in the database —
// mentor profiles themselves still live in the app's own storage. This
// endpoint's only job is the email alert.
router.post('/', async (req, res) => {
  const { nicheId, nicheName, displayName, bio, lookingFor, contact } = req.body;

  if (!nicheName || !displayName || !bio) {
    return res.status(400).json({ error: 'Missing required fields (nicheName, displayName, bio).' });
  }

  const adminEmail = process.env.ADMIN_ALERT_EMAIL;
  if (!adminEmail) {
    // Don't fail the request just because alerting isn't configured yet —
    // the mentor profile itself was already saved successfully by this point.
    console.warn('ADMIN_ALERT_EMAIL is not set — skipping mentor alert email.');
    return res.json({ alerted: false, reason: 'not_configured' });
  }

  const lookingForText = Array.isArray(lookingFor) && lookingFor.length
    ? lookingFor.join(', ')
    : 'unspecified';

  const result = await sendEmail({
    to: adminEmail,
    subject: `New mentor application — ${nicheName}`,
    text:
      `A new mentor profile was created in ${nicheName}.\n\n` +
      `Applicant: ${req.user.email}\n` +
      `Display name: ${displayName}\n` +
      `Looking for: ${lookingForText}\n` +
      `Bio: ${bio}\n` +
      `Contact info they shared: ${contact || '(none provided)'}\n`,
    html:
      `<p>A new mentor profile was created in <strong>${escapeHtml(nicheName)}</strong>.</p>` +
      `<p><strong>Applicant account:</strong> ${escapeHtml(req.user.email)}<br>` +
      `<strong>Display name:</strong> ${escapeHtml(displayName)}<br>` +
      `<strong>Looking for:</strong> ${escapeHtml(lookingForText)}<br>` +
      `<strong>Bio:</strong> ${escapeHtml(bio)}<br>` +
      `<strong>Contact info they shared:</strong> ${escapeHtml(contact || '(none provided)')}</p>`,
  });

  res.json({ alerted: result.sent });
});

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

module.exports = router;
