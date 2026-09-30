const Stripe = require('stripe');

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY, {
  apiVersion: '2024-06-20',
});

/**
 * Creates a Stripe Checkout Session for either the monthly subscription
 * or the one-time lifetime purchase, tied to a specific user.
 */
async function createCheckoutSession({ user, plan }) {
  const priceId =
    plan === 'lifetime'
      ? process.env.STRIPE_PRICE_LIFETIME
      : process.env.STRIPE_PRICE_MONTHLY;

  if (!priceId) {
    throw new Error(`No Stripe price configured for plan "${plan}"`);
  }

  const session = await stripe.checkout.sessions.create({
    mode: plan === 'lifetime' ? 'payment' : 'subscription',
    customer_email: user.stripeCustomerId ? undefined : user.email,
    customer: user.stripeCustomerId || undefined,
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${process.env.APP_URL}/billing/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${process.env.APP_URL}/billing/cancelled`,
    metadata: {
      userId: user.id,
      plan,
    },
  });

  return session;
}

/**
 * Creates a Stripe Billing Portal session so an existing customer can manage
 * or cancel their subscription without you building that UI yourself.
 */
async function createPortalSession({ user }) {
  if (!user.stripeCustomerId) {
    throw new Error('User has no Stripe customer yet — nothing to manage.');
  }
  const session = await stripe.billingPortal.sessions.create({
    customer: user.stripeCustomerId,
    return_url: `${process.env.APP_URL}/account`,
  });
  return session;
}

module.exports = { stripe, createCheckoutSession, createPortalSession };
