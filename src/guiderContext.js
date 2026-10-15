/**
 * What The Guider knows about the person asking.
 *
 * Built on the server from the user's own saved data, never from anything the
 * browser sends, so a request can't claim to be further along than it is or ask
 * about somebody else's business.
 *
 * It is a short summary on purpose: how far through the course they are, what
 * they set as a goal, and the shape of their own numbers. Client names and
 * individual line items stay out — they belong to the user's customers, they
 * aren't needed to answer well, and the person can always mention one themselves.
 */

const money = (n) => '$' + Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 0 });
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** How far through this chapter's course they are. */
function courseProgress(blob, niche) {
  if (!niche || !Array.isArray(niche.guides) || !niche.guides.length) return null;
  const done = new Set(Array.isArray(blob.completed) ? blob.completed : []);
  const finished = niche.guides.filter((g) => done.has(`${niche.id}|${g.title}`));
  if (!finished.length) return 'They have not finished a lesson in this chapter yet.';

  const last = finished[finished.length - 1];
  const next = niche.guides.find((g) => !done.has(`${niche.id}|${g.title}`));
  const mod = niche.modules && niche.modules[last.mod];
  const bits = [
    `${finished.length} of ${niche.guides.length} lessons finished in this chapter`,
    mod ? `currently in Module ${last.mod + 1}, "${mod.title}"` : null,
    `just finished "${last.title}"`,
    next ? `next up is "${next.title}"` : 'they have finished the whole chapter',
  ].filter(Boolean);
  return bits.join('; ') + '.';
}

/** The shape of their own business numbers — totals, never individual customers. */
function businessShape(blob) {
  const b = blob.business || {};
  const out = [];

  const goal = b.goal || {};
  if (goal.label && Number(goal.target) > 0) {
    out.push(`Their stated goal: ${goal.label} — ${money(goal.target)}${goal.deadline ? ` by ${goal.deadline}` : ''}.`);
  }

  const invoices = Array.isArray(b.invoices) ? b.invoices : [];
  if (invoices.length) {
    const total = invoices.reduce((s, i) => s + (Number(i.total) || 0), 0);
    const unpaid = invoices.filter((i) => String(i.status || '').toLowerCase() !== 'paid');
    const unpaidTotal = unpaid.reduce((s, i) => s + (Number(i.total) || 0), 0);
    const avg = total / invoices.length;
    out.push(
      `They have raised ${plural(invoices.length, 'invoice')} totalling ${money(total)} ` +
      `(average ${money(avg)})${unpaid.length ? `, of which ${plural(unpaid.length, 'invoice')} worth ${money(unpaidTotal)} ${unpaid.length === 1 ? 'is' : 'are'} still unpaid` : ', all paid'}.`
    );
  }

  const expenses = Array.isArray(b.expenses) ? b.expenses : [];
  if (expenses.length) {
    const total = expenses.reduce((s, e) => s + (Number(e.amount) || 0), 0);
    out.push(`They have logged ${plural(expenses.length, 'expense')} totalling ${money(total)}.`);
  }

  const recurring = Array.isArray(b.recurring) ? b.recurring : [];
  if (recurring.length) {
    const total = recurring.reduce((s, r) => s + (Number(r.amount) || 0), 0);
    out.push(`They have ${plural(recurring.length, 'recurring revenue source')} worth ${money(total)} a month.`);
  }

  const open = (Array.isArray(b.reminders) ? b.reminders : []).filter((r) => r && !r.done).length;
  if (open) out.push(`They have ${plural(open, 'reminder')} still open.`);

  return out;
}

/** Counts from the per-chapter trackers (client lists, listings, trades and so on). */
function trackerShape(blob, nicheId) {
  const tools = (blob.tools || {})[nicheId];
  if (!tools || typeof tools !== 'object') return [];
  const counts = Object.entries(tools)
    .filter(([, v]) => Array.isArray(v) && v.length)
    .map(([k, v]) => `${plural(v.length, k.replace(/([A-Z])/g, ' $1').trim().toLowerCase().replace(/s$/, ''))}`);
  return counts.length ? [`In this chapter's trackers they have: ${counts.join(', ')}.`] : [];
}

/** Goals a member can pick for their 30-day plan (the app keeps the same list). */
const PLAN_GOALS = {
  first_customer: 'their first paying customer',
  first_500: 'their first $500 from it',
  set_up: 'being set up and ready to sell',
  grow: 'more customers than they have now',
  trade_plan: 'a written trading plan they stick to',
  practice: 'a month of practice trades in their journal',
  basics: 'the basics down before they risk real money',
};

/**
 * Their 30-day plan in this chapter, if they have one: which day they are on and what they want by day 30.
 * Days are counted in UTC here, so near midnight this can be a day off from what the app shows.
 */
function planLine(blob, niche, now = Date.now()) {
  const p = blob.dayPlan;
  if (!p || typeof p !== 'object' || !niche || p.nicheId !== niche.id) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(p.start))) return null;
  const day = Math.floor((now - Date.parse(`${p.start}T00:00:00Z`)) / 86400000) + 1;
  if (!Number.isFinite(day) || day > 37) return null;
  const goal = PLAN_GOALS[p.goal];
  const goalBit = goal ? ` Their goal by day 30: ${goal}.` : '';
  const shape = 'one lesson step a day, a module a week, and a check-in with you every 7 days';
  if (day < 1) return `They have made a 30-day plan for this chapter (${shape}); it starts on ${p.start}.${goalBit}`;
  if (day > 30) return `They have just finished a 30-day plan in this chapter (${shape}).${goalBit}`;
  return `They are on day ${day} of 30 of a plan for this chapter (${shape}).${goalBit} ` +
    'When they check in, look at what they finished, help them with what got in the way, and keep the advice to the next 7 days.';
}

/**
 * A short paragraph for the system prompt, or '' when there is nothing useful
 * to say yet (a brand-new account should not get a wall of empty facts).
 */
function buildGuiderContext(blob, niche) {
  if (!blob || typeof blob !== 'object') return '';
  const lines = [];

  const progress = courseProgress(blob, niche);
  if (progress) lines.push(progress);
  const plan = planLine(blob, niche);
  if (plan) lines.push(plan);
  lines.push(...businessShape(blob));
  if (niche) lines.push(...trackerShape(blob, niche.id));

  const streak = blob.streak && Number(blob.streak.count);
  if (streak > 1) lines.push(`They are on a ${streak}-day streak.`);

  if (!lines.length) return '';
  return (
    `\n\nWhat you know about this person, from their own saved work in the app:\n- ` +
    lines.join('\n- ') +
    `\n\nUse these details when they make the answer more specific — quote their own numbers back to them ` +
    `rather than talking in generalities, and refer to where they are in the course. Do not list this ` +
    `information back at them unprompted, do not invent anything beyond it, and if something they ask about ` +
    `is not covered here, say you cannot see it rather than guessing.`
  );
}

module.exports = { buildGuiderContext };
