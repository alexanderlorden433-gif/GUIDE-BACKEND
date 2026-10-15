// Member websites: a one-page site for a member's own business (account menu → My website).
//
// The member fills in a short form in the app (name, what they offer and for how much, where they work,
// how to reach them). The page is served at theguide.company/s/<address>: Netlify passes /s/* through to
// this server (see web/_redirects), which renders it as plain HTML, so Google and link previews in
// messages see the business name. Visitors can send a request through the form on the page; it lands in
// the member's app (with a bell notification), never in an email.
//
// Saving a draft is open to every member; putting the page live is part of Pro. If a member's Pro ends,
// the page rests (a short "not available" page) until they come back.
//
// The two tables are created at startup with CREATE TABLE IF NOT EXISTS, like the other small tables,
// and are declared in prisma/schema.prisma as MemberSite and SiteRequest. Deleting an account removes
// its page and its requests (ON DELETE CASCADE).
const prisma = require('./db');

const SITE_ORIGIN = 'https://theguide.company';

const DDL = [
  `CREATE TABLE IF NOT EXISTS "MemberSite" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "previewKey" TEXT NOT NULL,
    "data" JSONB NOT NULL DEFAULT '{}',
    "published" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "MemberSite_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "MemberSite_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "MemberSite_userId_key" ON "MemberSite"("userId")`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "MemberSite_slug_key" ON "MemberSite"("slug")`,
  `CREATE TABLE IF NOT EXISTS "SiteRequest" (
    "id" TEXT NOT NULL,
    "siteId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "contact" TEXT NOT NULL,
    "service" TEXT,
    "message" TEXT,
    "seen" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "SiteRequest_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "SiteRequest_siteId_fkey" FOREIGN KEY ("siteId") REFERENCES "MemberSite"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  `CREATE INDEX IF NOT EXISTS "SiteRequest_siteId_createdAt_idx" ON "SiteRequest"("siteId", "createdAt")`,
  // how many times a member asked the AI to write their page today (src/siteAi.js keeps a daily limit)
  `CREATE TABLE IF NOT EXISTS "SiteAiUse" (
    "userId" TEXT NOT NULL,
    "day" TEXT NOT NULL,
    "n" INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT "SiteAiUse_pkey" PRIMARY KEY ("userId", "day"),
    CONSTRAINT "SiteAiUse_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  // AI website credits (src/siteCredits.js): what each member has left, free and bought
  `CREATE TABLE IF NOT EXISTS "SiteAiCredit" (
    "userId" TEXT NOT NULL,
    "free" INTEGER NOT NULL DEFAULT 0,
    "paid" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "SiteAiCredit_pkey" PRIMARY KEY ("userId"),
    CONSTRAINT "SiteAiCredit_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  // every change to them: a pack bought (one row per Stripe checkout, so a payment is never counted twice),
  // a write (with the model and tokens it used, to see what writes really cost), a failed write given back
  `CREATE TABLE IF NOT EXISTS "SiteAiCreditLog" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "kind" TEXT NOT NULL,
    "free" INTEGER NOT NULL DEFAULT 0,
    "paid" INTEGER NOT NULL DEFAULT 0,
    "pack" TEXT,
    "amountCents" INTEGER,
    "stripeSession" TEXT,
    "model" TEXT,
    "inputTokens" INTEGER,
    "outputTokens" INTEGER,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "SiteAiCreditLog_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "SiteAiCreditLog_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "SiteAiCreditLog_stripeSession_key" ON "SiteAiCreditLog"("stripeSession")`,
  // Pro's daily AI hour (src/siteCredits.js): when a member's hour started, one row per member per (their) day
  `CREATE TABLE IF NOT EXISTS "SiteAiHour" (
    "userId" TEXT NOT NULL,
    "day" TEXT NOT NULL,
    "startedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "SiteAiHour_pkey" PRIMARY KEY ("userId", "day"),
    CONSTRAINT "SiteAiHour_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE
  )`,
  `CREATE INDEX IF NOT EXISTS "SiteAiCreditLog_kind_createdAt_idx" ON "SiteAiCreditLog"("kind", "createdAt")`,
];

const state = { ready: false };
async function ensureSiteTables() {
  for (let attempt = 0; attempt < 3 && !state.ready; attempt++) {
    try {
      for (const sql of DDL) await prisma.$executeRawUnsafe(sql);
      state.ready = true;
      console.log('Member site tables ready.');
    } catch (err) {
      console.error('Member site table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return state.ready;
}

// ---------------------------------------------------------------- cleaning what members and visitors send
function oneLine(v, max) {
  return String(v == null ? '' : v).replace(/[\u0000-\u001f\u007f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, max);
}
function multiLine(v, max) {
  return String(v == null ? '' : v).replace(/\r\n?/g, '\n').replace(/[\u0000-\u0009\u000b-\u001f\u007f]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n').trim().slice(0, max);
}
const EMAIL_RE = /^[^\s@<>"]+@[^\s@<>"]+\.[^\s@<>"]{2,}$/;

// The accent colours a member can pick for their page (the rest of the page stays plain and light).
const COLORS = {
  green: '#16865A',
  blue: '#2459D6',
  purple: '#7E3BD0',
  orange: '#C2540A',
  red: '#C62F2F',
  black: '#1D2321',
};

// Addresses that would look like The Guide's own pages, or that people might mistake for them.
const RESERVED = new Set(['admin', 'api', 'app', 'account', 'billing', 'help', 'support', 'login', 'signup', 'signin',
  'logout', 'pro', 'guide', 'guides', 'theguide', 'the-guide', 'guider', 'the-guider', 'official', 'www', 'mail', 'email',
  'terms', 'privacy', 'about', 'contact', 'start', 'tools', 'quiz', 'media', 'static', 'assets', 'test', 'null', 'undefined']);

/** "Joe's Lawns!" → "joes-lawns". Returns '' when nothing usable is left. */
function slugify(v) {
  return String(v == null ? '' : v).toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/['’]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/g, '');
}
/** null when the address is fine, otherwise what to tell the member. */
function slugProblem(slug) {
  if (!slug || slug.length < 3) return 'Pick a web address of at least 3 letters or numbers.';
  if (!/^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$/.test(slug)) return 'Use only letters, numbers and dashes for the web address.';
  if (RESERVED.has(slug) || /^the-?guide/.test(slug)) return 'That web address is kept for The Guide. Try one with your business name.';
  return null;
}

/** What a member's page says, cleaned. Nothing else from the request is kept. */
function cleanSiteData(b) {
  b = b && typeof b === 'object' ? b : {};
  const services = (Array.isArray(b.services) ? b.services : []).slice(0, 8)
    .map(s => ({ name: oneLine(s && s.name, 60), price: oneLine(s && s.price, 30), note: oneLine(s && s.note, 160) }))
    .filter(s => s.name);
  const email = oneLine(b.email, 120).toLowerCase();
  const phone = oneLine(b.phone, 30).replace(/[^\d+()\-.\s]/g, '').trim();
  return {
    name: oneLine(b.name, 60),
    tagline: oneLine(b.tagline, 140),
    area: oneLine(b.area, 80),
    hours: oneLine(b.hours, 80),
    about: multiLine(b.about, 800),
    services,
    email: EMAIL_RE.test(email) ? email : '',
    phone: phone.replace(/\D/g, '').length >= 6 ? phone : '',
    color: Object.prototype.hasOwnProperty.call(COLORS, b.color) ? b.color : 'green',
    nicheId: /^[a-z0-9_-]{1,30}$/.test(String(b.nicheId || '')) ? b.nicheId : '',
    // why people pick this business: up to three short points
    highlights: (Array.isArray(b.highlights) ? b.highlights : []).slice(0, 3).map(h => oneLine(h, 100)).filter(Boolean),
    // questions customers ask, with the answers
    faq: (Array.isArray(b.faq) ? b.faq : []).slice(0, 6)
      .map(f => ({ q: oneLine(f && f.q, 120), a: multiLine(f && f.a, 400) }))
      .filter(f => f.q && f.a),
    // the language of the page itself (the words around the member's own text)
    lang: b.lang === 'es' ? 'es' : 'en',
  };
}
/** What has to be there before a page can go live. null when it's ready. */
function publishProblem(data) {
  if (!data.name) return 'Add your business name before you publish.';
  if (!data.services.length && !data.about) return 'Add at least one service (or a few words about you) before you publish.';
  return null;
}

/** A request from a visitor, cleaned. `error` says what to fix. */
function cleanRequest(b) {
  b = b && typeof b === 'object' ? b : {};
  const out = {
    name: oneLine(b.name, 60),
    contact: oneLine(b.contact, 120),
    service: oneLine(b.service, 60),
    message: multiLine(b.message, 1000),
  };
  if (!out.name) out.error = 'Add your name.';
  else if (!out.contact || out.contact.replace(/[^a-z0-9]/gi, '').length < 5) out.error = 'Add a phone number or email so they can reach you.';
  return out;
}

// ---------------------------------------------------------------- the page itself
// The words around the member's own text, in the page's language.
const WORDS = {
  en: {
    quote: 'Ask for a quote', call: 'Call', email: 'Email', serving: 'Serving', services: 'Services and prices',
    why: (name) => `Why people choose ${name}`, faq: 'Questions people ask', about: 'About',
    sent: (name) => `Thanks. Your request was sent to ${name}. They will get back to you soon.`, them: 'them', thisBiz: 'this business',
    yourName: 'Your name', contact: 'Phone or email', need: 'What do you need?', choose: 'Choose one', other: 'Something else',
    message: 'Message', messageHint: 'When, where, and anything they should know', send: 'Send request',
    private: (name) => `Your details go only to ${name}, so they can reply.`, empty: 'Leave this empty',
    preview: 'Preview: only you can see this page until you publish it in the app.',
    madeWith: 'Made with', madeTail: ', where people learn to start a side business.', placeholderName: 'Your business name', soon: 'Coming soon',
  },
  es: {
    quote: 'Pide una cotización', call: 'Llamar al', email: 'Correo', serving: 'Servicio en', services: 'Servicios y precios',
    why: (name) => `Por qué elegir ${name}`, faq: 'Preguntas frecuentes', about: 'Sobre nosotros',
    sent: (name) => `Gracias. Tu solicitud se envió a ${name}. Te responderán pronto.`, them: 'ellos', thisBiz: 'este negocio',
    yourName: 'Tu nombre', contact: 'Teléfono o correo', need: '¿Qué necesitas?', choose: 'Elige uno', other: 'Otra cosa',
    message: 'Mensaje', messageHint: 'Cuándo, dónde y lo que deban saber', send: 'Enviar solicitud',
    private: (name) => `Tus datos solo le llegan a ${name}, para que te pueda responder.`, empty: 'Deja esto vacío',
    preview: 'Vista previa: solo tú puedes ver esta página hasta que la publiques en la app.',
    madeWith: 'Hecho con', madeTail: ', donde la gente aprende a empezar un negocio paralelo.', placeholderName: 'El nombre de tu negocio', soon: 'Muy pronto',
  },
};
// The form's messages to visitors, in Spanish for Spanish pages.
const ERRORS_ES = {
  'Add your name.': 'Escribe tu nombre.',
  'Add a phone number or email so they can reach you.': 'Escribe un teléfono o correo para que te puedan contactar.',
  'Too many requests from here. Please try again later, or call or email instead.': 'Demasiadas solicitudes desde aquí. Inténtalo más tarde, o llama o escribe un correo.',
  'This page has had a lot of requests today. Please try again tomorrow, or call or email instead.': 'Esta página recibió muchas solicitudes hoy. Inténtalo mañana, o llama o escribe un correo.',
};
const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const telHref = (phone) => 'tel:' + phone.replace(/[^\d+]/g, '');

function shell({ title, description, canonical, robots, body, color, jsonLd, lang }) {
  return `<!DOCTYPE html>
<html lang="${lang === 'es' ? 'es' : 'en'}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
${description ? `<meta name="description" content="${esc(description)}">` : ''}
<meta name="robots" content="${robots}">
${canonical ? `<link rel="canonical" href="${esc(canonical)}">
<meta property="og:type" content="website">
<meta property="og:title" content="${esc(title)}">
${description ? `<meta property="og:description" content="${esc(description)}">` : ''}
<meta property="og:url" content="${esc(canonical)}">` : ''}
<meta name="theme-color" content="${color}">
<link rel="icon" href="${SITE_ORIGIN}/icons/favicon-32.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
${jsonLd ? `<script type="application/ld+json">${JSON.stringify(jsonLd).replace(/</g, '\\u003c')}</script>` : ''}
<style>
  :root{ --accent:${color}; --ink:#15191A; --ink-2:#3B4442; --muted:#66706D; --line:#E3E7E5; --bg:#FFFFFF; --soft:#F5F7F6; --ok:#16865A; --bad:#B42318; }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0}
  body{background:var(--bg);color:var(--ink);font:16px/1.6 'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;-webkit-font-smoothing:antialiased}
  .wrap{max-width:720px;margin:0 auto;padding:0 20px}
  .top{border-top:6px solid var(--accent);padding:48px 0 32px}
  h1{font-size:34px;line-height:1.15;letter-spacing:-.02em;margin:0 0 8px}
  .tag{font-size:18px;color:var(--ink-2);margin:0 0 16px;max-width:60ch}
  .meta{display:flex;flex-wrap:wrap;gap:4px 16px;color:var(--muted);font-size:14px;margin:0 0 24px}
  .acts{display:flex;flex-wrap:wrap;gap:8px}
  .btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 20px;border-radius:10px;font:600 15px/1 'Inter',sans-serif;text-decoration:none;cursor:pointer;border:1px solid var(--accent);background:var(--accent);color:#fff}
  .btn.ghost{background:transparent;color:var(--accent)}
  section{padding:32px 0;border-top:1px solid var(--line)}
  h2{font-size:20px;letter-spacing:-.01em;margin:0 0 16px}
  .svc{display:flex;justify-content:space-between;align-items:baseline;gap:16px;padding:12px 0;border-bottom:1px solid var(--line)}
  .svc:last-child{border-bottom:0}
  .svc b{font-weight:600}
  .svc small{display:block;color:var(--muted);font-size:14px;margin-top:2px}
  .svc .price{font-weight:600;white-space:nowrap;color:var(--ink)}
  .about{white-space:pre-line;color:var(--ink-2);max-width:65ch;margin:0}
  .why{list-style:none;padding:0;margin:0;display:grid;gap:12px}
  .why li{padding-left:28px;position:relative;color:var(--ink-2)}
  .why li::before{content:'';position:absolute;left:4px;top:.55em;width:10px;height:10px;border-radius:50%;background:var(--accent)}
  .faq details{border-bottom:1px solid var(--line);padding:12px 0}
  .faq details:last-child{border-bottom:0}
  .faq summary{cursor:pointer;font-weight:600;list-style:none}
  .faq summary::-webkit-details-marker{display:none}
  .faq summary::after{content:'+';float:right;color:var(--muted);font-weight:400}
  .faq details[open] summary::after{content:'–'}
  .faq p{margin:8px 0 0;color:var(--ink-2);white-space:pre-line}
  form{display:grid;gap:12px;max-width:520px}
  label{display:grid;gap:4px;font-size:14px;font-weight:500;color:var(--ink-2)}
  input,select,textarea{font:16px 'Inter',sans-serif;padding:10px 12px;min-height:44px;border:1px solid #C9D0CD;border-radius:10px;background:#fff;color:var(--ink);width:100%}
  textarea{min-height:110px;resize:vertical}
  input:focus,select:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:var(--accent)}
  .hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
  .note{padding:12px 16px;border-radius:10px;background:var(--soft);font-size:15px;margin:0 0 16px}
  .note.ok{border-left:4px solid var(--ok)}
  .note.bad{border-left:4px solid var(--bad)}
  .small{font-size:13px;color:var(--muted)}
  .preview{background:var(--ink);color:#fff;text-align:center;font-size:14px;padding:10px 16px}
  footer{padding:32px 0 48px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
  footer a{color:var(--muted)}
  @media (max-width:520px){ h1{font-size:28px} .top{padding-top:32px} .btn{flex:1 1 auto} }
</style>
</head>
<body>
${body}
</body>
</html>`;
}

/** The member's page. `opts`: {preview, sent, error, form} — what to show after the form was used. */
function renderSitePage(site, opts = {}) {
  const d = cleanSiteData(site.data);
  const W = WORDS[d.lang] || WORDS.en;
  const color = COLORS[d.color] || COLORS.green;
  const url = `${SITE_ORIGIN}/s/${site.slug}`;
  const title = d.area ? `${d.name} · ${d.area}` : d.name || W.soon;
  const description = d.tagline || (d.services.length ? d.services.map(s => s.name).slice(0, 4).join(', ') : '') || d.about.slice(0, 150);
  const form = opts.form || {};
  const error = opts.error && d.lang === 'es' ? (ERRORS_ES[opts.error] || opts.error) : opts.error;
  const contactBtns = [
    `<a class="btn" href="#ask">${W.quote}</a>`,
    d.phone ? `<a class="btn ghost" href="${esc(telHref(d.phone))}">${W.call} ${esc(d.phone)}</a>` : '',
    d.email ? `<a class="btn ghost" href="mailto:${esc(d.email)}">${W.email}</a>` : '',
  ].join('');
  const services = d.services.length ? `<section id="services"><h2>${W.services}</h2>
      ${d.services.map(s => `<div class="svc"><div><b>${esc(s.name)}</b>${s.note ? `<small>${esc(s.note)}</small>` : ''}</div>${s.price ? `<span class="price">${esc(s.price)}</span>` : ''}</div>`).join('')}
    </section>` : '';
  const why = d.highlights.length ? `<section id="why"><h2>${esc(W.why(d.name || W.thisBiz))}</h2>
      <ul class="why">${d.highlights.map(h => `<li>${esc(h)}</li>`).join('')}</ul></section>` : '';
  const about = d.about ? `<section id="about"><h2>${W.about}</h2><p class="about">${esc(d.about)}</p></section>` : '';
  const faq = d.faq.length ? `<section id="faq" class="faq"><h2>${W.faq}</h2>
      ${d.faq.map(f => `<details><summary>${esc(f.q)}</summary><p>${esc(f.a)}</p></details>`).join('')}</section>` : '';
  const options = d.services.map(s => `<option${form.service === s.name ? ' selected' : ''}>${esc(s.name)}</option>`).join('');
  const action = `/s/${esc(site.slug)}/request${opts.preview ? `?preview=${esc(opts.previewKey || '')}` : ''}`;
  const ask = opts.sent
    ? `<p class="note ok" role="status">${esc(W.sent(d.name || W.them))}</p>`
    : `${error ? `<p class="note bad" role="alert">${esc(error)}</p>` : ''}
      <form method="post" action="${action}">
        <label>${W.yourName}<input name="name" required maxlength="60" autocomplete="name" value="${esc(form.name || '')}"></label>
        <label>${W.contact}<input name="contact" required maxlength="120" autocomplete="on" value="${esc(form.contact || '')}"></label>
        ${options ? `<label>${W.need}<select name="service"><option value="">${W.choose}</option>${options}<option${form.service === 'Something else' ? ' selected' : ''} value="Something else">${W.other}</option></select></label>` : ''}
        <label>${W.message}<textarea name="message" maxlength="1000" placeholder="${W.messageHint}">${esc(form.message || '')}</textarea></label>
        <div class="hp" aria-hidden="true"><label>${W.empty}<input name="website" tabindex="-1" autocomplete="off"></label></div>
        <div><button class="btn" type="submit">${W.send}</button></div>
        <p class="small">${esc(W.private(d.name || W.thisBiz))}</p>
      </form>`;
  const business = {
    '@context': 'https://schema.org', '@type': 'LocalBusiness', name: d.name, url,
    ...(description ? { description } : {}), ...(d.area ? { areaServed: d.area } : {}),
    ...(d.phone ? { telephone: d.phone } : {}), ...(d.email ? { email: d.email } : {}),
    ...(d.services.length ? { makesOffer: d.services.map(s => ({ '@type': 'Offer', itemOffered: { '@type': 'Service', name: s.name }, ...(s.price ? { description: s.price } : {}) })) } : {}),
  };
  const jsonLd = d.faq.length ? [business, { '@context': 'https://schema.org', '@type': 'FAQPage',
    mainEntity: d.faq.map(f => ({ '@type': 'Question', name: f.q, acceptedAnswer: { '@type': 'Answer', text: f.a } })) }] : business;
  const body = `${opts.preview ? `<div class="preview">${W.preview}</div>` : ''}
<main class="wrap">
  <header class="top">
    <h1>${esc(d.name || W.placeholderName)}</h1>
    ${d.tagline ? `<p class="tag">${esc(d.tagline)}</p>` : ''}
    ${d.area || d.hours ? `<p class="meta">${d.area ? `<span>${W.serving} ${esc(d.area)}</span>` : ''}${d.hours ? `<span>${esc(d.hours)}</span>` : ''}</p>` : ''}
    <div class="acts">${contactBtns}</div>
  </header>
  ${services}
  ${why}
  ${about}
  ${faq}
  <section id="ask"><h2>${W.quote}</h2>${ask}</section>
</main>
<footer><div class="wrap">${W.madeWith} <a href="${SITE_ORIGIN}/?utm_source=member_site&amp;utm_medium=referral&amp;utm_campaign=${esc(site.slug)}${d.lang === 'es' ? '&amp;lang=es' : ''}">The Guide</a>${W.madeTail}</div></footer>`;
  return shell({ title, description, canonical: opts.preview ? '' : url, robots: opts.preview ? 'noindex, nofollow' : 'index, follow', body, color, jsonLd: opts.preview ? null : jsonLd, lang: d.lang });
}

/** For an address with no live page behind it. */
function renderMissingPage() {
  const body = `<main class="wrap"><header class="top"><h1>This page isn't available</h1>
    <p class="tag">The business may have moved it or taken it down for now.</p>
    <div class="acts"><a class="btn" href="${SITE_ORIGIN}/?utm_source=member_site&amp;utm_medium=referral&amp;utm_campaign=missing">Go to The Guide</a></div></header></main>`;
  return shell({ title: 'Page not available', description: '', canonical: '', robots: 'noindex, nofollow', body, color: COLORS.black });
}

module.exports = {
  SITE_ORIGIN, COLORS, state, ensureSiteTables, oneLine, slugify, slugProblem, cleanSiteData, publishProblem,
  cleanRequest, renderSitePage, renderMissingPage,
};
