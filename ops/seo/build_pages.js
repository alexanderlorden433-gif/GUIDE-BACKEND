#!/usr/bin/env node
/* Public pages Google can find: one guide page per business (with its free Module 1 in full), a hub page,
   free calculators, sitemap.xml and robots.txt. Everything is generated from the lesson files in web/niches/,
   so the pages never drift from the app.

     node ops/seo/build_pages.js          # write the pages
     node ops/seo/build_pages.js --check  # exit 1 if the pages are out of date (used by ops/check.sh)

   Output (all plain files, published by Netlify as-is):
     web/start/index.html                 every business, one list
     web/start/<slug>/index.html          one page per business
     web/tools/index.html, web/tools/<tool>/index.html
     web/sitemap.xml, web/robots.txt
*/
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');
const WEB = path.join(ROOT, 'web');
const SITE = 'https://theguide.company';
const CHECK = process.argv.includes('--check');

// ---------- the lesson data, exactly as the app loads it ----------
function loadChapters() {
  const ctx = { window: {} };
  vm.createContext(ctx);
  const files = ['base.js', ...fs.readdirSync(path.join(WEB, 'niches')).filter(f => /^pack-\d+\.js$/.test(f)).sort()];
  for (const f of files) vm.runInContext(fs.readFileSync(path.join(WEB, 'niches', f), 'utf8'), ctx, { filename: f });
  const list = [...(ctx.window.GUIDE_NICHES || [])];
  for (const pack of ctx.window.NICHE_PACKS || []) {
    for (const e of pack) if (!list.some(n => n.id === e.chapter.id)) list.push(Object.assign({}, e.chapter, { guides: e.guides }));
  }
  return list;
}

// Each business gets a plain-English address and the words people actually search for.
// The OnlyFans chapter stays off public pages (same rule as the ads).
const PAGES = {
  lawn:       { slug: 'lawn-care-business',             h1: 'How to start a lawn care business' },
  cleaning:   { slug: 'cleaning-business',              h1: 'How to start a cleaning and pressure washing business' },
  detailing:  { slug: 'mobile-car-detailing-business',  h1: 'How to start a mobile car detailing business' },
  handyman:   { slug: 'handyman-business',              h1: 'How to start a handyman business' },
  pets:       { slug: 'pet-sitting-dog-walking-business', h1: 'How to start a pet sitting and dog walking business' },
  local:      { slug: 'local-service-business',         h1: 'How to start a local service business' },
  ecommerce:  { slug: 'ecommerce-business',             h1: 'How to start an e-commerce business' },
  affiliate:  { slug: 'affiliate-marketing',            h1: 'How to start affiliate marketing' },
  ugc:        { slug: 'ugc-creator',                    h1: 'How to become a UGC creator' },
  creator:    { slug: 'content-creator-business',       h1: 'How to start a content creator business' },
  social:     { slug: 'social-media-manager',           h1: 'How to become a freelance social media manager' },
  writing:    { slug: 'freelance-writing',              h1: 'How to start freelance writing and copywriting' },
  design:     { slug: 'graphic-design-business',        h1: 'How to start a graphic design business' },
  va:         { slug: 'virtual-assistant-business',     h1: 'How to start a virtual assistant business' },
  marketing:  { slug: 'online-marketing-business',      h1: 'How to start an online marketing business' },
  video:      { slug: 'videography-business',           h1: 'How to start a videography business' },
  photo:      { slug: 'photography-business',           h1: 'How to start a photography business' },
  coaching:   { slug: 'coaching-business',              h1: 'How to start a coaching or consulting business' },
  realestate: { slug: 'real-estate',                    h1: 'How to get started in real estate' },
  trading:    { slug: 'trading-for-beginners',          h1: 'Trading and investing for beginners' },
};
const HIDDEN = new Set(['ofm']);

const TOOLS = [
  { slug: 'hourly-rate-calculator', name: 'Hourly rate calculator', short: 'How much to charge per hour',
    title: 'How much should I charge? Hourly rate calculator for freelancers and side businesses',
    desc: 'Work backward from the income you want to the hourly rate you need. Free, no signup: add your goal, costs and billable hours.' },
  { slug: 'profit-margin-calculator', name: 'Profit margin calculator', short: 'What a job or product really earns',
    title: 'Profit margin calculator: what a job or product really earns',
    desc: 'Enter what you charge and what it costs you to see your profit and margin, or set the margin you want and get the price. Free, no signup.' },
  { slug: 'job-quote-calculator', name: 'Job quote calculator', short: 'Quote a job without guessing',
    title: 'Job quote calculator for cleaning, lawn care, detailing and handyman work',
    desc: 'Add your time, materials and travel to get a quote that covers your costs and pays you properly. Free, no signup.' },
];

// ---------- helpers ----------
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const plain = (s) => String(s || '').replace(/\s+—\s+/g, ', ').replace(/\s+/g, ' ').trim();
const clip = (s, n) => { s = plain(s); return s.length <= n ? s : s.slice(0, s.lastIndexOf(' ', n - 1)).replace(/[,;:.]$/, '') + '…'; };
const words = (s) => String(s || '').split(/\s+/).filter(Boolean).length;
const appLink = (id, campaign) => `/?start=${encodeURIComponent(id)}&utm_source=guide_pages&utm_medium=organic&utm_campaign=${encodeURIComponent(campaign)}`;

// Lesson text: paragraphs split by blank lines; lines starting "- " or "1. " become lists.
function lessonHtml(text) {
  const out = [];
  for (const block of String(text || '').split(/\n\s*\n/)) {
    const lines = block.split('\n').map(l => l.trim()).filter(Boolean);
    let para = [], list = null, kind = '';
    const flushP = () => { if (para.length) out.push(`<p>${esc(para.join(' '))}</p>`); para = []; };
    const flushL = () => { if (list) out.push(`<${kind}>${list.map(i => `<li>${esc(i)}</li>`).join('')}</${kind}>`); list = null; };
    for (const l of lines) {
      const ul = l.match(/^[-•]\s+(.*)$/), ol = l.match(/^\d+[.)]\s+(.*)$/);
      if (ul || ol) {
        const k = ul ? 'ul' : 'ol';
        flushP();
        if (list && kind !== k) flushL();
        if (!list) { list = []; kind = k; }
        list.push((ul || ol)[1]);
      } else { flushL(); para.push(l); }
    }
    flushP(); flushL();
  }
  return out.join('\n');
}

const LOGO = `<svg class="pg-logo" viewBox="0 0 200 200" aria-hidden="true"><circle cx="100" cy="100" r="82" fill="none" stroke-width="14"/><path d="M100,32 L114.1,85.9 L168,100 L114.1,114.1 L100,168 L85.9,114.1 L32,100 L85.9,85.9 Z"/><circle class="pg-logo-dot" cx="100" cy="100" r="14"/></svg>`;

function page({ url, title, desc, body, jsonld = [], ogImage = '/img/og/og-default.jpg', scripts = '' }) {
  const ld = jsonld.map(o => `<script type="application/ld+json">${JSON.stringify(o).replace(/</g, '\\u003c')}</script>`).join('\n');
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${esc(title)}</title>
<meta name="description" content="${esc(desc)}">
<link rel="canonical" href="${SITE}${url}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="The Guide">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:url" content="${SITE}${url}">
<meta property="og:image" content="${SITE}${ogImage}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0C1310">
<link rel="icon" type="image/png" href="/icons/favicon-32.png">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/pages.css">
${ld}
</head>
<body>
<header class="pg-top"><div class="pg-wrap pg-top-in">
  <a class="pg-brand" href="/">${LOGO}<span>The Guide</span></a>
  <nav class="pg-nav" aria-label="Site"><a href="/start/">Business guides</a><a href="/tools/">Free calculators</a><a class="pg-btn pg-btn-sm" href="/?utm_source=guide_pages&amp;utm_medium=organic&amp;utm_campaign=header">Start free</a></nav>
</div></header>
<main class="pg-wrap">
${body}
</main>
<footer class="pg-foot"><div class="pg-wrap">
  <p>Guides reflect general practice, not guaranteed outcomes. Nothing here is financial, legal or tax advice.</p>
  <p><a href="/">The Guide</a> · <a href="/start/">Business guides</a> · <a href="/tools/">Free calculators</a> · <a href="/privacy.html">Privacy</a> · <a href="/terms.html">Terms</a></p>
</div></footer>
${scripts}
</body>
</html>
`;
}

const ORG = { '@type': 'Organization', name: 'The Guide', url: SITE, logo: `${SITE}/icons/icon-512.png` };
const crumbs = (items) => ({ '@context': 'https://schema.org', '@type': 'BreadcrumbList',
  itemListElement: items.map(([name, url], i) => ({ '@type': 'ListItem', position: i + 1, name, item: SITE + url })) });

// ---------- one business ----------
function chapterPage(n, all) {
  const meta = PAGES[n.id];
  const url = `/start/${meta.slug}/`;
  const mods = n.modules || [];
  const m1 = n.guides.filter(g => g.mod === 0);
  const total = n.guides.length;
  const bd = n.breakdown || null;
  const lead = plain(n.description);
  const title = `${meta.h1}: a free step-by-step course | The Guide`;
  const desc = clip(`${meta.h1}, one step at a time. ${plain(n.description)} Read Module 1 free: ${m1.length} lessons, each ending in one thing to do.`, 158);
  const facts = bd ? `
  <dl class="pg-facts">
    ${bd.cost ? `<div><dt>What it costs to start</dt><dd>${esc(bd.cost)}</dd></div>` : ''}
    ${bd.difficulty ? `<div><dt>How hard it is</dt><dd>${esc(bd.difficulty)}</dd></div>` : ''}
    <div><dt>The course</dt><dd>${mods.length} modules, ${total} lessons</dd></div>
  </dl>` : `
  <dl class="pg-facts"><div><dt>The course</dt><dd>${mods.length} modules, ${total} lessons, each with a narrated video</dd></div><div><dt>Free to start</dt><dd>Module 1, ${m1.length} lessons</dd></div></dl>`;
  const pieces = bd && Array.isArray(bd.pieces) ? bd.pieces.filter(p => p && p.title && p.body).slice(0, 6) : [];
  const piecesHtml = pieces.length ? `
  <section class="pg-sec">
    <h2>Is it right for you?</h2>
    <div class="pg-pieces">${pieces.map(p => `
      <div><h3>${esc(p.title)}</h3><p>${esc(p.body)}</p>${Array.isArray(p.points) && p.points.length ? `<ul>${p.points.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}</div>`).join('')}
    </div>
  </section>` : '';
  const lessons = m1.map((g, i) => `
    <article class="pg-lesson" id="lesson-${i + 1}">
      <p class="pg-k">Lesson ${i + 1} of ${total} · ${esc(g.time || '')} read</p>
      <h3>${esc(g.title)}</h3>
      ${lessonHtml(g.content)}
      ${g.action ? `<div class="pg-step"><b>Your step</b><p>${esc(g.action)}</p></div>` : ''}
    </article>`).join('');
  const others = all.filter(x => x.id !== n.id && PAGES[x.id]).slice(0, 40);
  const sameGroup = others.filter(x => (x.group || (x.breakdown && x.breakdown.group)) && (x.group || x.breakdown.group) === (n.group || (bd && bd.group)));
  const related = (sameGroup.length >= 3 ? sameGroup : others).slice(0, 6);
  const disclaimer = n.id === 'trading' ? `<p class="pg-note">Educational content only, not financial advice. Trading can lose money, including more than you put in.</p>` : '';
  const body = `
<nav class="pg-crumbs" aria-label="Breadcrumb"><a href="/start/">Business guides</a> <span aria-hidden="true">/</span> ${esc(n.name)}</nav>
<section class="pg-hero">
  <p class="pg-k">${esc(n.name)} · free step-by-step course</p>
  <h1>${esc(meta.h1)}</h1>
  <p class="pg-lead">${esc(lead)}</p>
  ${disclaimer}
  <div class="pg-ctas"><a class="pg-btn" href="${appLink(n.id, meta.slug)}">Start Module 1 free</a><a class="pg-btn pg-btn-2" href="#module-1">Read it here first</a></div>
  ${facts}
</section>
${piecesHtml}
<section class="pg-sec">
  <h2>What the course covers</h2>
  <ol class="pg-mods">${mods.map((m, i) => `
    <li><b>Module ${i + 1}: ${esc(m.title)}</b>${m.goal ? `<span>${esc(m.goal)}</span>` : ''}${i === 0 ? '<em>Free</em>' : ''}</li>`).join('')}
  </ol>
</section>
<section class="pg-sec" id="module-1">
  <h2>Module 1: ${esc((mods[0] && mods[0].title) || 'Start here')}</h2>
  <p class="pg-lead">The whole first module, free. Each lesson ends with one thing to do, so you finish with real progress, not just notes.</p>
  ${lessons}
</section>
<section class="pg-cta">
  <h2>Keep going in the app</h2>
  <p>Modules 2 to ${mods.length} pick up where this leaves off, with a narrated video for every lesson. Module 1 stays free and your progress saves as you go. Pro opens the rest of the course, plus the AI mentor, templates and trackers.</p>
  <div class="pg-ctas"><a class="pg-btn" href="${appLink(n.id, meta.slug)}">Start free</a></div>
</section>
<section class="pg-sec">
  <h2>Other businesses you could start</h2>
  <ul class="pg-list">${related.map(x => `<li><a href="/start/${PAGES[x.id].slug}/"><b>${esc(x.name)}</b><span>${esc(clip(x.breakdown && x.breakdown.oneLiner ? x.breakdown.oneLiner : x.description, 90))}</span></a></li>`).join('')}
    <li><a href="/tools/"><b>Free calculators</b><span>Work out what to charge and what a job really earns</span></a></li>
  </ul>
</section>`;
  const jsonld = [
    { '@context': 'https://schema.org', '@type': 'Course', name: meta.h1, description: plain(n.description), url: SITE + url,
      provider: ORG, inLanguage: 'en',
      hasCourseInstance: { '@type': 'CourseInstance', courseMode: 'online', courseWorkload: `PT${Math.max(1, Math.round(total * 4 / 60))}H` },
      offers: { '@type': 'Offer', category: 'Partially Free' } },
    crumbs([['Business guides', '/start/'], [n.name, url]]),
  ];
  return { url, html: page({ url, title, desc, body, jsonld, ogImage: `/img/og/og-${n.id}.jpg` }), words: words(body.replace(/<[^>]+>/g, ' ')) };
}

// ---------- the list of businesses ----------
function hubPage(chs) {
  const url = '/start/';
  const groups = [
    ['Local services', chs.filter(n => ['lawn', 'cleaning', 'detailing', 'handyman', 'pets', 'local'].includes(n.id))],
    ['Online and creative', chs.filter(n => ['ecommerce', 'affiliate', 'ugc', 'creator', 'social', 'writing', 'design', 'va', 'marketing', 'video', 'photo', 'coaching'].includes(n.id))],
    ['Property and markets', chs.filter(n => ['realestate', 'trading'].includes(n.id))],
  ];
  const card = (n) => { const m = PAGES[n.id], bd = n.breakdown;
    return `<li><a href="/start/${m.slug}/"><b>${esc(n.name)}</b><span>${esc(clip(bd && bd.oneLiner ? bd.oneLiner : n.description, 100))}</span>${bd && bd.difficulty ? `<em>${esc(bd.difficulty)}</em>` : ''}</a></li>`; };
  const body = `
<section class="pg-hero">
  <p class="pg-k">Business guides</p>
  <h1>Start a side business, step by step</h1>
  <p class="pg-lead">${chs.length} real businesses, each taught as a course with modules in order. Every guide below has its first module free to read, and every lesson ends with one thing to do.</p>
  <div class="pg-ctas"><a class="pg-btn" href="/?utm_source=guide_pages&amp;utm_medium=organic&amp;utm_campaign=hub">Start free</a><a class="pg-btn pg-btn-2" href="/tools/">Free calculators</a></div>
</section>
${groups.filter(g => g[1].length).map(([name, list]) => `
<section class="pg-sec">
  <h2>${esc(name)}</h2>
  <ul class="pg-list">${list.map(card).join('')}</ul>
</section>`).join('')}`;
  const jsonld = [{ '@context': 'https://schema.org', '@type': 'ItemList', name: 'Business guides',
    itemListElement: chs.map((n, i) => ({ '@type': 'ListItem', position: i + 1, url: `${SITE}/start/${PAGES[n.id].slug}/`, name: n.name })) }];
  return { url, html: page({ url, title: `Start a side business: ${chs.length} free step-by-step guides | The Guide`,
    desc: `Pick a real business and follow it step by step: lawn care, cleaning, detailing, e-commerce, UGC, freelance writing and more. Module 1 of every guide is free.`, body, jsonld }) };
}

// ---------- calculators ----------
function toolPage(t) {
  const url = `/tools/${t.slug}/`;
  const forms = {
    'hourly-rate-calculator': `
  <form class="pg-calc" data-calc="rate" onsubmit="return false">
    <label>What you want to take home in a year<span class="pg-in"><i>$</i><input type="number" inputmode="decimal" name="income" value="30000" min="0"></span></label>
    <label>Business costs in a year (tools, software, insurance, ads, travel)<span class="pg-in"><i>$</i><input type="number" inputmode="decimal" name="costs" value="3000" min="0"></span></label>
    <label>Set aside for taxes<span class="pg-in"><input type="number" inputmode="decimal" name="tax" value="25" min="0" max="80"><i>%</i></span></label>
    <label>Hours a week you can bill a client for<span class="pg-in"><input type="number" inputmode="decimal" name="hours" value="15" min="1"><i>hrs</i></span></label>
    <label>Weeks a year you'll work (after time off)<span class="pg-in"><input type="number" inputmode="decimal" name="weeks" value="46" min="1" max="52"><i>wks</i></span></label>
    <output class="pg-out" aria-live="polite"></output>
  </form>
  <section class="pg-sec">
    <h2>How it works</h2>
    <p>Your rate has to cover three things: the money you want to keep, what the business costs to run, and the tax on what's left. The calculator adds those up and divides by the hours you can actually bill.</p>
    <p>Billable hours are the hours a client pays for. Quoting, messages, driving, marketing and bookkeeping are real work too, but nobody pays for them directly, which is why your rate usually comes out higher than you'd expect. Most people starting out bill fewer hours than they plan.</p>
    <p>Treat the number as your floor. If it's far above what people near you charge, look at the costs and hours first, then at offering packages instead of hours. The tax figure is a rough set-aside, not tax advice; rules depend on where you live.</p>
  </section>`,
    'profit-margin-calculator': `
  <form class="pg-calc" data-calc="margin" onsubmit="return false">
    <label>What you charge<span class="pg-in"><i>$</i><input type="number" inputmode="decimal" name="price" value="150" min="0"></span></label>
    <label>What it costs you (materials, fees, shipping, travel, helpers)<span class="pg-in"><i>$</i><input type="number" inputmode="decimal" name="cost" value="60" min="0"></span></label>
    <output class="pg-out" aria-live="polite"></output>
  </form>
  <form class="pg-calc" data-calc="price" onsubmit="return false">
    <h2>Or start from the margin you want</h2>
    <label>What it costs you<span class="pg-in"><i>$</i><input type="number" inputmode="decimal" name="cost" value="60" min="0"></span></label>
    <label>Margin you want to keep<span class="pg-in"><input type="number" inputmode="decimal" name="margin" value="50" min="0" max="95"><i>%</i></span></label>
    <output class="pg-out" aria-live="polite"></output>
  </form>
  <section class="pg-sec">
    <h2>Margin and markup are not the same</h2>
    <p>Margin is the share of the price you keep: charge $150 with $60 of costs and you keep $90, a 60% margin. Markup is how much you add on top of cost: $90 on top of $60 is a 150% markup. Mixing them up is one of the most common pricing mistakes, and it usually means charging too little.</p>
    <p>Count every cost that comes with the sale: payment fees, packaging, shipping, gas, supplies, the share of your ads it took to get the order. If you leave them out, the margin looks healthy on paper and disappears in practice.</p>
  </section>`,
    'job-quote-calculator': `
  <form class="pg-calc" data-calc="quote" onsubmit="return false">
    <label>Hours the job takes (including setup and clean-up)<span class="pg-in"><input type="number" inputmode="decimal" name="hours" value="3" min="0"><i>hrs</i></span></label>
    <label>Your hourly rate<span class="pg-in"><i>$</i><input type="number" inputmode="decimal" name="rate" value="40" min="0"></span></label>
    <label>Materials and supplies for this job<span class="pg-in"><i>$</i><input type="number" inputmode="decimal" name="materials" value="25" min="0"></span></label>
    <label>Round-trip miles<span class="pg-in"><input type="number" inputmode="decimal" name="miles" value="12" min="0"><i>mi</i></span></label>
    <label>Cost per mile (gas and wear)<span class="pg-in"><i>$</i><input type="number" inputmode="decimal" name="permile" value="0.70" min="0" step="0.01"></span></label>
    <label>Buffer for the unexpected<span class="pg-in"><input type="number" inputmode="decimal" name="buffer" value="10" min="0" max="50"><i>%</i></span></label>
    <output class="pg-out" aria-live="polite"></output>
  </form>
  <section class="pg-sec">
    <h2>Quote the job, not the hour</h2>
    <p>Customers compare totals. Work out your number from your time, your materials and the drive, then give one clear price for the job. A small buffer covers the stubborn stain, the extra trip for supplies and the yard that's bigger than it looked in the photo.</p>
    <p>Don't know your hourly rate yet? Start with the <a href="/tools/hourly-rate-calculator/">hourly rate calculator</a>. The cost per mile is up to you: count gas and a share of maintenance, or use the standard mileage rate where you live.</p>
  </section>`,
  };
  const body = `
<nav class="pg-crumbs" aria-label="Breadcrumb"><a href="/tools/">Free calculators</a> <span aria-hidden="true">/</span> ${esc(t.name)}</nav>
<section class="pg-hero">
  <p class="pg-k">Free calculator · no signup</p>
  <h1>${esc(t.name)}</h1>
  <p class="pg-lead">${esc(t.desc)}</p>
</section>
${forms[t.slug]}
<section class="pg-cta">
  <h2>Turn the number into a business</h2>
  <p>The Guide teaches ${'{{COUNT}}'} real businesses step by step, from your first price to your first repeat customer. Module 1 of every course is free.</p>
  <div class="pg-ctas"><a class="pg-btn" href="/?utm_source=guide_pages&amp;utm_medium=organic&amp;utm_campaign=${t.slug}">Start free</a><a class="pg-btn pg-btn-2" href="/start/">See the business guides</a></div>
</section>
<section class="pg-sec"><h2>More free calculators</h2><ul class="pg-list">${TOOLS.filter(x => x !== t).map(x => `<li><a href="/tools/${x.slug}/"><b>${esc(x.name)}</b><span>${esc(x.short)}</span></a></li>`).join('')}</ul></section>`;
  const jsonld = [{ '@context': 'https://schema.org', '@type': 'WebApplication', name: t.name, url: SITE + url, applicationCategory: 'BusinessApplication',
    operatingSystem: 'Any', offers: { '@type': 'Offer', price: 0, priceCurrency: 'USD' }, publisher: ORG }, crumbs([['Free calculators', '/tools/'], [t.name, url]])];
  return { url, html: page({ url, title: `${t.title} | The Guide`, desc: t.desc, body, jsonld, ogImage: '/img/og/og-tools.jpg', scripts: '<script src="/tools/calc.js" defer></script>' }) };
}

function toolsHub(count) {
  const url = '/tools/';
  const body = `
<section class="pg-hero">
  <p class="pg-k">Free calculators · no signup</p>
  <h1>Free calculators for side businesses</h1>
  <p class="pg-lead">Work out what to charge, what a job really earns and how to quote it. They run in your browser and nothing you type is sent anywhere.</p>
</section>
<section class="pg-sec"><ul class="pg-list">${TOOLS.map(t => `<li><a href="/tools/${t.slug}/"><b>${esc(t.name)}</b><span>${esc(t.short)}</span></a></li>`).join('')}</ul></section>
<section class="pg-cta">
  <h2>Pick a business and start it</h2>
  <p>The Guide teaches ${count} real businesses step by step. Module 1 of every course is free.</p>
  <div class="pg-ctas"><a class="pg-btn" href="/start/">See the business guides</a></div>
</section>`;
  return { url, html: page({ url, title: 'Free calculators for side businesses: rates, margins and quotes | The Guide',
    desc: 'Free calculators for freelancers and side businesses: hourly rate, profit margin and job quotes. No signup, nothing sent anywhere.', body, ogImage: '/img/og/og-tools.jpg' }) };
}

// ---------- write everything ----------
function build() {
  const all = loadChapters();
  const chs = all.filter(n => PAGES[n.id] && !HIDDEN.has(n.id));
  const missing = all.filter(n => !PAGES[n.id] && !HIDDEN.has(n.id)).map(n => n.id);
  if (missing.length) throw new Error(`No public page settings for chapter(s): ${missing.join(', ')}. Add them to PAGES in ops/seo/build_pages.js (or to HIDDEN).`);
  const files = {};
  const hub = hubPage(chs); files['start/index.html'] = hub.html;
  const urls = ['/', hub.url];
  for (const n of chs) { const p = chapterPage(n, chs); files[`start/${PAGES[n.id].slug}/index.html`] = p.html; urls.push(p.url); }
  const th = toolsHub(chs.length); files['tools/index.html'] = th.html; urls.push(th.url);
  for (const t of TOOLS) { const p = toolPage(t); files[`tools/${t.slug}/index.html`] = p.html.replace('{{COUNT}}', String(chs.length)); urls.push(p.url); }
  urls.push('/privacy.html', '/terms.html');
  files['sitemap.xml'] = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.map(u => `  <url><loc>${SITE}${u}</loc></url>`).join('\n')}\n</urlset>\n`;
  files['robots.txt'] = `User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: ${SITE}/sitemap.xml\n`;
  return { files, chs };
}

const { files, chs } = build();
let stale = [];
for (const [rel, html] of Object.entries(files)) {
  const full = path.join(WEB, rel);
  const cur = fs.existsSync(full) ? fs.readFileSync(full, 'utf8') : null;
  if (cur === html) continue;
  if (CHECK) { stale.push(rel); continue; }
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, html);
}
// pages for chapters that no longer exist
for (const dir of ['start']) {
  const base = path.join(WEB, dir);
  if (!fs.existsSync(base)) continue;
  for (const d of fs.readdirSync(base)) {
    const rel = `${dir}/${d}/index.html`;
    if (fs.statSync(path.join(base, d)).isDirectory() && !files[rel]) {
      if (CHECK) stale.push(rel + ' (no longer a chapter)');
      else fs.rmSync(path.join(base, d), { recursive: true });
    }
  }
}
if (CHECK) {
  if (stale.length) { console.log(`Public pages out of date: ${stale.slice(0, 8).join(', ')}${stale.length > 8 ? '…' : ''}\nRun: node ops/seo/build_pages.js`); process.exit(1); }
  console.log(`Public pages up to date (${chs.length} business guides, ${TOOLS.length} calculators, sitemap)`);
} else {
  console.log(`Wrote ${Object.keys(files).length} files: ${chs.length} business guides, ${TOOLS.length} calculators, hub pages, sitemap.xml, robots.txt`);
}
