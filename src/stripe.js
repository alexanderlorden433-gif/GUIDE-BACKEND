const Stripe = require('stripe');

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY, {
  apiVersion: '2024-06-20',
});

/** How long the optional free trial runs. Shown to the customer before they choose it. */
const TRIAL_DAYS = 4;

/**
 * Creates a Stripe Checkout Session for either the monthly or yearly
 * subscription, tied to a specific user.
 */
async function createCheckoutSession({ user, plan, trial }) {
  const priceId =
    plan === 'yearly'
      ? process.env.STRIPE_PRICE_YEARLY
      : process.env.STRIPE_PRICE_MONTHLY;

  if (!priceId) {
    throw new Error(`No Stripe price configured for plan "${plan}"`);
  }

  const session = await stripe.checkout.sessions.create({
    mode: 'subscription',
    customer_email: user.stripeCustomerId ? undefined : user.email,
    customer: user.stripeCustomerId || undefined,
    line_items: [{ price: priceId, quantity: 1 }],
    // The free trial is the customer's choice at checkout, and only ever offered to
    // someone who has never subscribed before — otherwise cancelling and signing up
    // again would farm free months.
    subscription_data: (trial && !user.stripeCustomerId) ? { trial_period_days: TRIAL_DAYS } : undefined,
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
 * A one-time Stripe Checkout for a pack of AI website credits (src/siteCredits.js). The price is written
 * into the session, so nothing has to be set up in the Stripe dashboard. `kind: 'site_credits'` in the
 * metadata is what tells the webhook this is credits, not Pro: it must never turn on Pro.
 */
async function createCreditsCheckout({ user, pack }) {
  const session = await stripe.checkout.sessions.create({
    mode: 'payment',
    // cards (with Apple Pay and Google Pay) are paid on the spot, so the credits can be added straight away
    payment_method_types: ['card'],
    customer: user.stripeCustomerId || undefined,
    customer_email: user.stripeCustomerId ? undefined : user.email,
    line_items: [{
      quantity: 1,
      price_data: {
        currency: 'usd',
        unit_amount: pack.cents,
        product_data: {
          name: `AI website credits (${pack.credits})`,
          description: `${pack.credits} AI writes of your page on The Guide. Credits never expire.`,
        },
      },
    }],
    payment_intent_data: { description: `The Guide: ${pack.credits} AI website credits` },
    success_url: `${process.env.APP_URL}/billing/credits?credits_session={CHECKOUT_SESSION_ID}`,
    cancel_url: `${process.env.APP_URL}/billing/cancelled?open=website`,
    client_reference_id: user.id,
    metadata: { kind: 'site_credits', userId: user.id, pack: pack.id, credits: String(pack.credits) },
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

/**
 * The live prices, straight from Stripe, so the app never advertises a number
 * we don't actually charge. Cached for 10 minutes.
 */
let priceCache = { at: 0, data: null };
async function getPlanPrices() {
  if (priceCache.data && Date.now() - priceCache.at < 10 * 60 * 1000) return priceCache.data;

  const ids = { monthly: process.env.STRIPE_PRICE_MONTHLY, yearly: process.env.STRIPE_PRICE_YEARLY };
  const out = {};
  for (const [plan, id] of Object.entries(ids)) {
    if (!id) continue;
    const price = await stripe.prices.retrieve(id);
    if (price.unit_amount == null) continue;
    out[plan] = {
      amount: price.unit_amount / 100,
      currency: (price.currency || 'usd').toUpperCase(),
      interval: price.recurring ? price.recurring.interval : null,
    };
  }
  if (out.monthly && out.yearly && out.yearly.interval === 'year') {
    const full = out.monthly.amount * 12;
    out.yearly.savingPercent = full > 0 ? Math.round((1 - out.yearly.amount / full) * 100) : 0;
    out.yearly.monthsFree = full > 0 ? Math.round((full - out.yearly.amount) / out.monthly.amount) : 0;
  }
  priceCache = { at: Date.now(), data: out };
  return out;
}

module.exports = { stripe, createCheckoutSession, createCreditsCheckout, createPortalSession, getPlanPrices, TRIAL_DAYS };
