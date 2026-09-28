# The Guide — Backend

A real backend for The Guide: authentication, account data storage, and Stripe
billing — replacing the prototype's `window.storage` (which only works inside
Claude.ai artifacts and can't run on your own domain).

## What this replaces

| Prototype (artifact) | This backend |
|---|---|
| `window.storage.set('user:...', json, true)` | `PUT /api/account` |
| `window.storage.get('user:...', true)` | `GET /api/account` |
| Plaintext password stored in the record | `bcrypt`-hashed password in Postgres |
| Fake "Upgrade & continue" button | Real Stripe Checkout + webhook |
| "Forgot password" self-serve reset | Real emailed reset link via Resend (see step 5) |

## Stack

- **Express** — API server
- **Prisma + PostgreSQL** — database and ORM
- **bcryptjs** — password hashing
- **jsonwebtoken** — session tokens (sent as `Authorization: Bearer <token>`)
- **Stripe** — subscription + one-time (lifetime) billing

## 1. Local setup

```bash
cd guide-backend
npm install
cp .env.example .env
```

Fill in `.env`:
- `DATABASE_URL` — a Postgres connection string. For local dev, the easiest option
  is a free Postgres from [Neon](https://neon.tech) or [Supabase](https://supabase.com),
  or run one locally with `docker run -p 5432:5432 -e POSTGRES_PASSWORD=pass postgres`.
- `JWT_SECRET` — generate with `openssl rand -hex 32`.
- `STRIPE_SECRET_KEY` — from your Stripe dashboard (use a **test mode** key first).
- `STRIPE_PRICE_MONTHLY` / `STRIPE_PRICE_LIFETIME` — see step 3 below.
- `STRIPE_WEBHOOK_SECRET` — see step 4 below.
- `RESEND_API_KEY` / `EMAIL_FROM` / `ADMIN_ALERT_EMAIL` — see step 5 below. Optional to
  start — the app works fine without these, it just won't send email alerts yet.

Then create the database tables:

```bash
npx prisma migrate dev --name init
```

Run it:

```bash
npm run dev
```

The API is now live at `http://localhost:4000`. Check `http://localhost:4000/api/health`.

## 2. API reference

All authenticated routes expect `Authorization: Bearer <token>`, where the
token comes back from `/api/auth/signup` or `/api/auth/login`.

| Method | Route | Auth? | Purpose |
|---|---|---|---|
| POST | `/api/auth/signup` | No | Create account, returns `{ token, user }` |
| POST | `/api/auth/login` | No | Log in, returns `{ token, user }` |
| POST | `/api/auth/forgot-password` | No | Sends a reset token (see step 5) |
| POST | `/api/auth/reset-password` | No | Sets a new password with a valid token |
| GET | `/api/account` | Yes | Returns `{ email, isPro, planType, data }` |
| PUT | `/api/account` | Yes | Body: `{ data: {...} }` — saves the full app data blob |
| PUT | `/api/account/password` | Yes | Body: `{ currentPassword, newPassword }` |
| DELETE | `/api/account` | Yes | Permanently deletes the account |
| POST | `/api/billing/checkout` | Yes | Body: `{ plan: "monthly" \| "lifetime" }` → `{ url }` to redirect to |
| POST | `/api/billing/portal` | Yes | Returns `{ url }` to Stripe's subscription-management page |
| POST | `/api/billing/webhook` | No (Stripe calls this) | Keeps `isPro` in sync with actual payment status |
| POST | `/api/mentor-alert` | Yes | Body: `{ nicheId, nicheName, displayName, bio, lookingFor, contact }` — sends an email to `ADMIN_ALERT_EMAIL` when someone creates a mentor profile |

## 3. Setting up Stripe products

In the [Stripe Dashboard](https://dashboard.stripe.com/products):

1. Create a product **"The Guide Pro — Monthly"**, price $12.99/month, recurring.
   Copy its Price ID (`price_...`) into `STRIPE_PRICE_MONTHLY`.
2. Create a product **"The Guide Pro — Lifetime"**, price $84.99, one-time.
   Copy its Price ID into `STRIPE_PRICE_LIFETIME`.

## 4. Setting up the webhook

Stripe needs to reach your server directly (not through your frontend) to
tell it when a payment succeeds, fails, or a subscription is cancelled.

**Local testing:** use the [Stripe CLI](https://stripe.com/docs/stripe-cli):
```bash
stripe listen --forward-to localhost:4000/api/billing/webhook
```
It will print a webhook signing secret starting with `whsec_` — put that in
`.env` as `STRIPE_WEBHOOK_SECRET`.

**In production:** in the Stripe Dashboard → Developers → Webhooks, add an
endpoint pointing to `https://your-domain.com/api/billing/webhook`, and select
at least these events:
- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_failed`

Copy the signing secret it gives you into your production `.env`.

## 5. Sending real emails

There's a small email utility at `src/email.js` using [Resend](https://resend.com)
(generous free tier, no credit card needed to start, simple HTTP API — no SMTP
setup). Two things are already wired up to use it:

- **Password reset emails** — `POST /api/auth/forgot-password` now actually
  emails the reset link (it used to just log the token to the console).
  Rate-limited to 5 requests per 15 minutes per IP so it can't be used to
  spam an inbox or burn through your sending quota.
- **Mentor application alerts** — `POST /api/mentor-alert` sends you an email
  whenever someone creates a profile in the app's Mentor Directory. Set
  `ADMIN_ALERT_EMAIL` in `.env` to the inbox that should receive these.

To actually receive emails:
1. Sign up at [resend.com](https://resend.com) and grab an API key from
   **API Keys** in their dashboard → `RESEND_API_KEY`.
2. For quick testing, leave `EMAIL_FROM` as `onboarding@resend.dev` (Resend's
   shared testing address — works immediately, no setup). Before going live,
   verify your own domain in Resend and switch `EMAIL_FROM` to an address on
   it (e.g. `alerts@yourdomain.com`), since the shared testing address can
   land in spam and isn't meant for real production traffic.
3. Set `ADMIN_ALERT_EMAIL` to wherever you want mentor-application alerts
   sent — any inbox you actually check. Password reset emails don't need
   this — they always go to the user's own address.

If neither `RESEND_API_KEY` nor `EMAIL_FROM` is set, both features degrade
gracefully — password reset still generates a valid token (just doesn't
email it, same as before), and mentor alerts just skip sending rather than
failing the request. Nothing breaks if you haven't set up Resend yet.

## 6. Deploying

Any Node host works. Easiest options if you haven't deployed a backend before:

- **[Railway](https://railway.app)** — can host both your Postgres database
  and this API together; connects to GitHub for auto-deploys.
- **[Render](https://render.com)** — free Postgres tier, straightforward
  Node web service setup.

Either way: push this folder to a GitHub repo, connect it, set the same
environment variables from `.env` in the host's dashboard (using your
**production** Stripe keys and a real database URL), and set the start
command to `npm run prisma:migrate && npm start`.

## 7. Connecting your frontend

The frontend currently calls `window.storage.get/set` directly. To use this
backend instead, those calls need to become `fetch()` calls to these
endpoints, with the JWT stored (e.g., in memory or a cookie) after login and
sent as `Authorization: Bearer <token>` on every request. Happy to do that
conversion next — just ask.
