/**
 * What Pro costs, in one place.
 *
 * Stripe is the real source of truth — the app shows what GET /api/billing/prices
 * reads back from Stripe, so a customer is never quoted a number we don't charge.
 * These are the same figures, kept here for the places that can't wait on a network
 * call: analytics estimates, the owner dashboard, emails, and the value attached to
 * a checkout event before the payment exists.
 *
 * If you change the prices in Stripe, change them here too.
 */
const PRICES = { monthly: 24.99, yearly: 149 };

/** Rough monthly value of a subscription, used for MRR estimates. */
const monthlyValue = (plan) => (plan === 'yearly' ? PRICES.yearly / 12 : PRICES.monthly);

module.exports = { PRICES, monthlyValue };
