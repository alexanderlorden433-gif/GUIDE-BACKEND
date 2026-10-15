// The AI that builds a member's one-page website, as a chat (My website): the member describes their business in
// their own words, the AI writes the whole page, and they keep chatting to change it ("make it blue", "add hedge
// trimming for $30"). Each turn sends the chat so far, the page as it is now and the new message; the answer is a
// short reply for the chat plus the whole page (structured outputs, so it always matches the schema below), and the
// page is cleaned by cleanSiteData() like anything else a member saves, so nothing reaches it unchecked.
//
// It uses the most capable Claude model this server can reach: Claude Fable 5.1 first, then Claude Opus 5.5,
// then Claude Sonnet 5.5 if the account can't use the one before (set SITE_AI_MODEL to pick a different first
// choice).
//
// Each message uses one AI credit (src/siteCredits.js): members start with a couple of free ones and buy packs
// after that. Pro members (and the old Lifetime plan) write without credits during their daily AI hour. On top of
// credits there's a per-member daily cap (so a stuck button or a script can't burn a whole pack) and an app-wide
// daily ceiling as an emergency brake (SITE_AI_DAILY_TOTAL). The daily counts live in the SiteAiUse table.
const prisma = require('./db');
const { state, cleanSiteData, COLORS } = require('./sites');
const credits = require('./siteCredits');

const DAILY_CAP = 30;
const TOTAL = () => Math.max(0, parseInt(process.env.SITE_AI_DAILY_TOTAL, 10) || 1000);
const MODELS = () => [...new Set([process.env.SITE_AI_MODEL, 'claude-fable-5-1', 'claude-opus-5-5', 'claude-sonnet-5-5'].filter(Boolean))];
const TIMEOUT_MS = 150 * 1000;
const HISTORY = 10;          // earlier chat messages sent along with the new one
// the model that wrote the last page, so My website can say which one it uses
let lastModel = null;
const currentModel = () => lastModel || MODELS()[0];

const str = { type: 'string' };
const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['reply', 'changed', 'name', 'tagline', 'area', 'hours', 'about', 'services', 'highlights', 'faq', 'color', 'lang', 'phone', 'email'],
  properties: {
    reply: { type: 'string', description: 'Your chat message to the owner: 1 to 3 short sentences, plain text, no emoji, no markdown.' },
    changed: { type: 'boolean', description: 'true if you wrote or changed the page this turn; false if you only answered or asked something.' },
    name: { type: 'string', description: 'Business name, at most 60 characters. Keep the owner\'s name if they gave one.' },
    tagline: { type: 'string', description: 'One line under the name: what they do and for whom, at most 120 characters.' },
    area: { type: 'string', description: 'Where they work, at most 80 characters, or empty if unknown.' },
    hours: { type: 'string', description: 'When they work, at most 80 characters, or empty if unknown.' },
    about: { type: 'string', description: 'About the owner, first person, 2 to 4 short sentences, at most 600 characters.' },
    services: {
      type: 'array', description: '1 to 8 services, the main one first (3 to 6 for a new page).',
      items: { type: 'object', additionalProperties: false, required: ['name', 'price', 'note'],
        properties: { name: { type: 'string', description: 'At most 60 characters.' },
          price: { type: 'string', description: 'Like "$40 a visit" or "from $120", at most 30 characters.' },
          note: { type: 'string', description: 'What is included, at most 140 characters, or empty.' } } },
    },
    highlights: { type: 'array', description: 'Up to 3 short, concrete reasons to pick them (3 for a new page), each at most 90 characters.', items: str },
    faq: {
      type: 'array', description: 'Up to 6 questions customers really ask (what is included, how to book, how to pay, the area), with short answers (3 to 5 for a new page).',
      items: { type: 'object', additionalProperties: false, required: ['q', 'a'],
        properties: { q: { type: 'string', description: 'At most 110 characters.' }, a: { type: 'string', description: 'At most 350 characters.' } } },
    },
    color: { type: 'string', enum: Object.keys(COLORS), description: 'The page accent colour: keep the current one unless the owner asks for another (pick one that suits a new page).' },
    lang: { type: 'string', enum: ['en', 'es'], description: 'The language of the page: keep the current one unless the owner asks for the page in the other language.' },
    phone: { type: 'string', description: 'A phone number only if the owner typed a new one in their latest message, otherwise empty.' },
    email: { type: 'string', description: 'An email address only if the owner typed a new one in their latest message, otherwise empty.' },
  },
};

function systemPrompt(chatLang) {
  return [
    'You are the website builder inside The Guide, an app that teaches beginners to start a side business (mostly in the US). You chat with the owner and build their one-page website.',
    'Each turn you get their page as it is now (if they have one) and their latest message. You answer with a short chat reply and the whole page.',
    '- No page yet: if they told you what their business is, write the whole page from it and make sensible, honest suggestions for anything they left out. If they have not said what their business is, set changed to false and ask what they do, where, for whom and what they charge.',
    '- A page already exists: do what they ask and change only that. Keep everything else exactly as it is: same wording, prices, colour and language. For broad requests ("make it better", "more professional") improve the wording but keep their facts and prices.',
    '- A question (about prices, wording, what to add): answer it in your reply. Change the page only if they asked you to.',
    '- Anything that is not about their business or their page: say in one sentence that you can only help with their website, and set changed to false.',
    'When changed is false, return the page exactly as you got it (or empty fields if there is no page).',
    'The page has: the business name, a one-line tagline, where and when they work, services with prices, reasons to pick them, a short "about" in the owner\'s voice, and a few FAQs. Visitors ask for a quote through a form, so the page should make that the obvious next step.',
    'Page writing: plain and warm, in short sentences a customer reads in seconds, specific to this business. No hype words ("premier", "world-class", "unparalleled"), no emoji, no exclamation marks.',
    'Honesty rules, always: never invent reviews, testimonials, ratings, awards, customer counts, years in business, licenses, certifications, insurance, guarantees, or anything else the owner did not tell you. Use the owner\'s facts as given. Reasons to pick them must follow from what they actually do (for example "Same day every week" for a weekly route), not from claims about quality.',
    'Prices: use the owner\'s prices when given. Otherwise suggest realistic beginner prices for that kind of work in the US, in US dollars, written like "$40 a visit", "from $120" or "$25 an hour".',
    'If the owner gave no business name, suggest a simple one that says what they do.',
    'Contact details: the page shows the owner\'s phone and email from their own fields. Fill the phone or email field only if they typed a new one in their latest message; otherwise leave it empty. Never put contact details in any other text.',
    'Page language: text on the page is in English (American) or, when the page language is es, in neutral Latin American Spanish that addresses customers as "usted", with prices in US dollars.',
    `Your reply: ${chatLang === 'es' ? 'in Spanish (the owner uses the app in Spanish), unless they write to you in English' : 'in the language the owner writes to you in'}. 1 to 3 short sentences, friendly and plain, no emoji, no markdown. Say what you made or changed. When you set or suggest prices, tell them to check local competitors before they publish. End with one short idea for what they could ask next.`,
  ].join('\n');
}

/** What the model sees this turn: the business, the page as it is now, and the new message. */
function turnPrompt({ message, draft, chapter }) {
  const parts = [];
  if (chapter && chapter.name) {
    parts.push(`Kind of business (from the chapter they study in The Guide): ${chapter.name}${chapter.description ? ` (${chapter.description})` : ''}.`);
    if (chapter.tips && chapter.tips.length) parts.push('What The Guide teaches about pricing and offers for this business:\n- ' + chapter.tips.join('\n- '));
  }
  parts.push(draft ? `Their page right now (JSON; "(set)" means they filled that in themselves):\n${JSON.stringify(draft)}` : 'They do not have a page yet.');
  parts.push(`Their latest message:\n"""${message}"""`);
  return parts.join('\n\n');
}

/** The chat so far, as the API wants it: alternating turns that start with the owner. Short strings only. */
function cleanHistory(h) {
  const out = [];
  for (const m of (Array.isArray(h) ? h : []).slice(-HISTORY)) {
    if (!m || (m.role !== 'user' && m.role !== 'assistant')) continue;
    const content = String(m.content == null ? '' : m.content).replace(/\r\n?/g, '\n').trim().slice(0, 1500);
    if (!content) continue;
    if (out.length && out[out.length - 1].role === m.role) out[out.length - 1].content += '\n\n' + content;
    else out.push({ role: m.role, content });
  }
  while (out.length && out[0].role !== 'user') out.shift();
  // the new message is a user turn, so the history must end with the assistant
  while (out.length && out[out.length - 1].role !== 'assistant') out.pop();
  return out;
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
 * One chat turn: {message, history, draft, chapter, lang (the page's), appLang (the app's, for the reply), tz}.
 * (The older {mode, description} form still works.) Returns {status, body} for the route to send; body is
 * {reply, changed, draft, model, paidWith, credits, hour}. `fetchImpl` lets the checks stand in for the real API.
 */
async function writePage({ userId, message, history, draft, chapter, lang, appLang, tz, mode, description }, fetchImpl = fetch) {
  if (!state.ready) return { status: 503, body: { error: 'Websites are not ready yet. Try again in a minute.' } };
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return { status: 503, body: { error: 'The page writer is not set up yet.' } };
  const current = draft && typeof draft === 'object' ? cleanSiteData(draft) : null;
  const hasPage = !!(current && (current.name || current.services.length || current.about));
  if (message == null && (description != null || mode)) {
    message = mode === 'improve' ? 'Make my page better: clearer, more specific and more convincing, keeping my facts and prices.' : description;
  }
  message = String(message == null ? '' : message).replace(/\r\n?/g, '\n').trim().slice(0, 1500);
  if (message.length < 2) return { status: 400, body: { error: 'Type a message first.' } };
  if (!hasPage && message.length < 10 && mode !== 'improve' && !cleanHistory(history).length) {
    return { status: 400, body: { error: 'Tell it a little about your business first: what you do, where, and for whom.' } };
  }
  const pageLang = lang === 'es' || lang === 'en' ? lang : (current ? current.lang : 'en');
  if ((await usedByEveryone()) >= TOTAL()) {
    return { status: 503, body: { error: 'The page writer is very busy today. Please try again tomorrow.' } };
  }
  if (!(await takeUse(userId, DAILY_CAP))) {
    return { status: 429, body: { error: "That's a lot of writes for one day. Please try again tomorrow." } };
  }
  // Pro's daily hour first (free while it runs), then credits
  const spent = (await credits.useDailyHour(userId, tz)) ? { bucket: 'hour' } : await credits.spendCredit(userId);
  if (!spent.bucket) {
    await giveBack(userId).catch(() => {});
    const [left, hour] = await Promise.all([credits.getCredits(userId), credits.hourState(userId, tz)]);
    return { status: 402, body: { buy: true, credits: left, hour, packs: credits.packsForApp(),
      error: hour.included
        ? "You've used today's AI hour. It comes back tomorrow, or pick a pack to keep writing now."
        : spent.reason === 'free_busy'
          ? 'Free tries are all taken for today. Buy a pack to write now, or try again tomorrow.'
          : "You're out of AI credits. Pick a pack to keep writing." } };
  }
  // the model never sees the contact details the owner typed into their page
  const forModel = hasPage ? Object.assign({}, current, { email: current.email ? '(set)' : '', phone: current.phone ? '(set)' : '', lang: pageLang }) : null;
  const body = {
    max_tokens: 16000,
    system: systemPrompt(appLang === 'es' ? 'es' : 'en'),
    messages: cleanHistory(history).concat([{ role: 'user', content: turnPrompt({ message, draft: forModel, chapter: cleanChapter(chapter) }) }]),
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
    if (spent.bucket === 'hour') await credits.giveBackHourWrite(userId, tz).catch(err => console.error('[site-ai] could not give the hour write back:', err.message));
    else await credits.refundCredit(userId, spent.bucket).catch(err => console.error('[site-ai] could not give the credit back:', err.message));
    const msg = result && result.error === 'timeout' ? 'That took too long. Please try again.' : 'The page writer could not finish just now. Please try again.';
    return { status: 502, body: { error: msg, credits: await credits.getCredits(userId).catch(() => undefined), hour: await credits.hourState(userId, tz).catch(() => undefined) } };
  }
  lastModel = result.model;
  const u = result.usage || {};
  console.log(`[site-ai] wrote a page with ${result.model}: ${u.input_tokens || 0} tokens in, ${u.output_tokens || 0} out`);
  await credits.logUse(userId, spent.bucket, result.model, result.usage).catch(err => console.error('[site-ai] could not log the write:', err.message));
  const ai = result.data || {};
  const reply = String(ai.reply || '').replace(/\s+\n/g, '\n').trim().slice(0, 1200) || (ai.changed ? 'Done. Have a look at your page.' : '');
  let page = current || cleanSiteData({ lang: pageLang });
  let changed = false;
  if (ai.changed) {
    const typed = cleanSiteData({ email: ai.email, phone: ai.phone });
    // the owner's own contact details stay, unless they just typed new ones in the chat; the business type stays
    const next = cleanSiteData(Object.assign({}, ai, {
      email: typed.email || (current ? current.email : ''), phone: typed.phone || (current ? current.phone : ''),
      nicheId: current ? current.nicheId : '', lang: ai.lang === 'es' || ai.lang === 'en' ? ai.lang : pageLang,
    }));
    if (next.name || next.services.length || next.about) { page = next; changed = true; }
  }
  const [left, hour] = await Promise.all([credits.getCredits(userId), credits.hourState(userId, tz)]);
  return { status: 200, body: { reply, changed, draft: page, tips: [], model: result.model, paidWith: spent.bucket, credits: left, hour } };
}

module.exports = { writePage, currentModel, SCHEMA, DAILY_CAP, MODELS };
