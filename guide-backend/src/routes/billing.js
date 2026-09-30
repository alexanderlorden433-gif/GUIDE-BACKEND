const express = require('express');
const prisma = require('../db');
const { requireAuth } = require('../middleware/auth');
const { stripe, createCheckoutSession, createPortalSession } = require('../stripe');

const router = express.Router();

// ---------- POST /api/billing/checkout ----------
// Body: { plan: "monthly" | "lifetime" }
// Returns a Stripe Checkout URL for the frontend to redirect the user to.
router.post('/checkout', requireAuth, async (req, res) => {
  try {
    const plan = req.body.plan === 'lifetime' ? 'lifetime' : 'monthly';
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
    res.status(400).json({ error: err.message });
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

        await prisma.user.update({
          where: { id: userId },
          data: {
            isPro: true,
            planType: plan,
            stripeCustomerId: session.customer || undefined,
            stripeSubscriptionId:
              plan === 'monthly' ? session.subscription || undefined : undefined,
          },
        });
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
        await prisma.user.updateMany({
          where: { stripeSubscriptionId: subscription.id },
          data: { isPro: false, stripeSubscriptionId: null },
        });
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
