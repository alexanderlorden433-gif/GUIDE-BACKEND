// The AI that writes a member's one-page website (My website → "Write my page" / "Make it better").
//
// It uses the most capable Claude model this server can reach: Claude Fable 5.1 first, then Claude Opus 5.5,
// then Claude Sonnet 5.5 if the account can't use the one before (set SITE_AI_MODEL to pick a different first
// choice). The answer comes back as JSON that must match the schema below (structured outputs), and is then
// cleaned by cleanSiteData() like anything else a member saves, so nothing reaches the page unchecked.
//
// Each write uses one AI credit (src/siteCredits.js): members start with a couple of free ones and buy packs
// after that. On top of credits there's a per-member daily cap (so a stuck button or a script can't burn a whole
// pack) and an app-wide daily ceiling as an emergency brake (SITE_AI_DAILY_TOTAL). The daily counts live in the
// SiteAiUse table (created in src/sites.js).
const prisma = require('./db');
const { state, cleanSiteData, COLORS } = require('./sites');
const credits = require('./siteCredits');

const DAILY_CAP = 30;
const TOTAL = () => Math.max(0, parseInt(process.env.SITE_AI_DAILY_TOTAL, 10) || 1000);
const MODELS = () => [...new Set([process.env.SITE_AI_MODEL, 'claude-fable-5-1', 'claude-opus-5-5', 'claude-sonnet-5-5'].filter(Boolean))];
const TIMEOUT_MS = 150 * 1000;
// the model that wrote the last page, so My website can say which one it uses
let lastModel = null;
const currentModel = () => lastModel || MODELS()[0];

const str = { type: 'string' };
const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['name', 'tagline', 'area', 'hours', 'about', 'services', 'highlights', 'faq', 'color', 'tips'],
  properties: {
    name: { type: 'string', description: 'Business name, at most 60 characters. Keep the owner\'s name if they gave one.' },
    tagline: { type: 'string', description: 'One line under the name: what they do and for whom, at most 120 characters.' },
    area: { type: 'string', description: 'Where they work, at most 80 characters, or empty if unknown.' },
    hours: { type: 'string', description: 'When they work, at most 80 characters, or empty if unknown.' },
    about: { type: 'string', description: 'About the owner, first person, 2 to 4 short sentences, at most 600 characters.' },
    services: {
      type: 'array', description: '3 to 6 services, the main one first.',
      items: { type: 'object', additionalProperties: false, required: ['name', 'price', 'note'],
        properties: { name: { type: 'string', description: 'At most 60 characters.' },
          price: { type: 'string', description: 'Like "$40 a visit" or "from $120", at most 30 characters.' },
          note: { type: 'string', description: 'What is included, at most 140 characters, or empty.' } } },
    },
    highlights: { type: 'array', description: 'Exactly 3 short, concrete reasons to pick them, each at most 90 characters.', items: str },
    faq: {
      type: 'array', description: '3 to 5 questions customers really ask (what is included, how to book, how to pay, the area), with short answers.',
      items: { type: 'object', additionalProperties: false, required: ['q', 'a'],
        properties: { q: { type: 'string', description: 'At most 110 characters.' }, a: { type: 'string', description: 'At most 350 characters.' } } },
    },
    color: { type: 'string', enum: Object.keys(COLORS), description: 'An accent colour that suits the business.' },
    tips: { type: 'array', description: '2 or 3 short notes for the owner (not shown on the page): what to check or add before publishing, e.g. confirm prices against local competitors, add a phone number.', items: str },
  },
};

function systemPrompt(lang) {
  const spanish = lang === 'es';
  return [
    'You write one-page websites for small businesses started by beginners using The Guide, an app that teaches people to start a side business (mostly in the US).',
    'The page has: the business name, a one-line tagline, where and when they work, services with prices, three reasons to pick them, a short "about" in the owner\'s voice, and a few FAQs. Visitors ask for a quote through a form, so the page should make that the obvious next step.',
    'Write plainly and warmly, in short sentences a customer reads in seconds. Be specific to this business. No hype words ("premier", "world-class", "unparalleled"), no emoji, no exclamation marks.',
    'Honesty rules, always: never invent reviews, testimonials, ratings, awards, customer counts, years in business, licenses, certifications, insurance, guarantees, or anything else the owner did not tell you. If the owner gave facts, use them as given. Reasons to pick them must follow from what they actually do (for example "Same day every week" for a weekly route), not from claims about quality.',
    'Prices: use the owner\'s prices when given. Otherwise suggest realistic beginner prices for that kind of work in the US, in US dollars, written like "$40 a visit", "from $120" or "$25 an hour", and add a tip telling the owner to check them against local competitors.',
    'If the owner gave no business name, suggest a simple one that says what they do. Keep their contact details out of the text; the page shows them separately.',
    spanish
      ? 'Write everything (including the tips) in Spanish: neutral Latin American Spanish, addressing customers as "usted". Keep prices in US dollars.'
      : 'Write everything in American English.',
  ].join('\n');
}

function userPrompt({ mode, description, draft, chapter }) {
  const parts = [];
  if (chapter && chapter.name) {
    parts.push(`Kind of business: ${chapter.name}${chapter.description ? ` (${chapter.description})` : ''}.`);
    if (chapter.tips && chapter.tips.length) parts.push('What The Guide teaches about pricing and offers for this business:\n- ' + chapter.tips.join('\n- '));
  }
  if (description) parts.push(`What the owner says about their business:\n"""${description}"""`);
  if (draft) parts.push(`Their page as it is now (JSON):\n${JSON.stringify(draft)}`);
  parts.push(mode === 'improve'
    ? 'Make this page better: clearer, more specific and more convincing to a customer. Keep every fact, name, price and contact detail the owner wrote unless it is clearly a placeholder; fill gaps (missing services, reasons to pick them, FAQs) in the same spirit.'
    : 'Write the whole page from what the owner told you. Where they left something out, make a sensible, honest suggestion they can edit.');
  return parts.join('\n\n');
}

/** Tidy what the app sends about the chapter: short strings only. */
function cleanChapter(c) {
  if (!c || typeof c !== 'object') return null;
  const s = (v, n) => String(v == null ? '' : v).replace(/\s+/g, ' ').trim().slice(0, n);
  return {
    name: s(c.name, 80),
    description: s(c.description, 240),
    tips: (Array.isArray(c.tips) ? c.tips : []).slice(0, 8).map(t => s(t, 400)).filter(Boolean),
  };
}

/**
 * Takes one of today's writes for this member, if any are left. Done in one statement before calling the
 * model, so two taps at once can't both slip under the limit. Returns how many they have now used, or 0
 * when the limit is reached.
 */
async function takeUse(userId, limit) {
  const rows = await prisma.$queryRawUnsafe(
    `INSERT INTO "SiteAiUse" ("userId", "day", "n") VALUES ($1::text, $2::text, 1)
     ON CONFLICT ("userId", "day") DO UPDATE SET "n" = "SiteAiUse"."n" + 1 WHERE "SiteAiUse"."n" < $3::int
     RETURNING "n"`, userId, today(), limit);
  return rows[0] ? rows[0].n : 0;
}
/** Gives a write back when the model failed, so a failure doesn't cost the member one. */
async function giveBack(userId) {
  await prisma.$executeRawUnsafe(
    `UPDATE "SiteAiUse" SET "n" = GREATEST("n" - 1, 0) WHERE "userId" = $1::text AND "day" = $2::text`, userId, today());
}
async function usedByEveryone() {
  const rows = await prisma.$queryRawUnsafe(`SELECT COALESCE(SUM("n"), 0)::int AS n FROM "SiteAiUse" WHERE "day" = $1::text`, today());
  return rows[0] ? rows[0].n : 0;
}
function today() { return new Date().toISOString().slice(0, 10); }

/** One call to the Messages API. Returns {ok, data, model} or {ok:false, retryNextModel, status, error}. */
async function callModel(model, body, apiKey, fetchImpl) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetchImpl('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify(Object.assign({ model }, body)),
      signal: ctl.signal,
    });
    const text = await res.text();
    if (!res.ok) {
      // a model this account can't use (or that doesn't exist here): try the next one
      const retryNextModel = res.status === 404 || res.status === 403 || (res.status === 400 && /model/i.test(text));
      return { ok: false, retryNextModel, status: res.status, error: text.slice(0, 300) };
    }
    const json = JSON.parse(text);
    if (json.stop_reason === 'refusal') return { ok: false, retryNextModel: false, status: 200, error: 'refusal' };
    if (json.stop_reason === 'max_tokens') return { ok: false, retryNextModel: false, status: 200, error: 'max_tokens' };
    const block = (json.content || []).find(b => b.type === 'text');
    if (!block) return { ok: false, retryNextModel: false, status: 200, error: 'no text' };
    return { ok: true, data: JSON.parse(block.text), model, usage: json.usage || null };
  } catch (err) {
    return { ok: false, retryNextModel: false, status: 0, error: err.name === 'AbortError' ? 'timeout' : err.message };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Writes (mode "write") or improves (mode "improve") a page. Returns {status, body} for the route to send.
 * `fetchImpl` is there so the checks can stand in for the real API.
 */
async function writePage({ userId, mode, description, draft, chapter, lang }, fetchImpl = fetch) {
  if (!state.ready) return { status: 503, body: { error: 'Websites are not ready yet. Try again in a minute.' } };
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return { status: 503, body: { error: 'The page writer is not set up yet.' } };
  mode = mode === 'improve' ? 'improve' : 'write';
  description = String(description == null ? '' : description).replace(/\r\n?/g, '\n').trim().slice(0, 2000);
  const current = draft && typeof draft === 'object' ? cleanSiteData(draft) : null;
  const pageLang = lang === 'es' || lang === 'en' ? lang : (current ? current.lang : 'en');
  if (mode === 'write' && description.length < 10) {
    return { status: 400, body: { error: 'Tell it a little about your business first: what you do, where, and for whom.' } };
  }
  if (mode === 'improve' && !(current && (current.name || current.services.length || current.about))) {
    return { status: 400, body: { error: 'There is nothing to improve yet. Write a few lines about your business, then tap Write my page.' } };
  }
  if ((await usedByEveryone()) >= TOTAL()) {
    return { status: 503, body: { error: 'The page writer is very busy today. Please try again tomorrow.' } };
  }
  if (!(await takeUse(userId, DAILY_CAP))) {
    return { status: 429, body: { error: "That's a lot of writes for one day. Please try again tomorrow." } };
  }
  const spent = await credits.spendCredit(userId);
  if (!spent.bucket) {
    await giveBack(userId).catch(() => {});
    const left = await credits.getCredits(userId);
    return { status: 402, body: { buy: true, credits: left, packs: credits.packsForApp(),
      error: spent.reason === 'free_busy'
        ? 'Free tries are all taken for today. Buy a pack to write now, or try again tomorrow.'
        : "You're out of AI credits. Pick a pack to keep writing." } };
  }
  const forModel = current ? Object.assign({}, current, { email: current.email ? '(set)' : '', phone: current.phone ? '(set)' : '' }) : null;
  const body = {
    max_tokens: 16000,
    system: systemPrompt(pageLang),
    messages: [{ role: 'user', content: userPrompt({ mode, description, draft: forModel, chapter: cleanChapter(chapter) }) }],
    output_config: { format: { type: 'json_schema', schema: SCHEMA } },
  };
  let result = null;
  for (const model of MODELS()) {
    result = await callModel(model, body, apiKey, fetchImpl);
    if (result.ok || !result.retryNextModel) break;
    console.warn(`[site-ai] ${model} not available (${result.status}); trying the next model`);
  }
  if (!result || !result.ok) {
    console.error('[site-ai] could not write the page:', result && result.status, result && result.error);
    await giveBack(userId).catch(err => console.error('[site-ai] could not give the write back:', err.message));
    await credits.refundCredit(userId, spent.bucket).catch(err => console.error('[site-ai] could not give the credit back:', err.message));
    const msg = result && result.error === 'timeout' ? 'That took too long. Please try again.' : 'The page writer could not finish just now. Please try again.';
    return { status: 502, body: { error: msg, credits: await credits.getCredits(userId).catch(() => undefined) } };
  }
  lastModel = result.model;
  const u = result.usage || {};
  console.log(`[site-ai] wrote a page with ${result.model}: ${u.input_tokens || 0} tokens in, ${u.output_tokens || 0} out`);
  await credits.logUse(userId, spent.bucket, result.model, result.usage).catch(err => console.error('[site-ai] could not log the write:', err.message));
  const ai = result.data || {};
  // the owner's own contact details, address and look stay as they set them
  const merged = cleanSiteData(Object.assign({}, ai, {
    email: current ? current.email : '', phone: current ? current.phone : '',
    nicheId: current ? current.nicheId : '', lang: pageLang,
    color: current && mode === 'improve' ? current.color : ai.color,
  }));
  const tips = (Array.isArray(ai.tips) ? ai.tips : []).slice(0, 3).map(t => String(t).slice(0, 240));
  return { status: 200, body: { draft: merged, tips, model: result.model, credits: await credits.getCredits(userId) } };
}

module.exports = { writePage, currentModel, SCHEMA, DAILY_CAP, MODELS };
