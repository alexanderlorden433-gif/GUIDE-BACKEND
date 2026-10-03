const express = require('express');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { stripe, createCheckoutSession, createPortalSession } = require('../stripe');
const { notifyUser } = require('../notifications');
const { recordMoney } = require('../analytics');

const router = express.Router();

// ---------- POST /api/billing/checkout ----------
// Body: { plan: "monthly" | "yearly" }
// Returns a Stripe Checkout URL for the frontend to redirect the user to.
router.post('/checkout', requireAuth, async (req, res) => {
  try {
    const plan = req.body.plan === 'yearly' ? 'yearly' : 'monthly';
    const user = await prisma.user.findUnique({ where: { id: req.user.id } });
    if (!user) return res.status(404).json({ error: 'Account not found.' });

    const session = await createCheckoutSession({ user, plan });
    res.json({ url: session.url });
  } catch (err) {
    console.error('Checkout session error:', err);
    res.status(500).json({ error: 'Could not start checkout. Please try again.' });
  }
});

// ---------- POST /api/billing/portal ----------
// Lets an existing Pro user manage or cancel their subscription via Stripe's
// hosted portal, instead of you building that UI yourself.
router.post('/portal', requireAuth, async (req, res) => {
  try {
    const user = await prisma.user.findUnique({ where: { id: req.user.id } });
    const session = await createPortalSession({ user });
    res.json({ url: session.url });
  } catch (err) {
    console.error('Portal session error:', err);
    res.status(400).json({ error: 'Could not open billing portal. Please try again.' });
  }
});

// ---------- POST /api/billing/webhook ----------
// Stripe calls this directly (not the frontend). It must receive the RAW
// request body for signature verification — see the express.raw()
// middleware wired up in index.js specifically for this route.
router.post('/webhook', async (req, res) => {
  const signature = req.headers['stripe-signature'];
  let event;

  try {
    event = stripe.webhooks.constructEvent(
      req.body,
      signature,
      process.env.STRIPE_WEBHOOK_SECRET
    );
  } catch (err) {
    console.error('Webhook signature verification failed:', err.message);
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }

  try {
    switch (event.type) {
      case 'checkout.session.completed': {
        const session = event.data.object;
        const userId = session.metadata?.userId;
        const plan = session.metadata?.plan;
        if (!userId) break;

        const wasAlreadyPro = await prisma.user.findUnique({
          where: { id: userId },
          select: { isPro: true, referredByCode: true },
        });

        const updatedUser = await prisma.user.update({
          where: { id: userId },
          data: {
            isPro: true,
            planType: plan,
            stripeCustomerId: session.customer || undefined,
            stripeSubscriptionId: session.subscription || undefined,
          },
        });

        // Live dashboards + revenue-by-channel. Never blocks the webhook.
        recordMoney('purchase', userId, {
          value: typeof session.amount_total === 'number' ? session.amount_total / 100 : undefined,
          plan,
          email: updatedUser.email,
          id: event.id, // Stripe may resend an event; the id keeps it counted once
        });

        // Referral reward: only fires the first time this user goes Pro, so
        // re-subscribing or plan changes don't double-reward the referrer.
        if (!wasAlreadyPro?.isPro && updatedUser.referredByCode) {
          const referrer = await prisma.user.findUnique({
            where: { referralCode: updatedUser.referredByCode },
          });
          if (referrer) {
            const base = referrer.bonusProUntil && referrer.bonusProUntil > new Date()
              ? referrer.bonusProUntil
              : new Date();
            const newBonusUntil = new Date(base.getTime() + 10 * 24 * 60 * 60 * 1000);
            await prisma.user.update({
              where: { id: referrer.id },
              data: { bonusProUntil: newBonusUntil },
            });
            notifyUser(referrer.id, {
              type: 'referral_bonus',
              title: 'You earned 10 days of free Pro 🎉',
              body: 'A friend you invited just went Pro.',
              link: { view: 'invite' },
            }).catch(() => {});
          }
        }
        break;
      }

      case 'customer.subscription.updated': {
        const subscription = event.data.object;
        const isActive = ['active', 'trialing'].includes(subscription.status);
        await prisma.user.updateMany({
          where: { stripeSubscriptionId: subscription.id },
          data: { isPro: isActive },
        });
        break;
      }

      case 'customer.subscription.deleted': {
        const subscription = event.data.object;
        const cancelled = await prisma.user.findFirst({
          where: { stripeSubscriptionId: subscription.id },
          select: { id: true, planType: true },
        });
        if (cancelled) recordMoney('cancel', cancelled.id, { plan: cancelled.planType || undefined, id: event.id });
        await prisma.user.updateMany({
          where: { stripeSubscriptionId: subscription.id },
          data: { isPro: false, stripeSubscriptionId: null },
        });
        break;
      }

      // Renewals (month 2 onwards, or year 2). The first payment is already
      // counted from checkout.session.completed above, so skip that one.
      // Only arrives if "invoice.paid" is ticked on the Stripe webhook.
      case 'invoice.paid': {
        const invoice = event.data.object;
        // Newer Stripe API versions moved the subscription id under "parent".
        const subId = invoice.subscription || invoice.parent?.subscription_details?.subscription;
        if (invoice.billing_reason === 'subscription_cycle' && typeof subId === 'string') {
          const renewing = await prisma.user.findFirst({
            where: { stripeSubscriptionId: subId },
            select: { id: true, planType: true },
          });
          if (renewing) {
            recordMoney('renewal', renewing.id, {
              value: typeof invoice.amount_paid === 'number' ? invoice.amount_paid / 100 : undefined,
              plan: renewing.planType || undefined,
              id: event.id,
            });
          }
        }
        break;
      }

      case 'invoice.payment_failed': {
        const invoice = event.data.object;
        // Optional: email the user that their payment failed. Stripe will
        // retry automatically and send its own dunning emails by default.
        console.log(`Payment failed for customer ${invoice.customer}`);
        break;
      }

      default:
        // Unhandled event types are fine to ignore.
        break;
    }

    res.json({ received: true });
  } catch (err) {
    console.error('Webhook handler error:', err);
    // Return 200 anyway once you've logged the error — returning an error
    // status causes Stripe to keep retrying, which can duplicate side effects.
    res.status(200).json({ received: true, error: 'Handled with errors, see server logs.' });
  }
});

module.exports = router;
