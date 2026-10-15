// Two billing emails, both sent at most once:
//
// 1. "Your Pro trial ends tomorrow": about a day before a free trial turns into a paid plan, so
//    nobody is surprised by the charge. It says the date, the amount, and how to cancel.
// 2. "Still thinking about Pro?": one gentle note to someone who opened the Pro checkout and left
//    without paying (nothing was charged). It is the only reminder they ever get about it.
//
// Both are worked out from Stripe itself (trialing subscriptions, recent checkout sessions), so
// nothing in the checkout or the Stripe webhook changes. An hourly pass sends what is due; the
// "EmailSent" table remembers what went out so nothing is sent twice. Created at startup with
// CREATE TABLE IF NOT EXISTS; declared in prisma/schema.prisma too.
const crypto = require('crypto');
const cron = require('node-cron');
const prisma = require('./db');
const { sendEmail } = require('./email');

const appUrl = () => (process.env.APP_URL || 'https://theguide.company').replace(/\/$/, '');
const supportEmail = () => process.env.SUPPORT_EMAIL || 'TheGuide1@gmail.com';
const HOUR = 3600 * 1000;

const DDL = [
  `CREATE TABLE IF NOT EXISTS "EmailSent" (
    "id" TEXT NOT NULL,
    "kind" TEXT NOT NULL,
    "ref" TEXT NOT NULL,
    "userId" TEXT,
    "sentAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "EmailSent_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "EmailSent_kind_ref_key" ON "EmailSent"("kind", "ref")`,
];

let ready = false;
async function ensureEmailTable() {
  for (let attempt = 0; attempt < 3 && !ready; attempt++) {
    try {
      for (const sql of DDL) await prisma.$executeRawUnsafe(sql);
      ready = true;
      console.log('EmailSent table ready.');
    } catch (err) {
      console.error('EmailSent table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return ready;
}

// Claims the (kind, ref) slot before sending, so two passes can never both send the same email.
async function claim(kind, ref, userId) {
  const n = await prisma.$executeRawUnsafe(
    `INSERT INTO "EmailSent" ("id","kind","ref","userId") VALUES ($1::text,$2::text,$3::text,$4::text) ON CONFLICT ("kind","ref") DO NOTHING`,
    crypto.randomUUID(), kind, String(ref), userId || null);
  return n > 0;
}
async function alreadySent(kind, ref) {
  const rows = await prisma.$queryRawUnsafe(`SELECT 1 FROM "EmailSent" WHERE "kind" = $1::text AND "ref" = $2::text`, kind, String(ref));
  return rows.length > 0;
}
async function findUser({ id, subscriptionId, customerId }) {
  const rows = await prisma.$queryRawUnsafe(
    `SELECT "id","email","isPro","stripeSubscriptionId" FROM "User"
      WHERE ($1::text IS NOT NULL AND "id" = $1::text)
         OR ($2::text IS NOT NULL AND "stripeSubscriptionId" = $2::text)
         OR ($3::text IS NOT NULL AND "stripeCustomerId" = $3::text)
      LIMIT 1`, id || null, subscriptionId || null, customerId || null);
  return rows[0] || null;
}

// ---------------------------------------------------------------- the emails
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
const money = (cents, currency) => {
  const n = (cents || 0) / 100;
  const s = n.toFixed(2).replace(/\.00$/, '');
  return (String(currency || 'usd').toLowerCase() === 'usd' ? '$' : '') + s + (String(currency || 'usd').toLowerCase() === 'usd' ? '' : ' ' + String(currency).toUpperCase());
};
const day = (ms) => new Date(ms).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', timeZone: 'America/New_York' });

function layout({ kicker, title, paras, cta, ctaUrl, foot }) {
  const text = `${title}\n\n${paras.join('\n\n')}\n\n${cta}: ${ctaUrl}\n\n${foot}\nThe Guide · theguide.company`;
  const html =
    `<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px 20px;color:#14211A;background:#FFFFFF;line-height:1.6;font-size:16px">` +
    `<p style="margin:0 0 6px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#6B7B72">${esc(kicker)}</p>` +
    `<h1 style="margin:0 0 18px;font-size:24px;line-height:1.25;color:#0C1310">${esc(title)}</h1>` +
    paras.map(p => `<p style="margin:0 0 16px">${esc(p)}</p>`).join('') +
    `<p style="margin:8px 0 26px"><a href="${ctaUrl}" style="display:inline-block;padding:13px 22px;background:#3FCB93;color:#0C1310;text-decoration:none;border-radius:10px;font-weight:700">${esc(cta)}</a></p>` +
    `<p style="margin:0;font-size:12.5px;color:#6B7B72;border-top:1px solid #E6EEE9;padding-top:14px">${esc(foot)}<br>The Guide · <a href="${appUrl()}" style="color:#6B7B72">theguide.company</a></p>` +
    `</div>`;
  return { text, html };
}

function trialEndingEmail({ endsAt, amountCents, currency, interval }) {
  const per = interval === 'year' ? 'a year' : 'a month';
  const charge = amountCents ? `${money(amountCents, currency)} ${per}` : 'the plan you picked';
  return {
    subject: 'Your Pro trial ends tomorrow',
    ...layout({
      kicker: 'Your Pro trial',
      title: `Your free trial ends in about a day`,
      paras: [
        `It ends on ${day(endsAt)} (New York time). If you keep Pro, nothing changes: your card is charged ${charge} when the trial ends, and you keep every course, the AI mentor, templates and trackers.`,
        `If Pro isn't for you, cancel before then and you won't be charged. In the app, open your account and tap Manage subscription. It takes a few seconds.`,
        `Either way, Module 1 of every course stays free and your progress stays saved.`,
      ],
      cta: 'Open my account',
      ctaUrl: `${appUrl()}/?open=account&utm_source=email&utm_medium=email&utm_campaign=trial_ending`,
      foot: `Questions about billing? Email ${supportEmail()}.`,
    }),
  };
}

function checkoutLeftEmail({ startedAt, prices }) {
  const m = prices && prices.monthly, y = prices && prices.yearly;
  const priceLine = m && y
    ? `Pro is ${money(Math.round(m.amount * 100), m.currency)} a month or ${money(Math.round(y.amount * 100), y.currency)} a year, and you can cancel any time.`
    : 'You can cancel Pro any time.';
  return {
    subject: 'Still thinking about Pro?',
    ...layout({
      kicker: 'The Guide Pro',
      title: 'You were one step from Pro',
      paras: [
        `You opened the Pro checkout on ${day(startedAt)} but didn't finish, so nothing was charged.`,
        `If something got in the way, like a question about the price or the free trial, or a card that didn't go through, email ${supportEmail()} and we'll sort it out.`,
        `${priceLine} Module 1 of every course stays free either way.`,
      ],
      cta: 'Pick up where you left off',
      ctaUrl: `${appUrl()}/?open=upgrade&utm_source=email&utm_medium=email&utm_campaign=checkout_left`,
      foot: 'This is the only reminder we will send about it.',
    }),
  };
}

// ---------------------------------------------------------------- the hourly pass
// stripe and getPrices are passed in so the pass can be tested without a real Stripe account.
async function processBillingEmails({ stripe, getPrices, now = Date.now() } = {}) {
  if (!ready || !stripe) return { trial: 0, checkout: 0 };
  let trial = 0, checkout = 0;

  // 1) trials ending in roughly a day (the hourly pass catches each one about 27 hours out)
  for await (const sub of stripe.subscriptions.list({ status: 'trialing', limit: 100 })) {
    const endsAt = (sub.trial_end || 0) * 1000;
    if (!endsAt || endsAt < now + 12 * HOUR || endsAt > now + 28 * HOUR) continue;
    if (sub.cancel_at_period_end) continue;                       // already cancelled: nothing to warn about
    if (await alreadySent('trial_ending', sub.id)) continue;
    const user = await findUser({ subscriptionId: sub.id, customerId: typeof sub.customer === 'string' ? sub.customer : null });
    if (!user || !user.email) continue;
    if (!(await claim('trial_ending', sub.id, user.id))) continue;
    const item = sub.items && sub.items.data && sub.items.data[0];
    const price = item && item.price;
    const mail = trialEndingEmail({ endsAt, amountCents: price && price.unit_amount, currency: price && price.currency,
                                   interval: price && price.recurring && price.recurring.interval });
    try { await sendEmail({ to: user.email, subject: mail.subject, html: mail.html, text: mail.text }); trial++; }
    catch (err) { console.error('[billing emails] trial email failed:', err.message); }
  }

  // 2) checkouts opened 2 to 48 hours ago and never finished: one note per member, ever
  const since = Math.floor((now - 48 * HOUR) / 1000);
  let prices = null;
  for await (const s of stripe.checkout.sessions.list({ created: { gte: since }, limit: 100 })) {
    if ((s.created || 0) < since) break;                          // newest first: everything after this is older
    if (s.status === 'complete' || s.mode !== 'subscription') continue;
    if ((s.created || 0) * 1000 > now - 2 * HOUR) continue;       // give them time to come back on their own
    const userId = s.metadata && s.metadata.userId;
    if (!userId || await alreadySent('checkout_left', userId)) continue;
    const user = await findUser({ id: userId });
    if (!user || !user.email || user.isPro || user.stripeSubscriptionId) continue;
    if (!(await claim('checkout_left', userId, userId))) continue;
    if (!prices && getPrices) { try { prices = await getPrices(); } catch (e) { prices = {}; } }
    const mail = checkoutLeftEmail({ startedAt: s.created * 1000, prices });
    try { await sendEmail({ to: user.email, subject: mail.subject, html: mail.html, text: mail.text }); checkout++; }
    catch (err) { console.error('[billing emails] checkout email failed:', err.message); }
  }

  if (trial || checkout) console.log(`[billing emails] trial reminders ${trial}, checkout notes ${checkout}`);
  return { trial, checkout };
}

function scheduleBillingEmails() {
  if (!process.env.STRIPE_SECRET_KEY) { console.log('[billing emails] Stripe not configured; not scheduled.'); return; }
  const { stripe, getPlanPrices } = require('./stripe');
  cron.schedule('17 * * * *', () => {
    processBillingEmails({ stripe, getPrices: getPlanPrices }).catch(err => console.error('[billing emails] error:', err.message));
  });
  console.log('[billing emails] Trial reminders and checkout notes scheduled hourly.');
}

module.exports = { ensureEmailTable, scheduleBillingEmails, processBillingEmails, trialEndingEmail, checkoutLeftEmail };
