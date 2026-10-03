/**
 * Onboarding email drip — a 5-email welcome sequence sent over 14 days after
 * signup. Encourages new users to complete their first guide, explore tools,
 * connect with the community, and go Pro.
 *
 * Runs in-process on a daily cron schedule (like digest.js and streakReminder.js).
 * Each user's dataBlob tracks which drip emails they've received so we never
 * double-send, and so users who signed up before this feature was deployed
 * don't get retroactive emails.
 *
 * Schedule:
 *   Day 0  — Welcome (sent immediately at signup, not by cron)
 *   Day 1  — "Complete your first guide"
 *   Day 3  — "Explore your business tools"
 *   Day 7  — "Connect with the community"
 *   Day 14 — "Ready to go Pro?"
 */

const cron = require('node-cron');
const prisma = require('./db');
const { sendEmail } = require('./email');

const appUrl = () => process.env.APP_URL || 'https://theguide.app';

// ---------- Email templates ----------

const DRIP_EMAILS = [
  {
    id: 'welcome',
    dayAfterSignup: 0,
    subject: 'Welcome to The Guide — let\'s build something amazing',
    build: (user) => {
      const name = (user.email || '').split('@')[0];
      return {
        text:
          `Hey ${name},\n\n` +
          `Welcome to The Guide! You just took the first step toward building a real business.\n\n` +
          `Here's how to get started:\n` +
          `1. Pick a niche that excites you\n` +
          `2. Work through the guides at your own pace\n` +
          `3. Use the built-in tools to take action immediately\n\n` +
          `Every guide is packed with real strategies — no fluff, no theory for theory's sake.\n\n` +
          `Jump in: ${appUrl()}\n\n` +
          `Let's go,\nThe Guide Team`,
        html:
          `<div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;color:#E8E4F0;">` +
          `<p>Hey ${name},</p>` +
          `<p>Welcome to <strong>The Guide</strong>! You just took the first step toward building a real business.</p>` +
          `<p>Here's how to get started:</p>` +
          `<ol>` +
          `<li>Pick a niche that excites you</li>` +
          `<li>Work through the guides at your own pace</li>` +
          `<li>Use the built-in tools to take action immediately</li>` +
          `</ol>` +
          `<p>Every guide is packed with real strategies — no fluff, no theory for theory's sake.</p>` +
          `<p><a href="${appUrl()}" style="display:inline-block;padding:12px 28px;background:linear-gradient(135deg,#A855F7,#EC4899);color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">Jump In →</a></p>` +
          `<p>Let's go,<br>The Guide Team</p>` +
          `</div>`,
      };
    },
  },
  {
    id: 'first_guide',
    dayAfterSignup: 1,
    subject: 'Your first guide is waiting — here\'s where to start',
    build: (user) => {
      const blob = user.dataBlob || {};
      const niches = blob.niches || [];
      const nicheLine = niches.length
        ? `You picked ${niches[0]} — great choice. Your first chapter is ready.`
        : `Pick a niche and your first chapter will be right there waiting.`;
      return {
        text:
          `Quick question: have you completed your first guide yet?\n\n` +
          `${nicheLine}\n\n` +
          `Each guide takes 10-15 minutes and gives you something you can actually use right away — ` +
          `a strategy, a template, a process.\n\n` +
          `The members who get the most out of The Guide start with just one chapter and build momentum from there.\n\n` +
          `Start your first guide: ${appUrl()}\n\n` +
          `You've got this,\nThe Guide Team`,
        html:
          `<div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;color:#E8E4F0;">` +
          `<p>Quick question: have you completed your first guide yet?</p>` +
          `<p>${nicheLine}</p>` +
          `<p>Each guide takes 10-15 minutes and gives you something you can actually use right away — a strategy, a template, a process.</p>` +
          `<p>The members who get the most out of The Guide start with just one chapter and build momentum from there.</p>` +
          `<p><a href="${appUrl()}" style="display:inline-block;padding:12px 28px;background:linear-gradient(135deg,#A855F7,#EC4899);color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">Start Your First Guide →</a></p>` +
          `<p>You've got this,<br>The Guide Team</p>` +
          `</div>`,
      };
    },
  },
  {
    id: 'explore_tools',
    dayAfterSignup: 3,
    subject: 'Have you tried the business tools yet?',
    build: (user) => {
      return {
        text:
          `Most people come to The Guide for the chapters — but the tools might be even more valuable.\n\n` +
          `Inside your dashboard you'll find:\n` +
          `- Invoice Generator — create professional invoices in seconds\n` +
          `- Client Status Pages — keep clients in the loop without back-and-forth\n` +
          `- Business Templates — contracts, proposals, SOPs ready to customize\n` +
          `- Income Tracker — see where your money is actually coming from\n\n` +
          `These aren't generic templates. They're built specifically for the kind of business you're building.\n\n` +
          `Check them out: ${appUrl()}\n\n` +
          `The Guide Team`,
        html:
          `<div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;color:#E8E4F0;">` +
          `<p>Most people come to The Guide for the chapters — but the tools might be even more valuable.</p>` +
          `<p>Inside your dashboard you'll find:</p>` +
          `<ul>` +
          `<li><strong>Invoice Generator</strong> — create professional invoices in seconds</li>` +
          `<li><strong>Client Status Pages</strong> — keep clients in the loop without back-and-forth</li>` +
          `<li><strong>Business Templates</strong> — contracts, proposals, SOPs ready to customize</li>` +
          `<li><strong>Income Tracker</strong> — see where your money is actually coming from</li>` +
          `</ul>` +
          `<p>These aren't generic templates. They're built specifically for the kind of business you're building.</p>` +
          `<p><a href="${appUrl()}" style="display:inline-block;padding:12px 28px;background:linear-gradient(135deg,#A855F7,#EC4899);color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">Explore Tools →</a></p>` +
          `<p>The Guide Team</p>` +
          `</div>`,
      };
    },
  },
  {
    id: 'community',
    dayAfterSignup: 7,
    subject: 'You\'re not building alone — meet the community',
    build: (user) => {
      return {
        text:
          `One week in — how's it going?\n\n` +
          `One thing a lot of members tell us: the community features made a bigger difference than they expected.\n\n` +
          `Here's what you can do:\n` +
          `- Post a win on the Wins Board and celebrate your progress\n` +
          `- Find people in your niche through Networking and connect directly\n` +
          `- Check the Leaderboard to see how you stack up\n` +
          `- Jump into chapter Discussions to ask questions and share tips\n\n` +
          `Building a business is hard enough — you don't have to do it alone.\n\n` +
          `See the community: ${appUrl()}\n\n` +
          `The Guide Team`,
        html:
          `<div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;color:#E8E4F0;">` +
          `<p>One week in — how's it going?</p>` +
          `<p>One thing a lot of members tell us: the community features made a bigger difference than they expected.</p>` +
          `<p>Here's what you can do:</p>` +
          `<ul>` +
          `<li><strong>Post a win</strong> on the Wins Board and celebrate your progress</li>` +
          `<li><strong>Find people in your niche</strong> through Networking and connect directly</li>` +
          `<li><strong>Check the Leaderboard</strong> to see how you stack up</li>` +
          `<li><strong>Jump into Discussions</strong> to ask questions and share tips</li>` +
          `</ul>` +
          `<p>Building a business is hard enough — you don't have to do it alone.</p>` +
          `<p><a href="${appUrl()}" style="display:inline-block;padding:12px 28px;background:linear-gradient(135deg,#A855F7,#EC4899);color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">See the Community →</a></p>` +
          `<p>The Guide Team</p>` +
          `</div>`,
      };
    },
  },
  {
    id: 'go_pro',
    dayAfterSignup: 14,
    subject: 'Unlock everything — The Guide Pro',
    build: (user) => {
      const blob = user.dataBlob || {};
      const completedCount = Array.isArray(blob.completed) ? blob.completed.length : 0;
      const progressLine = completedCount > 0
        ? `You've already completed ${completedCount} guide${completedCount === 1 ? '' : 's'} — imagine what you could do with full access.`
        : `You've been exploring The Guide — imagine what you could do with full access.`;
      return {
        text:
          `${progressLine}\n\n` +
          `With Pro you get:\n` +
          `- Every chapter in every niche — not just the free previews\n` +
          `- All business tools unlocked (Invoice Generator, Client Status Pages, and more)\n` +
          `- The AI business assistant (The Guider) with unlimited conversations\n` +
          `- Priority access to new features and content\n\n` +
          `Two options: $28.99/mo or $325.99/year (save 6%).\n\n` +
          `Upgrade now: ${appUrl()}\n\n` +
          `The Guide Team`,
        html:
          `<div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;color:#E8E4F0;">` +
          `<p>${progressLine}</p>` +
          `<p>With <strong>Pro</strong> you get:</p>` +
          `<ul>` +
          `<li>Every chapter in every niche — not just the free previews</li>` +
          `<li>All business tools unlocked (Invoice Generator, Client Status Pages, and more)</li>` +
          `<li>The AI business assistant (The Guider) with unlimited conversations</li>` +
          `<li>Priority access to new features and content</li>` +
          `</ul>` +
          `<p>Two options: <strong>$28.99/mo</strong> or <strong>$325.99/year</strong> (save 6%).</p>` +
          `<p><a href="${appUrl()}" style="display:inline-block;padding:12px 28px;background:linear-gradient(135deg,#A855F7,#EC4899);color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">Upgrade to Pro →</a></p>` +
          `<p>The Guide Team</p>` +
          `</div>`,
      };
    },
  },
];

// ---------- Send the instant welcome email (called from auth.js at signup) ----------

async function sendWelcomeEmail(user) {
  const template = DRIP_EMAILS.find(d => d.id === 'welcome');
  if (!template) return;

  const { text, html } = template.build(user);
  const result = await sendEmail({ to: user.email, subject: template.subject, text, html });

  // Mark as sent in dataBlob
  if (result.sent) {
    try {
      const current = await prisma.user.findUnique({
        where: { id: user.id },
        select: { dataBlob: true },
      });
      const blob = current?.dataBlob || {};
      const dripSent = blob.onboardingDripSent || [];
      if (!dripSent.includes('welcome')) {
        dripSent.push('welcome');
        await prisma.user.update({
          where: { id: user.id },
          data: { dataBlob: { ...blob, onboardingDripSent: dripSent } },
        });
      }
    } catch (err) {
      console.error('[onboarding] Failed to mark welcome email as sent:', err.message);
    }
  }

  return result;
}

// ---------- Daily cron: send scheduled drip emails ----------

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function processOnboardingDrip() {
  console.log('[onboarding] Starting onboarding drip run...');

  const users = await prisma.user.findMany({
    select: { id: true, email: true, dataBlob: true, createdAt: true },
  });

  let sent = 0, skipped = 0, failed = 0;

  for (const user of users) {
    const blob = user.dataBlob || {};

    // Skip users who opted out or are already Pro (no need for the go_pro email)
    if (blob.onboardingDripOptOut) { skipped++; continue; }

    const dripSent = blob.onboardingDripSent || [];
    const daysSinceSignup = Math.floor(
      (Date.now() - new Date(user.createdAt).getTime()) / (1000 * 60 * 60 * 24)
    );

    // Find the next drip email this user hasn't received yet
    for (const template of DRIP_EMAILS) {
      // Skip welcome — that's sent at signup, not by cron
      if (template.id === 'welcome') continue;

      // Already sent this one
      if (dripSent.includes(template.id)) continue;

      // Not time yet
      if (daysSinceSignup < template.dayAfterSignup) continue;

      // Skip the Pro email for users who are already Pro
      if (template.id === 'go_pro' && blob.isPro) {
        skipped++;
        continue;
      }

      // Send it
      try {
        const { text, html } = template.build(user);
        const result = await sendEmail({
          to: user.email,
          subject: template.subject,
          text,
          html,
        });

        if (result.sent) {
          // Mark as sent
          const freshUser = await prisma.user.findUnique({
            where: { id: user.id },
            select: { dataBlob: true },
          });
          const freshBlob = freshUser?.dataBlob || {};
          const freshDripSent = freshBlob.onboardingDripSent || [];
          freshDripSent.push(template.id);
          await prisma.user.update({
            where: { id: user.id },
            data: { dataBlob: { ...freshBlob, onboardingDripSent: freshDripSent } },
          });
          sent++;
        } else {
          failed++;
        }
      } catch (err) {
        console.error(`[onboarding] Failed to send ${template.id} to ${user.email}:`, err.message);
        failed++;
      }

      // Only send one drip email per user per day
      break;
    }

    // Pacing delay
    await sleep(150);
  }

  console.log(`[onboarding] Done. Sent: ${sent}, skipped: ${skipped}, failed: ${failed}`);
  return { sent, skipped, failed };
}

function scheduleOnboardingDrip() {
  // Every day at 10am UTC
  cron.schedule('0 10 * * *', () => {
    processOnboardingDrip().catch(err =>
      console.error('[onboarding] Unhandled error:', err)
    );
  });
  console.log('[onboarding] Onboarding drip scheduled for daily 10am UTC.');
}

module.exports = { scheduleOnboardingDrip, processOnboardingDrip, sendWelcomeEmail };
