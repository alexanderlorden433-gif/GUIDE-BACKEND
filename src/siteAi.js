// The AI that designs a member's website, as a chat (My website, the Lovable-style builder): the member describes
// their business and the look they want in their own words, and the AI writes the whole page, its own HTML and CSS,
// so every page can look the way its owner described it. They keep chatting to change it ("make it darker", "add a
// gallery section", "bigger headline"); small changes come back as exact find-and-replace edits (fast and cheap),
// big ones as the whole page again. Each turn sends the chat so far, the page as it is now and the new message;
// the answer is a short reply for the chat plus the page (structured outputs, so it always matches SCHEMA).
// Whatever the AI writes is cleaned by src/siteDesign.js (no scripts, nothing that runs) before it's saved or shown.
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
const { state, cleanSiteData } = require('./sites');
const credits = require('./siteCredits');

const DAILY_CAP = 30;
const TOTAL = () => Math.max(0, parseInt(process.env.SITE_AI_DAILY_TOTAL, 10) || 1000);
const MODELS = () => [...new Set([process.env.SITE_AI_MODEL, 'claude-fable-5-1', 'claude-opus-5-5', 'claude-sonnet-5-5'].filter(Boolean))];
const TIMEOUT_MS = 270 * 1000;   // a whole new design can take a couple of minutes
const MAX_TOKENS = 32000;        // thinking plus the page itself
const HISTORY = 10;              // earlier chat messages sent along with the new one
// the model that wrote the last page, so My website can say which one it uses
let lastModel = null;
const currentModel = () => lastModel || MODELS()[0];

const str = { type: 'string' };
const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['reply', 'changed', 'name', 'tagline', 'area', 'hours', 'services', 'lang', 'phone', 'email', 'fonts', 'html', 'css', 'edits'],
  properties: {
    reply: { type: 'string', description: 'Your chat message to the owner: 1 to 3 short sentences, plain text, no emoji, no markdown.' },
    changed: { type: 'boolean', description: 'true if you wrote or changed the page this turn; false if you only answered or asked something.' },
    name: { type: 'string', description: 'The business name as the page shows it, at most 60 characters.' },
    tagline: { type: 'string', description: 'One line on what they do and for whom, used in search results, at most 140 characters.' },
    area: { type: 'string', description: 'Where they work, at most 80 characters, or empty if unknown.' },
    hours: { type: 'string', description: 'When they work, at most 80 characters, or empty if unknown.' },
    services: {
      type: 'array', description: 'The services on the page with their prices (they fill the request form\'s list).',
      items: { type: 'object', additionalProperties: false, required: ['name', 'price'],
        properties: { name: { type: 'string', description: 'At most 60 characters.' }, price: { type: 'string', description: 'Like "$40 a visit", at most 30 characters, or empty.' } } },
    },
    lang: { type: 'string', enum: ['en', 'es'], description: 'The language of the page.' },
    phone: { type: 'string', description: 'A phone number only if the owner typed a new one in their latest message, otherwise empty.' },
    email: { type: 'string', description: 'An email address only if the owner typed a new one in their latest message, otherwise empty.' },
    fonts: { type: 'array', description: 'The Google Fonts families the page uses (at most 2), e.g. ["Fraunces", "Inter"]. Always list them, also when you only edit.', items: str },
    html: { type: 'string', description: 'The whole page markup (body content only) when you write the page in full; otherwise empty.' },
    css: { type: 'string', description: 'The whole page CSS when you write the page in full; otherwise empty.' },
    edits: {
      type: 'array', description: 'For a change to the existing page: exact find-and-replace edits. Empty when you write in full or change nothing.',
      items: { type: 'object', additionalProperties: false, required: ['target', 'find', 'replace'],
        properties: {
          target: { type: 'string', enum: ['html', 'css'] },
          find: { type: 'string', description: 'A piece of the current html or css copied exactly, long enough to appear only once.' },
          replace: { type: 'string', description: 'What it becomes.' } } },
    },
  },
};

function systemPrompt(chatLang) {
  return [
    'You are the website designer inside The Guide, an app that teaches beginners to start a side business (mostly in the US). Like a skilled web designer, you build the owner a one-page website by writing its HTML and CSS, and you chat with them to shape it.',
    'Each turn you get their page as it is now (if they have one: its details, HTML and CSS) and their latest message. You answer with a short chat reply and the page.',
    '',
    'How to answer:',
    '- No page yet, or they ask for a different design, style or layout: write the whole page in html and css, and leave edits empty. If they have not said what their business is yet, set changed to false and ask what they do, where, for whom, what they charge and what look they like.',
    '- A change to the page they have: leave html and css empty and give edits. Each edit replaces one exact piece of the current html or css (copied character for character, long enough to appear only once) with the new text. Use as few edits as you can. Change only what they asked; keep everything else exactly as it is. If the change touches most of the page, write it in full instead.',
    '- A question (about prices, wording, what to add): answer in your reply; change the page only if they asked you to.',
    '- Anything that is not about their business or their website: say in one sentence that you can only help with their website, and set changed to false.',
    'When changed is false, leave html, css and edits empty.',
    '',
    'What the page can use (anything else is removed before it is shown):',
    '- HTML: section, header, footer, nav, main, article, div, span, h1-h6, p, a, ul, ol, li, img, figure, figcaption, blockquote, strong, em, small, br, hr, table, details and summary, and inline SVG for icons and shapes (svg, g, path, circle, ellipse, rect, line, polyline, polygon, defs, linearGradient, radialGradient, stop).',
    '- Attributes: class, id, aria-*, role, href (https, mailto, tel, or #section links), img src (https only), alt, and SVG drawing attributes. No style attributes, no event handlers, no scripts, no forms, no inputs, no buttons (style links as buttons), no iframes.',
    '- CSS: any normal CSS: custom properties, flexbox, grid, media queries, gradients, shadows, transitions and keyframe animations. No @import. Background images only from https links. Put everything in css; html has no <style> tag.',
    '- Fonts: up to two Google Fonts families, listed in fonts and used in the CSS by name with a fallback (e.g. font-family: "Fraunces", Georgia, serif).',
    '- Images: there are no photos unless the owner gives you an image link (https). Make the design strong without photos: typography, colour, shapes, gradients, inline SVG icons and illustrations. Never invent image links.',
    '',
    'Every page must have:',
    '- A section with id="ask" where visitors ask for a quote, with <div data-guide="form"></div> where the form goes (leave it empty; the form is put in later). The form has these classes you can style to match: .tg-form, .tg-form label, .tg-form input, .tg-form select, .tg-form textarea, .tg-btn, .tg-small, .tg-note. Main buttons on the page link to #ask.',
    '- For calling or emailing, only <a data-guide="phone">Call us</a> and <a data-guide="email">Email us</a> (styled as you like). They get the owner\'s real number or email, or are left out if the owner has not added one. Never write a phone number or email address anywhere else.',
    '- A design that looks great on a phone first (most visitors), and good on a laptop.',
    '- At most about 18,000 characters of html and 10,000 of css: clean, compact markup, no comments.',
    '',
    'Design: a professional, modern small-business site that fits this business and the look the owner asked for (style, colours, mood). A clear hero with what they do, where, and a main button; services with prices; why choose them; how it works or about; questions (details and summary); the quote section; a simple footer. Clear hierarchy, generous spacing, readable contrast everywhere, consistent buttons, a polished feel.',
    'Words: plain and warm, short sentences a customer reads in seconds, specific to this business. No hype words ("premier", "world-class", "unparalleled"), no emoji, no exclamation marks.',
    'Honesty rules, always: never invent reviews, testimonials, ratings, awards, customer counts, years in business, licenses, certifications, insurance, guarantees, or anything else the owner did not tell you. Use their facts as given. Reasons to pick them must follow from what they actually do.',
    'Prices: use the owner\'s prices when given. Otherwise suggest realistic beginner prices for that kind of work in the US, in US dollars, like "$40 a visit", "from $120" or "$25 an hour".',
    'If they gave no business name, suggest a simple one that says what they do. Keep name, tagline, area, hours and services in step with the page.',
    'Page language: English (American), or when lang is es, neutral Latin American Spanish that addresses customers as "usted", with prices in US dollars. Keep the current language unless they ask to switch.',
    'Contact details: fill phone or email only if the owner typed a new one in their latest message; otherwise leave them empty.',
    `Your reply: ${chatLang === 'es' ? 'in Spanish (the owner uses the app in Spanish), unless they write to you in English' : 'in the language the owner writes to you in'}. 1 to 3 short sentences, friendly and plain, no emoji, no markdown. Say what you made or changed. When you set or suggest prices, tell them to check local competitors before they publish. End with one short idea for what they could ask next.`,
  ].join('\n');
}

/** What the model sees this turn: the business, the page as it is now, and the new message. */
function turnPrompt({ message, page, chapter, full }) {
  const parts = [];
  if (chapter && chapter.name) {
    parts.push(`Kind of business (from the chapter they study in The Guide): ${chapter.name}${chapter.description ? ` (${chapter.description})` : ''}.`);
    if (chapter.tips && chapter.tips.length) parts.push('What The Guide teaches about pricing and offers for this business:\n- ' + chapter.tips.join('\n- '));
  }
  if (!page) parts.push('They do not have a page yet.');
  else {
    const { design, ...details } = page;
    parts.push(`Their page details (JSON; "(set)" means they filled that in themselves):\n${JSON.stringify(details)}`);
    if (design) {
      parts.push(`The page HTML right now:\n<page_html>\n${design.html}\n</page_html>`);
      parts.push(`The page CSS right now:\n<page_css>\n${design.css}\n</page_css>`);
      parts.push(`Fonts: ${JSON.stringify(design.fonts)}`);
    } else {
      parts.push('The page still uses the standard layout built from those details. Turn it into a designed page: write it in full, keeping their words, prices and facts.');
    }
  }
  parts.push(`Their latest message:\n"""${message}"""`);
  if (full) parts.push('Important: your edits last time did not match the page exactly. This time write the whole page in full (html and css) with the change applied, and leave edits empty.');
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

/** Applies the AI's find-and-replace edits to the page. null when one of them doesn't match exactly once. */
function applyEdits(design, edits) {
  let html = design.html, css = design.css;
  for (const e of edits) {
    const find = String((e && e.find) || '');
    const rep = String(e && e.replace != null ? e.replace : '');
    if (!find) return null;
    const src = e.target === 'css' ? css : html;
    const at = src.indexOf(find);
    if (at < 0 || src.indexOf(find, at + 1) >= 0) return null;
    const next = src.slice(0, at) + rep + src.slice(at + find.length);
    if (e.target === 'css') css = next; else html = next;
  }
  return { html, css };
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
  const hasPage = !!(current && (current.design || current.name || current.services.length || current.about));
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
  const failed = async (result) => {
    console.error('[site-ai] could not write the page:', result && result.status, result && result.error);
    await giveBack(userId).catch(err => console.error('[site-ai] could not give the write back:', err.message));
    if (spent.bucket === 'hour') await credits.giveBackHourWrite(userId, tz).catch(err => console.error('[site-ai] could not give the hour write back:', err.message));
    else await credits.refundCredit(userId, spent.bucket).catch(err => console.error('[site-ai] could not give the credit back:', err.message));
    const msg = result && result.error === 'timeout' ? 'That took too long. Please try again.' : 'The page writer could not finish just now. Please try again.';
    return { status: 502, body: { error: msg, credits: await credits.getCredits(userId).catch(() => undefined), hour: await credits.hourState(userId, tz).catch(() => undefined) } };
  };

  // the model never sees the contact details the owner typed into their page
  const forModel = hasPage ? Object.assign({}, current, { email: current.email ? '(set)' : '', phone: current.phone ? '(set)' : '', lang: pageLang }) : null;
  const usage = { input_tokens: 0, output_tokens: 0 };
  const ask = async (full) => {
    const body = {
      max_tokens: MAX_TOKENS,
      system: systemPrompt(appLang === 'es' ? 'es' : 'en'),
      messages: cleanHistory(history).concat([{ role: 'user', content: turnPrompt({ message, page: forModel, chapter: cleanChapter(chapter), full }) }]),
      output_config: { format: { type: 'json_schema', schema: SCHEMA } },
    };
    let result = null;
    for (const model of MODELS()) {
      result = await callModel(model, body, apiKey, fetchImpl);
      if (result.ok || !result.retryNextModel) break;
      console.warn(`[site-ai] ${model} not available (${result.status}); trying the next model`);
    }
    if (result && result.ok && result.usage) {
      usage.input_tokens += (result.usage.input_tokens || 0) + (result.usage.cache_read_input_tokens || 0) + (result.usage.cache_creation_input_tokens || 0);
      usage.output_tokens += result.usage.output_tokens || 0;
    }
    return result;
  };

  let result = await ask(false);
  if (!result || !result.ok) return failed(result);
  let ai = result.data || {};
  let design = null;
  if (ai.changed) {
    if (String(ai.html || '').trim()) design = { html: ai.html, css: ai.css, fonts: ai.fonts };
    else if (Array.isArray(ai.edits) && ai.edits.length && current && current.design) {
      const applied = applyEdits(current.design, ai.edits);
      if (applied) design = Object.assign(applied, { fonts: Array.isArray(ai.fonts) && ai.fonts.length ? ai.fonts : current.design.fonts });
    } else if (current && current.design) design = current.design;   // only the details changed
    if (!design) {
      // its edits didn't match the page (or there was nothing to edit yet): once more, written in full
      console.warn('[site-ai] edits did not apply; asking for the whole page');
      const again = await ask(true);
      if (!again || !again.ok) return failed(again);
      if (!again.data || !again.data.changed || !String(again.data.html || '').trim()) return failed({ status: 200, error: 'no page' });
      result = again; ai = again.data;
      design = { html: ai.html, css: ai.css, fonts: ai.fonts };
    }
  }
  lastModel = result.model;
  console.log(`[site-ai] wrote a page with ${result.model}: ${usage.input_tokens} tokens in, ${usage.output_tokens} out`);
  await credits.logUse(userId, spent.bucket, result.model, usage).catch(err => console.error('[site-ai] could not log the write:', err.message));
  const reply = String(ai.reply || '').replace(/\s+\n/g, '\n').trim().slice(0, 1200) || (ai.changed ? 'Done. Have a look at your page.' : '');
  let page = current || cleanSiteData({ lang: pageLang });
  let changed = false;
  if (ai.changed && design) {
    const typed = cleanSiteData({ email: ai.email, phone: ai.phone });
    // the owner's own contact details stay, unless they just typed new ones in the chat; the business type stays
    const next = cleanSiteData(Object.assign({}, current || {}, {
      name: ai.name, tagline: ai.tagline, area: ai.area, hours: ai.hours,
      services: (Array.isArray(ai.services) ? ai.services : []).map(x => ({ name: x && x.name, price: x && x.price, note: '' })),
      email: typed.email || (current ? current.email : ''), phone: typed.phone || (current ? current.phone : ''),
      nicheId: current ? current.nicheId : '', lang: ai.lang === 'es' || ai.lang === 'en' ? ai.lang : pageLang,
      design,
    }));
    if (!next.design) return failed({ status: 200, error: 'the page was empty once cleaned' });
    page = next; changed = true;
  }
  const [left, hour] = await Promise.all([credits.getCredits(userId), credits.hourState(userId, tz)]);
  return { status: 200, body: { reply, changed, draft: page, tips: [], model: result.model, paidWith: spent.bucket, credits: left, hour } };
}

module.exports = { writePage, currentModel, applyEdits, SCHEMA, DAILY_CAP, MODELS };
