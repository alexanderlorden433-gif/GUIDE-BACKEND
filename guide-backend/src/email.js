/**
 * Minimal email-sending utility using Resend (https://resend.com).
 *
 * Resend was chosen because it has a generous free tier, a simple HTTP API
 * (no SMTP setup), and works well for transactional alerts like this one.
 * If you'd rather use a different provider (SendGrid, Postmark, AWS SES),
 * you only need to change the implementation of `sendEmail` below — nothing
 * else in the codebase needs to change.
 *
 * Required env vars (see .env.example):
 *   RESEND_API_KEY   - from https://resend.com/api-keys
 *   EMAIL_FROM       - the "from" address. Must be on a domain you've verified
 *                       in Resend, OR use their default onboarding sender
 *                       (onboarding@resend.dev) for testing before you verify
 *                       your own domain.
 *   ADMIN_ALERT_EMAIL - where alert emails (like new mentor applications) are sent.
 */

async function sendEmail({ to, subject, html, text }) {
  const apiKey = process.env.RESEND_API_KEY;
  const from = process.env.EMAIL_FROM;

  if (!apiKey || !from) {
    console.warn('Email not sent — RESEND_API_KEY or EMAIL_FROM is not configured.');
    return { sent: false, reason: 'not_configured' };
  }

  try {
    const response = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ from, to, subject, html, text }),
    });

    if (!response.ok) {
      const body = await response.text();
      console.error('Resend API error:', response.status, body);
      return { sent: false, reason: 'api_error', status: response.status };
    }

    return { sent: true };
  } catch (err) {
    console.error('Failed to send email:', err);
    return { sent: false, reason: 'network_error' };
  }
}

module.exports = { sendEmail };
