// First-party analytics for The Guide: page views, traffic-source
// attribution (Google Ads, Meta, TikTok, organic, creators...), live presence,
// and a live event bus that the owner and marketing dashboards stream from.
//
// Design notes
// - Tables are created on startup with CREATE TABLE IF NOT EXISTS, so this
//   works no matter how the database schema is normally applied. The same
//   tables are also declared in prisma/schema.prisma so `prisma db push`
//   keeps them instead of treating them as strays.
// - All queries are raw SQL aggregates run inside Postgres, so dashboards stay
//   fast as the user base grows (nothing loads every row into Node).
// - Writes are batched (flushed about once a second) and live dashboards get
//   each event pushed instantly from memory — they never wait on the database.
// - Analytics must never break the app: every entry point swallows its own
//   errors and logs them.

const crypto = require('crypto');
const { EventEmitter } = require('events');
const prisma = require('./db');

// ---------------------------------------------------------------- roles
function listEnv(name) {
  return (process.env[name] || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}
function roleFor(email) {
  const e = String(email || '').toLowerCase();
  const owner = !!(process.env.OWNER_EMAIL && e === process.env.OWNER_EMAIL.trim().toLowerCase());
  const marketing = owner || listEnv('MARKETING_EMAILS').includes(e);
  return { owner, marketing };
}
// Accounts whose activity shouldn't count as real users/traffic.
function staffEmails() {
  const out = new Set([...listEnv('MARKETING_EMAILS'), ...listEnv('PREVIEW_EMAILS')]);
  if (process.env.OWNER_EMAIL) out.add(process.env.OWNER_EMAIL.trim().toLowerCase());
  return [...out];
}
function isStaffEmail(email) { return staffEmails().includes(String(email || '').toLowerCase()); }

// ---------------------------------------------------------------- tables
const DDL = [
  `CREATE TABLE IF NOT EXISTS "AnalyticsEvent" (
    "id" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "visitorId" TEXT NOT NULL,
    "sessionId" TEXT NOT NULL,
    "userId" TEXT,
    "path" TEXT,
    "channel" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "medium" TEXT,
    "campaign" TEXT,
    "term" TEXT,
    "content" TEXT,
    "clickId" TEXT,
    "referrer" TEXT,
    "landing" TEXT,
    "device" TEXT,
    "browser" TEXT,
    "os" TEXT,
    "country" TEXT,
    "value" DOUBLE PRECISION,
    "meta" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "AnalyticsEvent_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE INDEX IF NOT EXISTS "AnalyticsEvent_createdAt_idx" ON "AnalyticsEvent"("createdAt")`,
  `CREATE INDEX IF NOT EXISTS "AnalyticsEvent_type_createdAt_idx" ON "AnalyticsEvent"("type", "createdAt")`,
  `CREATE INDEX IF NOT EXISTS "AnalyticsEvent_channel_createdAt_idx" ON "AnalyticsEvent"("channel", "createdAt")`,
  `CREATE INDEX IF NOT EXISTS "AnalyticsEvent_userId_idx" ON "AnalyticsEvent"("userId")`,
  `CREATE TABLE IF NOT EXISTS "UserAttribution" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "channel" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "medium" TEXT,
    "campaign" TEXT,
    "term" TEXT,
    "content" TEXT,
    "clickId" TEXT,
    "referrer" TEXT,
    "landing" TEXT,
    "device" TEXT,
    "country" TEXT,
    "firstSeenAt" TIMESTAMP(3),
    "lastChannel" TEXT,
    "lastSource" TEXT,
    "lastCampaign" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "UserAttribution_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "UserAttribution_userId_key" ON "UserAttribution"("userId")`,
  `CREATE INDEX IF NOT EXISTS "UserAttribution_channel_idx" ON "UserAttribution"("channel")`,
  `CREATE INDEX IF NOT EXISTS "UserAttribution_createdAt_idx" ON "UserAttribution"("createdAt")`,
];

let ready = false;
async function ensureAnalyticsTables() {
  for (let attempt = 0; attempt < 3 && !ready; attempt++) {
    try {
      for (const sql of DDL) await prisma.$executeRawUnsafe(sql);
      ready = true;
      console.log('Analytics tables ready.');
      try {
        const rows = await prisma.$queryRawUnsafe(`SELECT name FROM pg_timezone_names`);
        pgZones = new Set(rows.map(r => r.name));
      } catch (e) { /* fall back to the pattern + Intl check */ }
    } catch (err) {
      // Two instances starting at once can race on CREATE ... IF NOT EXISTS;
      // a short retry settles it.
      console.error('Analytics table setup failed (attempt ' + (attempt + 1) + '):', err.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
  return ready;
}
function isReady() { return ready; }

// ---------------------------------------------------------------- helpers
// Trims, caps length, and removes control characters and lone UTF-16
// surrogates (e.g. half an emoji after slicing) — the database driver rejects
// those, which would otherwise sink a whole batch of events.
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;
const s = (v, max = 200) => {
  if (v === undefined || v === null) return null;
  const out = String(v).replace(/[\u0000-\u001f]/g, ' ').trim().slice(0, max).replace(LONE_SURROGATE, '');
  return out || null;
};
const nowUtcLiteral = () => new Date().toISOString().replace('T', ' ').replace('Z', '');
const uuid = () => crypto.randomUUID();

// Only real IANA zone names (e.g. "America/New_York") — and, once loaded,
// only ones Postgres itself knows — so a bad value can never reach SQL.
let pgZones = null;
function validTz(tz) {
  if (!tz || typeof tz !== 'string' || tz.length > 64) return 'UTC';
  if (tz !== 'UTC' && !/^[A-Za-z]+(\/[A-Za-z0-9_\-]+)+$/.test(tz)) return 'UTC';
  if (pgZones && !pgZones.has(tz)) return 'UTC';
  try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return tz; } catch { return 'UTC'; }
}

function hostOf(url) {
  try { return new URL(url).hostname.toLowerCase().replace(/^www\./, ''); } catch { return null; }
}
function ownHosts() {
  const hosts = new Set(['theguide.company', 'localhost']);
  const app = hostOf(process.env.APP_URL || '');
  if (app) hosts.add(app);
  return hosts;
}

// ---------------------------------------------------------------- classification
// Fixed channel list. The dashboards colour each channel by its position here,
// so the order matters — keep it stable.
const CHANNELS = ['Paid Search', 'Paid Social', 'Organic Search', 'Organic Social',
  'Creators & Affiliates', 'Referral', 'Direct', 'Email', 'Other'];

// Ad-platform click IDs. These are added automatically by the ad platform,
// so they identify paid traffic even when nobody set up UTM tags.
const CLICK_IDS = [
  ['gclid', 'Google Ads', 'Paid Search', 'cpc'],
  ['gbraid', 'Google Ads', 'Paid Search', 'cpc'],
  ['wbraid', 'Google Ads', 'Paid Search', 'cpc'],
  ['gad_source', 'Google Ads', 'Paid Search', 'cpc'],
  ['msclkid', 'Microsoft Ads', 'Paid Search', 'cpc'],
  ['ttclid', 'TikTok Ads', 'Paid Social', 'paid_social'],
  ['twclid', 'X Ads', 'Paid Social', 'paid_social'],
  ['li_fat_id', 'LinkedIn Ads', 'Paid Social', 'paid_social'],
  ['sccid', 'Snapchat Ads', 'Paid Social', 'paid_social'],
  ['epik', 'Pinterest Ads', 'Paid Social', 'paid_social'],
  ['rdt_cid', 'Reddit Ads', 'Paid Social', 'paid_social'],
  ['dclid', 'Google Display', 'Other', 'display'],
];

// [pattern, display name]. A pattern ending in "." matches any TLD
// (pinterest.com, pinterest.co.uk...); a leading "^" means the host must start
// with it (so google.com counts, but mail.google.com doesn't). Otherwise it
// matches the host or any subdomain. Android apps send "android-app://<id>".
const AI_HOSTS = [['chatgpt.com', 'ChatGPT'], ['chat.openai.com', 'ChatGPT'], ['openai.com', 'ChatGPT'],
  ['perplexity.ai', 'Perplexity'], ['claude.ai', 'Claude'], ['gemini.google.com', 'Gemini'],
  ['copilot.microsoft.com', 'Copilot'], ['you.com', 'You.com'], ['deepseek.com', 'DeepSeek']];
const SEARCH_HOSTS = [['^google.', 'Google'], ['com.google.android.googlequicksearchbox', 'Google'], ['bing.com', 'Bing'], ['duckduckgo.com', 'DuckDuckGo'],
  ['search.yahoo.', 'Yahoo'], ['yahoo.com', 'Yahoo'], ['ecosia.org', 'Ecosia'], ['search.brave.com', 'Brave'],
  ['baidu.com', 'Baidu'], ['yandex.', 'Yandex'], ['startpage.com', 'Startpage'], ['qwant.com', 'Qwant'], ['naver.com', 'Naver']];
const SOCIAL_HOSTS = [['instagram.com', 'Instagram'], ['facebook.com', 'Facebook'], ['fb.com', 'Facebook'],
  ['fb.me', 'Facebook'], ['messenger.com', 'Facebook'], ['t.co', 'X (Twitter)'], ['twitter.com', 'X (Twitter)'],
  ['x.com', 'X (Twitter)'], ['tiktok.com', 'TikTok'], ['youtube.com', 'YouTube'], ['youtu.be', 'YouTube'],
  ['reddit.com', 'Reddit'], ['linkedin.com', 'LinkedIn'], ['lnkd.in', 'LinkedIn'], ['pinterest.', 'Pinterest'],
  ['pin.it', 'Pinterest'], ['snapchat.com', 'Snapchat'], ['threads.net', 'Threads'], ['threads.com', 'Threads'],
  ['discord.com', 'Discord'], ['discord.gg', 'Discord'], ['whatsapp.com', 'WhatsApp'], ['wa.me', 'WhatsApp'],
  ['t.me', 'Telegram'], ['telegram.org', 'Telegram'], ['quora.com', 'Quora'], ['twitch.tv', 'Twitch'],
  ['tumblr.com', 'Tumblr'], ['linktr.ee', 'Linktree'], ['beacons.ai', 'Beacons'], ['stan.store', 'Stan'],
  ['bsky.app', 'Bluesky'], ['com.instagram.android', 'Instagram'], ['com.zhiliaoapp.musically', 'TikTok'],
  ['com.ss.android.ugc.trill', 'TikTok'], ['com.facebook.katana', 'Facebook'], ['com.facebook.orca', 'Facebook'],
  ['com.twitter.android', 'X (Twitter)'], ['com.linkedin.android', 'LinkedIn'], ['com.reddit.frontpage', 'Reddit'],
  ['com.snapchat.android', 'Snapchat'], ['com.pinterest', 'Pinterest'], ['com.google.android.youtube', 'YouTube']];
const EMAIL_HOSTS = [['mail.google.com', 'Gmail'], ['com.google.android.gm', 'Gmail'], ['inbox.google.com', 'Gmail'],
  ['mail.aol.com', 'AOL Mail'], ['mail.zoho.com', 'Zoho Mail'], ['icloud.com', 'iCloud Mail'], ['outlook.live.com', 'Outlook'], ['outlook.office.com', 'Outlook'],
  ['outlook.office365.com', 'Outlook'], ['mail.yahoo.com', 'Yahoo Mail'], ['mail.proton.me', 'Proton Mail']];

function matchHost(host, list) {
  if (!host) return null;
  for (const [pat, name] of list) {
    const anchored = pat.startsWith('^');
    const p = anchored ? pat.slice(1) : pat;
    let hit;
    if (p.endsWith('.')) hit = new RegExp((anchored ? '^' : '(^|\\.)') + p.replace(/\./g, '\\.') + '[a-z.]+$').test(host);
    else hit = host === p || (!anchored && host.endsWith('.' + p));
    if (hit) return name;
  }
  return null;
}

// Friendly names for common hand-typed utm_source values.
const SOURCE_ALIASES = {
  ig: 'Instagram', insta: 'Instagram', instagram: 'Instagram', fb: 'Facebook', facebook: 'Facebook', meta: 'Meta',
  tt: 'TikTok', tiktok: 'TikTok', yt: 'YouTube', youtube: 'YouTube', x: 'X (Twitter)', twitter: 'X (Twitter)',
  google: 'Google', googleads: 'Google Ads', google_ads: 'Google Ads', adwords: 'Google Ads', bing: 'Bing',
  reddit: 'Reddit', linkedin: 'LinkedIn', snapchat: 'Snapchat', snap: 'Snapchat', pinterest: 'Pinterest',
  threads: 'Threads', newsletter: 'Newsletter', email: 'Email', chatgpt: 'ChatGPT',
};
const SOCIAL_NAMES = new Set(['Instagram', 'Facebook', 'Meta', 'TikTok', 'YouTube', 'X (Twitter)', 'Reddit', 'LinkedIn',
  'Snapchat', 'Pinterest', 'Threads', 'Discord', 'WhatsApp', 'Telegram', 'Twitch', 'Bluesky', 'Linktree']);
const SEARCH_NAMES = new Set(['Google', 'Google Ads', 'Bing', 'DuckDuckGo', 'Yahoo', 'Ecosia', 'Brave', 'Baidu', 'Yandex']);

function prettySource(raw) {
  const k = String(raw || '').trim().toLowerCase().replace(/^www\./, '');
  if (!k) return null;
  if (Object.prototype.hasOwnProperty.call(SOURCE_ALIASES, k)) return SOURCE_ALIASES[k];
  const fromHost = matchHost(k, SOCIAL_HOSTS) || matchHost(k, SEARCH_HOSTS) || matchHost(k, AI_HOSTS);
  if (fromHost) return fromHost;
  return String(raw).trim().slice(0, 80);
}

// In-app browsers often strip the referrer, which would otherwise make
// Instagram/TikTok traffic look "Direct". Their user agents give it away.
function inAppSource(ua) {
  if (/Instagram/.test(ua)) return 'Instagram';
  if (/BytedanceWebview|musical_ly|TikTok/i.test(ua)) return 'TikTok';
  if (/FBAN|FBAV|FB_IAB|FBIOS/.test(ua)) return 'Facebook';
  if (/Snapchat/i.test(ua)) return 'Snapchat';
  if (/LinkedInApp/.test(ua)) return 'LinkedIn';
  if (/Pinterest/i.test(ua)) return 'Pinterest';
  if (/\bThreads\b|Barcelona/.test(ua)) return 'Threads';
  return null;
}

/**
 * touch: { src, med, cmp, trm, cnt, ck: {gclid: '...'}, ref: 'https://...', rc: 'REFCODE' }
 * Returns the traffic source this visit is credited to.
 */
function classify(touch, ua) {
  touch = touch || {};
  const utm = {
    source: s(touch.src, 120), medium: s(touch.med, 80), campaign: s(touch.cmp, 150),
    term: s(touch.trm, 150), content: s(touch.cnt, 150),
  };
  const ck = touch.ck && typeof touch.ck === 'object' ? touch.ck : {};
  const refHost = hostOf(touch.ref || '');
  const internal = refHost && (ownHosts().has(refHost) || /(^|\.)stripe\.com$/.test(refHost) || /(^|\.)netlify\.app$/.test(refHost));
  const referrer = internal ? null : refHost;
  const base = { campaign: utm.campaign, term: utm.term, content: utm.content, clickId: null, referrer };

  // 1. Paid click IDs — the most reliable signal there is.
  for (const [key, name, channel, medium] of CLICK_IDS) {
    if (ck[key]) {
      return { ...base, channel, source: name, medium: utm.medium || medium, clickId: key };
    }
  }

  // 2. UTM tags.
  if (utm.source || utm.medium) {
    const src = prettySource(utm.source) || (referrer ? prettySource(referrer) : null) || 'Unknown';
    const m = (utm.medium || '').toLowerCase();
    const social = SOCIAL_NAMES.has(src) || /social|tiktok|facebook|instagram/.test((utm.source || '').toLowerCase());
    const search = SEARCH_NAMES.has(src);
    let channel;
    if (/^(cpc|ppc|paid[-_ ]?search|paidsearch|sem|search[-_ ]?ads?)$/.test(m)) channel = social ? 'Paid Social' : 'Paid Search';
    else if (/^(paid[-_ ]?social|social[-_ ]?paid|paidsocial|social[-_ ]?ads?)$/.test(m)) channel = 'Paid Social';
    else if (/^(paid|ads?|cpm|cpv|cpa|retargeting|sponsored)$/.test(m)) channel = search ? 'Paid Search' : (social ? 'Paid Social' : 'Other');
    else if (/^(display|banner|programmatic|native)$/.test(m)) channel = 'Other';
    else if (/e-?mail|newsletter/.test(m)) channel = 'Email';
    else if (/affiliate|partner|influencer|creator|ugc|sponsor|ambassador/.test(m)) channel = 'Creators & Affiliates';
    else if (/^(social|social[-_ ]?network|social[-_ ]?media|organic[-_ ]?social|sm|bio|link[-_ ]?in[-_ ]?bio|story|stories|post|reel|reels|video|dm)$/.test(m)) channel = 'Organic Social';
    else if (/^(organic|seo|organic[-_ ]?search)$/.test(m)) channel = 'Organic Search';
    else if (/^(referral|link|links|blog|pr|press|website|web|partner[-_ ]?site)$/.test(m)) channel = 'Referral';
    else if (!m) channel = social ? 'Organic Social' : search ? 'Organic Search' : (/mail|newsletter/i.test(utm.source || '') ? 'Email' : 'Referral');
    else channel = social ? 'Organic Social' : 'Other';
    return { ...base, channel, source: src, medium: utm.medium };
  }

  // 3. The app's own invite links (?ref=CODE).
  if (touch.rc) return { ...base, channel: 'Creators & Affiliates', source: 'Invite link', medium: 'referral' };

  // 4. Referring site.
  if (referrer) {
    const mail = matchHost(referrer, EMAIL_HOSTS);
    if (mail) return { ...base, channel: 'Email', source: mail, medium: 'email' };
    const ai = matchHost(referrer, AI_HOSTS);
    if (ai) return { ...base, channel: 'Referral', source: ai, medium: 'ai-assistant' };
    const search = matchHost(referrer, SEARCH_HOSTS);
    if (search) return { ...base, channel: 'Organic Search', source: search, medium: 'organic' };
    const social = matchHost(referrer, SOCIAL_HOSTS);
    if (social) return { ...base, channel: 'Organic Social', source: social, medium: 'social' };
    return { ...base, channel: 'Referral', source: referrer, medium: 'referral' };
  }

  // 5. In-app browsers that hide the referrer, and Meta's fbclid on organic links.
  const app = inAppSource(ua || '');
  if (app) return { ...base, channel: 'Organic Social', source: app, medium: 'social' };
  if (ck.fbclid) return { ...base, channel: 'Organic Social', source: 'Facebook / Instagram', medium: 'social' };

  return { ...base, channel: 'Direct', source: 'Direct', medium: null };
}

// ---------------------------------------------------------------- devices & places
const BOT_RE = /bot\b|bot\/|crawl|spider|slurp|headless|lighthouse|pagespeed|facebookexternalhit|embedly|quora link|vkshare|skypeuripreview|whatsapp\/|telegrambot|discordbot|curl\/|wget\/|python-requests|python-urllib|axios\/|node-fetch|go-http|okhttp|preview/i;
function isBot(ua) { return !ua || BOT_RE.test(ua); }

function parseUA(ua, touchScreen) {
  ua = ua || '';
  let device = /iPad|Tablet|PlayBook|Silk|Android(?!.*Mobile)/i.test(ua) ? 'Tablet'
    : /Mobi|iPhone|iPod|Android|Windows Phone/i.test(ua) ? 'Mobile' : 'Desktop';
  if (device === 'Desktop' && /Macintosh/.test(ua) && touchScreen) device = 'Tablet'; // iPadOS reports as a Mac
  const browser = /Instagram/.test(ua) ? 'Instagram app'
    : /FBAN|FBAV|FB_IAB|FBIOS/.test(ua) ? 'Facebook app'
    : /BytedanceWebview|musical_ly|TikTok/i.test(ua) ? 'TikTok app'
    : /Snapchat/i.test(ua) ? 'Snapchat app'
    : /LinkedInApp/.test(ua) ? 'LinkedIn app'
    : /Edg(A|iOS)?\//.test(ua) ? 'Edge'
    : /OPR\/|Opera/.test(ua) ? 'Opera'
    : /SamsungBrowser/.test(ua) ? 'Samsung Internet'
    : /CriOS|Chrome\//.test(ua) ? 'Chrome'
    : /FxiOS|Firefox\//.test(ua) ? 'Firefox'
    : /Safari\//.test(ua) ? 'Safari' : 'Other';
  const os = /iPhone|iPad|iPod/.test(ua) ? 'iOS' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows'
    : (/Macintosh|Mac OS X/.test(ua) ? (touchScreen ? 'iPadOS' : 'macOS') : /CrOS/.test(ua) ? 'ChromeOS' : /Linux/.test(ua) ? 'Linux' : 'Other');
  return { device, browser, os };
}

// Rough country from the browser's time zone (no IP lookups, nothing stored
// about the person). Good enough for "where in the world is traffic from".
const TZ_COUNTRY = (() => {
  const m = {};
  const add = (cc, list) => list.split(' ').forEach(z => { m[z] = cc; });
  add('US', 'America/New_York America/Chicago America/Denver America/Los_Angeles America/Phoenix America/Anchorage America/Detroit America/Boise America/Indiana/Indianapolis America/Kentucky/Louisville America/Adak Pacific/Honolulu US/Eastern US/Central US/Mountain US/Pacific America/Indianapolis America/Juneau America/Menominee');
  add('CA', 'America/Toronto America/Vancouver America/Edmonton America/Winnipeg America/Halifax America/Regina America/St_Johns America/Montreal America/Moncton');
  add('MX', 'America/Mexico_City America/Monterrey America/Tijuana America/Cancun America/Merida America/Chihuahua America/Hermosillo America/Mazatlan');
  add('BR', 'America/Sao_Paulo America/Fortaleza America/Recife America/Manaus America/Bahia America/Belem');
  add('AR', 'America/Argentina/Buenos_Aires America/Buenos_Aires'); add('CO', 'America/Bogota'); add('PE', 'America/Lima');
  add('CL', 'America/Santiago'); add('VE', 'America/Caracas'); add('DO', 'America/Santo_Domingo'); add('PR', 'America/Puerto_Rico');
  add('JM', 'America/Jamaica'); add('GT', 'America/Guatemala'); add('EC', 'America/Guayaquil'); add('PA', 'America/Panama'); add('CR', 'America/Costa_Rica');
  add('GB', 'Europe/London'); add('IE', 'Europe/Dublin'); add('FR', 'Europe/Paris'); add('DE', 'Europe/Berlin'); add('ES', 'Europe/Madrid Atlantic/Canary');
  add('IT', 'Europe/Rome'); add('NL', 'Europe/Amsterdam'); add('BE', 'Europe/Brussels'); add('CH', 'Europe/Zurich'); add('AT', 'Europe/Vienna');
  add('SE', 'Europe/Stockholm'); add('NO', 'Europe/Oslo'); add('DK', 'Europe/Copenhagen'); add('FI', 'Europe/Helsinki'); add('PL', 'Europe/Warsaw');
  add('CZ', 'Europe/Prague'); add('PT', 'Europe/Lisbon'); add('GR', 'Europe/Athens'); add('TR', 'Europe/Istanbul'); add('UA', 'Europe/Kiev Europe/Kyiv');
  add('RU', 'Europe/Moscow'); add('RO', 'Europe/Bucharest'); add('HU', 'Europe/Budapest'); add('RS', 'Europe/Belgrade');
  add('NG', 'Africa/Lagos'); add('ZA', 'Africa/Johannesburg'); add('KE', 'Africa/Nairobi'); add('EG', 'Africa/Cairo'); add('GH', 'Africa/Accra'); add('MA', 'Africa/Casablanca');
  add('IN', 'Asia/Kolkata Asia/Calcutta'); add('AE', 'Asia/Dubai'); add('PK', 'Asia/Karachi'); add('BD', 'Asia/Dhaka'); add('PH', 'Asia/Manila');
  add('SG', 'Asia/Singapore'); add('ID', 'Asia/Jakarta'); add('TH', 'Asia/Bangkok'); add('VN', 'Asia/Ho_Chi_Minh Asia/Saigon'); add('MY', 'Asia/Kuala_Lumpur');
  add('HK', 'Asia/Hong_Kong'); add('CN', 'Asia/Shanghai'); add('JP', 'Asia/Tokyo'); add('KR', 'Asia/Seoul'); add('TW', 'Asia/Taipei');
  add('SA', 'Asia/Riyadh'); add('IL', 'Asia/Jerusalem Asia/Tel_Aviv'); add('QA', 'Asia/Qatar'); add('KW', 'Asia/Kuwait');
  add('AU', 'Australia/Sydney Australia/Melbourne Australia/Brisbane Australia/Perth Australia/Adelaide Australia/Hobart Australia/Darwin');
  add('NZ', 'Pacific/Auckland');
  return m;
})();
function countryFromTz(tz) { return TZ_COUNTRY[tz] || null; }

// ---------------------------------------------------------------- live presence (in memory)
const presence = new Map(); // visitorId -> { sessionId, userId, path, channel, source, device, country, lastSeen }
const ONLINE_MS = 45 * 1000;
function touchPresence(visitorId, data) {
  const prev = presence.get(visitorId) || {};
  presence.set(visitorId, { ...prev, ...data, lastSeen: Date.now() });
  if (presence.size > 50000) prunePresence();
}
function leavePresence(visitorId) { presence.delete(visitorId); }
function prunePresence() {
  const cutoff = Date.now() - ONLINE_MS;
  for (const [k, v] of presence) if (v.lastSeen < cutoff) presence.delete(k);
}
function presenceSummary() {
  prunePresence();
  const tally = (key) => {
    const m = {};
    for (const v of presence.values()) { const k = v[key] || 'Unknown'; m[k] = (m[k] || 0) + 1; }
    return Object.entries(m).map(([name, n]) => ({ name, n })).sort((a, b) => b.n - a.n);
  };
  let signedIn = 0;
  for (const v of presence.values()) if (v.userId) signedIn++;
  return {
    total: presence.size, signedIn,
    byChannel: tally('channel'), byPath: tally('path').slice(0, 8), byDevice: tally('device'),
    byCountry: tally('country').slice(0, 6),
  };
}

// ---------------------------------------------------------------- live bus
const bus = new EventEmitter();
bus.setMaxListeners(200);
const feed = []; // newest first, last 40 interesting events
let feedLoaded = false;
function pushFeed(item) {
  if (item.id && feed.some(f => f.id === item.id)) return; // e.g. a webhook Stripe re-sent
  feed.unshift(item);
  if (feed.length > 40) feed.length = 40;
  bus.emit('event', item);
}
function feedItemFromRow(r) {
  return {
    id: r.id || null, type: r.type === 'pageview' ? 'visit' : r.type, ts: r.ts || Date.now(), channel: r.channel, source: r.source,
    campaign: r.campaign || null, path: r.path || r.landing || null, device: r.device || null, country: r.country || null,
    value: r.value ?? null, plan: r.meta && r.meta.plan ? r.meta.plan : null, email: r.email || null,
  };
}
async function loadFeed() {
  if (feedLoaded || !ready) return;
  feedLoaded = true;
  try {
    const rows = await prisma.$queryRawUnsafe(
      `SELECT e.id, e.type, e.channel, e.source, e.campaign, e.path, e.landing, e.device, e.country, e.value, e.meta,
              EXTRACT(EPOCH FROM e."createdAt")::float8 * 1000 AS ts, u.email
         FROM "AnalyticsEvent" e LEFT JOIN "User" u ON u.id = e."userId"
        WHERE e.type IN ('visit','signup','purchase','renewal','cancel','checkout')
        ORDER BY e."createdAt" DESC LIMIT 40`);
    const items = rows.map(feedItemFromRow);
    // keep anything that streamed in while this query ran
    const merged = [...feed, ...items].sort((a, b) => b.ts - a.ts).slice(0, 40);
    feed.length = 0; feed.push(...merged);
  } catch (err) { console.error('Analytics feed load failed:', err.message); }
}

// ---------------------------------------------------------------- writes (batched)
const COLS = ['id', 'type', 'visitorId', 'sessionId', 'userId', 'path', 'channel', 'source', 'medium', 'campaign', 'term',
  'content', 'clickId', 'referrer', 'landing', 'device', 'browser', 'os', 'country', 'value', 'meta', 'createdAt'];
let queue = [];
let flushTimer = null;
let flushing = false;

function enqueue(row) {
  if (queue.length > 20000) queue.shift(); // never let a DB outage eat all memory
  queue.push(row);
  if (queue.length >= 250) flush();
  else if (!flushTimer) flushTimer = setTimeout(flush, 800);
}
function rowPlaceholders(r, params) {
  const ph = COLS.map(c => {
    if (c === 'meta') { params.push(r.meta ? JSON.stringify(r.meta) : null); return `$${params.length}::jsonb`; }
    if (c === 'value') { params.push(r.value ?? null); return `$${params.length}::float8`; }
    if (c === 'createdAt') { params.push(r.createdAt); return `$${params.length}::timestamp`; }
    params.push(r[c] ?? null); return `$${params.length}::text`;
  });
  return `(${ph.join(',')})`;
}
function insertRows(values, params) {
  return prisma.$executeRawUnsafe(
    `INSERT INTO "AnalyticsEvent" (${COLS.map(c => `"${c}"`).join(',')}) VALUES ${values.join(',')} ON CONFLICT ("id") DO NOTHING`,
    ...params);
}

async function flush() {
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
  if (flushing || !queue.length) return;
  if (!ready) { flushTimer = setTimeout(flush, 5000); return; }
  flushing = true;
  const rows = queue.splice(0, 250);
  const params = [];
  const values = rows.map(r => rowPlaceholders(r, params));
  try {
    await insertRows(values, params);
  } catch (err) {
    console.error('Analytics flush failed:', err.message);
    // One malformed row shouldn't cost the whole batch: retry individually.
    if (rows.length > 1) {
      for (const r of rows) {
        const p1 = [];
        const v1 = rowPlaceholders(r, p1);
        await insertRows([v1], p1).catch(() => {});
      }
    }
  } finally {
    flushing = false;
    if (queue.length) setImmediate(flush);
  }
}

/** Records one event. ctx = { visitorId, sessionId, userId, path, touch, ua, touchScreen, tz, landing, value, meta, email } */
function recordEvent(type, ctx) {
  try {
    const cls = ctx.cls || classify(ctx.touch, ctx.ua);
    const dev = ctx.ua ? parseUA(ctx.ua, ctx.touchScreen) : { device: ctx.device || null, browser: null, os: null };
    const row = {
      id: s(ctx.id, 80) || uuid(), type, visitorId: s(ctx.visitorId, 64) || 'server', sessionId: s(ctx.sessionId, 64) || 'server',
      userId: s(ctx.userId, 64), path: s(ctx.path, 200), channel: cls.channel, source: s(cls.source, 120) || 'Direct',
      medium: s(cls.medium, 80), campaign: s(cls.campaign, 150), term: s(cls.term, 150), content: s(cls.content, 150),
      clickId: s(cls.clickId, 20), referrer: s(cls.referrer, 120), landing: s(ctx.landing, 200),
      device: dev.device, browser: dev.browser, os: dev.os, country: ctx.country || countryFromTz(ctx.tz),
      value: typeof ctx.value === 'number' && isFinite(ctx.value) ? ctx.value : null,
      meta: ctx.meta || null, createdAt: nowUtcLiteral(),
    };
    enqueue(row);
    // Live dashboards: arrivals, signups and money moves go to the feed;
    // ordinary page views just tick the counters.
    if (type === 'pageview' && ctx.newSession) {
      enqueue({ ...row, id: uuid(), type: 'visit' });
      pushFeed(feedItemFromRow({ ...row, type: 'visit', ts: Date.now() }));
    } else if (type !== 'pageview') {
      pushFeed(feedItemFromRow({ ...row, ts: Date.now(), email: ctx.email || null }));
    } else {
      bus.emit('pv', { ts: Date.now() });
    }
    return row;
  } catch (err) {
    console.error('Analytics recordEvent failed:', err.message);
    return null;
  }
}

// Saves where a new user came from (first touch + the touch that converted)
// and drops a "signup" event on the live feed.
async function recordSignup(user, body, req) {
  try {
    if (isStaffEmail(user.email)) return;
    const a = body && typeof body.attribution === 'object' && body.attribution ? body.attribution : {};
    const ua = req.get('user-agent') || '';
    const first = classify(a.first || a.last || {}, ua);
    const last = classify(a.last || a.first || {}, ua);
    const dev = parseUA(ua, !!a.touch);
    const tz = validTz(a.tz);
    const country = countryFromTz(tz);
    const firstSeen = Number(a.firstSeen) > 1.5e12 && Number(a.firstSeen) <= Date.now() + 60000
      ? new Date(Number(a.firstSeen)).toISOString().replace('T', ' ').replace('Z', '') : null;
    if (ready) {
      await prisma.$executeRawUnsafe(
        `INSERT INTO "UserAttribution" ("id","userId","channel","source","medium","campaign","term","content","clickId",
           "referrer","landing","device","country","firstSeenAt","lastChannel","lastSource","lastCampaign","createdAt")
         VALUES ($1::text,$2::text,$3::text,$4::text,$5::text,$6::text,$7::text,$8::text,$9::text,$10::text,$11::text,$12::text,
           $13::text,$14::timestamp,$15::text,$16::text,$17::text,$18::timestamp)
         ON CONFLICT ("userId") DO NOTHING`,
        uuid(), user.id, first.channel, s(first.source, 120) || 'Direct', s(first.medium, 80), s(first.campaign, 150),
        s(first.term, 150), s(first.content, 150), s(first.clickId, 20), s(first.referrer, 120), s(a.firstLanding || a.landing, 200),
        dev.device, country, firstSeen, last.channel, s(last.source, 120), s(last.campaign, 150), nowUtcLiteral());
    }
    recordEvent('signup', {
      cls: first, visitorId: a.v, sessionId: a.s, userId: user.id, path: '/signup', ua, touchScreen: !!a.touch, tz,
      landing: s(a.firstLanding || a.landing, 200), email: user.email,
    });
  } catch (err) {
    console.error('Analytics recordSignup failed:', err.message);
  }
}

// Money events from the Stripe webhook, credited to the channel that
// originally brought the user in.
async function recordMoney(type, userId, { value, plan, email, id } = {}) {
  try {
    if (!userId) return;
    let cls = { channel: 'Direct', source: 'Direct', medium: null, campaign: null };
    let mail = email || null;
    if (ready) {
      const rows = await prisma.$queryRawUnsafe(
        `SELECT a.channel, a.source, a.medium, a.campaign, a.device, a.country, u.email
           FROM "User" u LEFT JOIN "UserAttribution" a ON a."userId" = u.id WHERE u.id = $1::text`, userId);
      if (rows[0]) {
        if (isStaffEmail(rows[0].email)) return;
        mail = mail || rows[0].email;
        if (rows[0].channel) cls = { channel: rows[0].channel, source: rows[0].source, medium: rows[0].medium, campaign: rows[0].campaign };
        recordEvent(type, { id, cls, userId, value, meta: plan ? { plan } : null, email: mail, device: rows[0].device, country: rows[0].country });
        return;
      }
    }
    recordEvent(type, { id, cls, userId, value, meta: plan ? { plan } : null, email: mail });
  } catch (err) {
    console.error('Analytics recordMoney failed:', err.message);
  }
}

// ---------------------------------------------------------------- query helpers
// Dashboards fire many small aggregate queries. Cap how many run at once so
// they can never hog the connection pool that signups, logins and the Stripe
// webhook share.
const MAX_PARALLEL = 4;
let running = 0;
const waiting = [];
function q(sql, ...params) {
  return new Promise((resolve, reject) => {
    const go = () => {
      running++;
      prisma.$queryRawUnsafe(sql, ...params).then(resolve, reject).finally(() => {
        running--;
        const next = waiting.shift();
        if (next) next();
      });
    };
    if (running < MAX_PARALLEL) go(); else waiting.push(go);
  });
}
// SQL snippets. $1 is always the viewer's time zone.
const LOCAL = col => `((${col} AT TIME ZONE 'UTC') AT TIME ZONE $1::text)`;
const DAY_START = days => `((date_trunc('day', now() AT TIME ZONE $1::text) - interval '${Number(days) | 0} days') AT TIME ZONE $1::text AT TIME ZONE 'UTC')`;
const NOW_UTC = `(now() AT TIME ZONE 'UTC')`;
const AGO = (n, unit) => `(${NOW_UTC} - interval '${Number(n) | 0} ${unit}')`;

function cached(store, key, ttlMs, fn) {
  const hit = store.get(key);
  if (hit && Date.now() - hit.at < ttlMs) return hit.promise;
  const promise = fn().catch(err => { store.delete(key); throw err; });
  store.set(key, { at: Date.now(), promise });
  if (store.size > 100) store.delete(store.keys().next().value);
  return promise;
}

// ---------------------------------------------------------------- live snapshot
const snapCache = new Map();
const totalsCache = new Map();

async function ownerTotals() {
  return cached(totalsCache, 'totals', 10000, async () => {
    const staff = staffEmails();
    const [r] = await q(
      `SELECT COUNT(*)::int AS "totalUsers",
              COUNT(*) FILTER (WHERE "isPro")::int AS "proUsers",
              COUNT(*) FILTER (WHERE "isPro" AND "planType" = 'monthly')::int AS "monthly",
              COUNT(*) FILTER (WHERE "isPro" AND "planType" = 'yearly')::int AS "yearly"
         FROM "User" WHERE lower(email) <> ALL($1::text[])`, staff);
    const mrr = r.monthly * PRICES.monthly + r.yearly * PRICES.yearly / 12;
    return { ...r, mrr: Math.round(mrr * 100) / 100 };
  });
}

const PRICES = { monthly: 28.99, yearly: 325.99 };

async function liveSnapshot(tz, role) {
  tz = validTz(tz);
  await loadFeed();
  const base = await cached(snapCache, tz, 1500, async () => {
    const staff = staffEmails();
    const [[ev], [users], perMin] = await Promise.all([
      q(`SELECT COUNT(DISTINCT "visitorId") FILTER (WHERE type = 'pageview')::int AS visitors,
                COUNT(DISTINCT "sessionId") FILTER (WHERE type = 'pageview')::int AS sessions,
                COUNT(*) FILTER (WHERE type = 'pageview')::int AS pageviews,
                COUNT(*) FILTER (WHERE type = 'purchase')::int AS "newPro",
                COUNT(*) FILTER (WHERE type = 'checkout')::int AS checkouts,
                COALESCE(SUM(value) FILTER (WHERE type IN ('purchase','renewal')), 0)::float8 AS revenue
           FROM "AnalyticsEvent" WHERE "createdAt" >= ${DAY_START(0)}`, tz),
      q(`SELECT COUNT(*)::int AS signups FROM "User"
          WHERE "createdAt" >= ${DAY_START(0)} AND lower(email) <> ALL($2::text[])`, tz, staff),
      q(`SELECT (EXTRACT(EPOCH FROM date_trunc('minute', "createdAt")) * 1000)::float8 AS t, COUNT(*)::int AS n
           FROM "AnalyticsEvent" WHERE type = 'pageview' AND "createdAt" >= ${AGO(30, 'minutes')}
          GROUP BY 1 ORDER BY 1`),
    ]);
    // 30 one-minute buckets, oldest first, zero-filled
    const nowMin = Math.floor(Date.now() / 60000) * 60000;
    const m = new Map(perMin.map(r => [Math.round(r.t), r.n]));
    const minutes = [];
    for (let i = 29; i >= 0; i--) { const t = nowMin - i * 60000; minutes.push({ t, n: m.get(t) || 0 }); }
    return { today: { ...ev, signups: users.signups }, minutes };
  });
  const snap = {
    at: Date.now(), tz, online: presenceSummary(), today: { ...base.today }, minutes: base.minutes,
    feed: feed.slice(0, 25).map(f => scrubFor(role, f)),
  };
  if (role.owner) snap.totals = await ownerTotals();
  return snap;
}

// Marketing sees everything except people's emails.
function scrubFor(role, item) {
  if (role.owner) return item;
  const { email, ...rest } = item;
  return rest;
}

// ---------------------------------------------------------------- owner overview
const overviewCache = new Map();
async function ownerOverview(tz) {
  tz = validTz(tz);
  return cached(overviewCache, tz, 15000, async () => {
    const staff = staffEmails();
    const notStaff = `lower(u.email) <> ALL($2::text[])`;
    const notStaff1 = `lower(u.email) <> ALL($1::text[])`;
    const [
      [u], signupsDaily, revenueDaily, visitorsDaily, [active], [engage], chapters, chapterViews,
      recent, channels, [money], community,
    ] = await Promise.all([
      q(`SELECT COUNT(*)::int AS "totalUsers",
                COUNT(*) FILTER (WHERE "isPro")::int AS "proUsers",
                COUNT(*) FILTER (WHERE "isPro" AND "planType" = 'monthly')::int AS "monthlyUsers",
                COUNT(*) FILTER (WHERE "isPro" AND "planType" = 'yearly')::int AS "yearlyUsers",
                COUNT(*) FILTER (WHERE "createdAt" >= ${DAY_START(0)})::int AS "signupsToday",
                COUNT(*) FILTER (WHERE "createdAt" >= ${DAY_START(6)})::int AS "signups7",
                COUNT(*) FILTER (WHERE "createdAt" >= ${DAY_START(29)})::int AS "signups30",
                COUNT(*) FILTER (WHERE "createdAt" >= ${DAY_START(59)} AND "createdAt" < ${DAY_START(29)})::int AS "signupsPrev30"
           FROM "User" u WHERE ${notStaff}`, tz, staff),
      q(`SELECT to_char(${LOCAL('u."createdAt"')}, 'YYYY-MM-DD') AS d, COUNT(*)::int AS n
           FROM "User" u WHERE u."createdAt" >= ${DAY_START(29)} AND ${notStaff} GROUP BY 1`, tz, staff),
      q(`SELECT to_char(${LOCAL('"createdAt"')}, 'YYYY-MM-DD') AS d, COALESCE(SUM(value), 0)::float8 AS n
           FROM "AnalyticsEvent" WHERE type IN ('purchase','renewal') AND "createdAt" >= ${DAY_START(29)} GROUP BY 1`, tz),
      q(`SELECT to_char(${LOCAL('"createdAt"')}, 'YYYY-MM-DD') AS d, COUNT(DISTINCT "visitorId")::int AS n
           FROM "AnalyticsEvent" WHERE type = 'pageview' AND "createdAt" >= ${DAY_START(29)} GROUP BY 1`, tz),
      q(`SELECT
           (SELECT COUNT(*)::int FROM (SELECT u.id FROM "User" u WHERE u."updatedAt" >= ${DAY_START(0)} AND ${notStaff}
              UNION SELECT e."userId" FROM "AnalyticsEvent" e WHERE e."userId" IS NOT NULL AND e."createdAt" >= ${DAY_START(0)}) x) AS dau,
           (SELECT COUNT(*)::int FROM (SELECT u.id FROM "User" u WHERE u."updatedAt" >= ${DAY_START(6)} AND ${notStaff}
              UNION SELECT e."userId" FROM "AnalyticsEvent" e WHERE e."userId" IS NOT NULL AND e."createdAt" >= ${DAY_START(6)}) x) AS wau,
           (SELECT COUNT(*)::int FROM (SELECT u.id FROM "User" u WHERE u."updatedAt" >= ${DAY_START(29)} AND ${notStaff}
              UNION SELECT e."userId" FROM "AnalyticsEvent" e WHERE e."userId" IS NOT NULL AND e."createdAt" >= ${DAY_START(29)}) x) AS mau`, tz, staff),
      q(`SELECT COALESCE(AVG(CASE WHEN jsonb_typeof(u."dataBlob"->'streak'->'count') = 'number' THEN (u."dataBlob"->'streak'->>'count')::float8 ELSE 0 END), 0)::float8 AS "avgStreak",
                COALESCE(MAX(CASE WHEN jsonb_typeof(u."dataBlob"->'streak'->'count') = 'number' THEN (u."dataBlob"->'streak'->>'count')::float8 ELSE 0 END), 0)::float8 AS "maxStreak",
                COALESCE(SUM(CASE WHEN jsonb_typeof(u."dataBlob"->'completed') = 'array' THEN jsonb_array_length(u."dataBlob"->'completed') ELSE 0 END), 0)::float8 AS "totalCompleted"
           FROM "User" u WHERE ${notStaff1}`, staff),
      q(`SELECT n AS "nicheId", COUNT(*)::int AS count
           FROM "User" u, jsonb_array_elements_text(CASE WHEN jsonb_typeof(u."dataBlob"->'niches') = 'array' THEN u."dataBlob"->'niches' ELSE '[]'::jsonb END) AS n
          WHERE ${notStaff1} GROUP BY n ORDER BY 2 DESC LIMIT 8`, staff),
      q(`SELECT substring(path from 14) AS "nicheId", COUNT(*)::int AS views, COUNT(DISTINCT "visitorId")::int AS visitors
           FROM "AnalyticsEvent" WHERE type = 'pageview' AND path LIKE '/app/chapter/%' AND "createdAt" >= ${DAY_START(6)}
          GROUP BY 1 ORDER BY 2 DESC LIMIT 8`, tz),
      q(`SELECT u.email, (EXTRACT(EPOCH FROM u."createdAt") * 1000)::float8 AS "createdAt", u."isPro", u."planType",
                CASE WHEN jsonb_typeof(u."dataBlob"->'niches') = 'array' THEN u."dataBlob"->'niches' ELSE '[]'::jsonb END AS niches,
                CASE WHEN jsonb_typeof(u."dataBlob"->'completed') = 'array' THEN jsonb_array_length(u."dataBlob"->'completed') ELSE 0 END AS "guidesCompleted",
                CASE WHEN jsonb_typeof(u."dataBlob"->'streak'->'count') = 'number' THEN (u."dataBlob"->'streak'->>'count')::float8 ELSE 0 END AS streak,
                a.channel, a.source, a.campaign
           FROM "User" u LEFT JOIN "UserAttribution" a ON a."userId" = u.id
          WHERE ${notStaff1} ORDER BY u."createdAt" DESC LIMIT 20`, staff),
      q(`SELECT channel, COUNT(DISTINCT "sessionId")::int AS sessions FROM "AnalyticsEvent"
          WHERE type = 'pageview' AND "createdAt" >= ${DAY_START(29)} GROUP BY 1`, tz),
      q(`SELECT COALESCE(SUM(value) FILTER (WHERE type IN ('purchase','renewal')), 0)::float8 AS "revenue30",
                COUNT(*) FILTER (WHERE type = 'purchase')::int AS "newPro30",
                COUNT(*) FILTER (WHERE type = 'cancel')::int AS "cancels30",
                COUNT(DISTINCT COALESCE("userId", "visitorId")) FILTER (WHERE type = 'paywall')::int AS "paywall30",
                COUNT(DISTINCT COALESCE("userId", "visitorId")) FILTER (WHERE type = 'checkout')::int AS "checkout30",
                COUNT(DISTINCT "visitorId") FILTER (WHERE type = 'pageview')::int AS "visitors30"
           FROM "AnalyticsEvent" WHERE "createdAt" >= ${DAY_START(29)}`, tz),
      Promise.all([
        q(`SELECT COUNT(*)::int AS n FROM "Win"`).catch(() => [{ n: 0 }]),
        q(`SELECT COUNT(*)::int AS n FROM "NetworkRequest"`).catch(() => [{ n: 0 }]),
        q(`SELECT COUNT(*)::int AS n FROM "MentorProfile"`).catch(() => [{ n: 0 }]),
        q(`SELECT COUNT(*)::int AS n FROM "DiscussionPost"`).catch(() => [{ n: 0 }]),
      ]),
    ]);

    const days = dayList(tz, 30);
    const fill = (rows) => { const m = new Map(rows.map(r => [r.d, Number(r.n)])); return days.map(d => ({ date: d, value: m.get(d) || 0 })); };
    const mrr = u.monthlyUsers * PRICES.monthly + u.yearlyUsers * PRICES.yearly / 12;
    return {
      generatedAt: Date.now(), tz,
      users: {
        total: u.totalUsers, pro: u.proUsers, free: u.totalUsers - u.proUsers, monthly: u.monthlyUsers, yearly: u.yearlyUsers,
        signupsToday: u.signupsToday, signups7: u.signups7, signups30: u.signups30, signupsPrev30: u.signupsPrev30,
        conversionRate: u.totalUsers ? Math.round(u.proUsers / u.totalUsers * 1000) / 10 : 0,
      },
      revenue: {
        mrr: Math.round(mrr * 100) / 100, arr: Math.round(mrr * 12 * 100) / 100,
        revenue30: Math.round(money.revenue30 * 100) / 100, newPro30: money.newPro30, cancels30: money.cancels30,
        paywall30: money.paywall30, checkout30: money.checkout30, visitors30: money.visitors30,
      },
      active: active,
      engagement: {
        avgStreak: Math.round(engage.avgStreak * 10) / 10, maxStreak: Math.round(engage.maxStreak), totalCompleted: Math.round(engage.totalCompleted),
        avgCompleted: u.totalUsers ? Math.round(engage.totalCompleted / u.totalUsers * 10) / 10 : 0,
      },
      community: { wins: community[0][0].n, connections: community[1][0].n, mentors: community[2][0].n, posts: community[3][0].n },
      series: { signups: fill(signupsDaily), revenue: fill(revenueDaily), visitors: fill(visitorsDaily) },
      popularChapters: chapters, chapterViews,
      channels: orderChannels(channels.map(c => ({ channel: c.channel, sessions: c.sessions }))),
      recentSignups: recent.map(r => ({ ...r, streak: Math.max(0, Math.round(r.streak || 0)), niches: Array.isArray(r.niches) ? r.niches : [] })),
    };
  });
}

// The last n calendar dates (YYYY-MM-DD) in the viewer's time zone, oldest
// first. Steps by date rather than 24h so daylight-saving changes can't skip
// or repeat a day.
function dayList(tz, n) {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  const [y, m, d] = today.split('-').map(Number);
  const out = [];
  for (let i = n - 1; i >= 0; i--) out.push(new Date(Date.UTC(y, m - 1, d - i)).toISOString().slice(0, 10));
  return out;
}
function orderChannels(rows) {
  return rows.sort((a, b) => (CHANNELS.indexOf(a.channel) + 99 * (CHANNELS.indexOf(a.channel) < 0)) - (CHANNELS.indexOf(b.channel) + 99 * (CHANNELS.indexOf(b.channel) < 0)));
}

// ---------------------------------------------------------------- marketing report
const RANGES = { today: 1, '7d': 7, '30d': 30, '90d': 90 };
const reportCache = new Map();

async function marketingReport({ range, tz, model }) {
  tz = validTz(tz);
  const N = RANGES[range] || 30;
  range = Object.keys(RANGES).find(k => RANGES[k] === N);
  model = model === 'last' ? 'last' : 'first';
  return cached(reportCache, `${range}|${tz}|${model}`, 20000, async () => {
    const staff = staffEmails();
    const S = DAY_START(N - 1), E = NOW_UTC;
    const PS = `(${DAY_START(N - 1)} - interval '${N} days')`, PE = AGO(N, 'days');
    const W = (col = '"createdAt"', s = S, e = E) => `${col} >= ${s} AND ${col} < ${e}`;
    const PV = `type = 'pageview'`;
    const notStaff = `lower(u.email) <> ALL($2::text[])`;
    const aCh = model === 'last' ? `COALESCE(a."lastChannel", a.channel)` : 'a.channel';
    const aSrc = model === 'last' ? `COALESCE(a."lastSource", a.source)` : 'a.source';
    const aCmp = model === 'last' ? `COALESCE(a."lastCampaign", a.campaign)` : 'a.campaign';
    const bucket = N === 1 ? `to_char(${LOCAL('"createdAt"')}, 'HH24')` : `to_char(${LOCAL('"createdAt"')}, 'YYYY-MM-DD')`;
    const ubucket = N === 1 ? `to_char(${LOCAL('u."createdAt"')}, 'HH24')` : `to_char(${LOCAL('u."createdAt"')}, 'YYYY-MM-DD')`;

    const kpis = (s, e) => Promise.all([
      q(`SELECT COUNT(DISTINCT "visitorId")::int AS visitors, COUNT(DISTINCT "sessionId")::int AS sessions, COUNT(*)::int AS pageviews
           FROM "AnalyticsEvent" WHERE ${PV} AND ${W('"createdAt"', s, e)}`, tz),
      q(`SELECT COUNT(*) FILTER (WHERE c = 1)::int AS bounced, COUNT(*)::int AS sessions
           FROM (SELECT COUNT(*) AS c FROM "AnalyticsEvent" WHERE ${PV} AND ${W('"createdAt"', s, e)} GROUP BY "sessionId") x`, tz),
      q(`SELECT COUNT(*)::int AS signups FROM "User" u WHERE ${W('u."createdAt"', s, e)} AND ${notStaff}`, tz, staff),
      q(`SELECT COUNT(DISTINCT COALESCE("userId", "visitorId")) FILTER (WHERE type = 'paywall')::int AS paywall,
                COUNT(DISTINCT COALESCE("userId", "visitorId")) FILTER (WHERE type = 'checkout')::int AS checkout,
                COUNT(*) FILTER (WHERE type = 'purchase')::int AS "newPro",
                COALESCE(SUM(value) FILTER (WHERE type IN ('purchase','renewal')), 0)::float8 AS revenue
           FROM "AnalyticsEvent" WHERE ${W('"createdAt"', s, e)}`, tz),
    ]).then(([[a], [b], [c], [d]]) => ({
      visitors: a.visitors, sessions: a.sessions, pageviews: a.pageviews,
      bounceRate: b.sessions ? Math.round(b.bounced / b.sessions * 1000) / 10 : 0,
      pagesPerSession: a.sessions ? Math.round(a.pageviews / a.sessions * 10) / 10 : 0,
      signups: c.signups, signupRate: a.visitors ? Math.round(c.signups / a.visitors * 1000) / 10 : 0,
      paywall: d.paywall, checkout: d.checkout, newPro: d.newPro, revenue: Math.round(d.revenue * 100) / 100,
    }));

    const [
      cur, prev, chTraffic, chSignups, chMoney, srcTraffic, srcSignups, cmpTraffic, cmpSignups, cmpMoney,
      referrers, landings, landSignups, pages, devices, browsers, countries, seriesCh, seriesSignups,
    ] = await Promise.all([
      kpis(S, E), kpis(PS, PE),
      q(`SELECT channel, COUNT(DISTINCT "visitorId")::int AS visitors, COUNT(DISTINCT "sessionId")::int AS sessions, COUNT(*)::int AS pageviews
           FROM "AnalyticsEvent" WHERE ${PV} AND ${W()} GROUP BY 1`, tz),
      q(`SELECT COALESCE(${aCh}, 'Unattributed') AS channel, COUNT(*)::int AS signups
           FROM "User" u LEFT JOIN "UserAttribution" a ON a."userId" = u.id WHERE ${W('u."createdAt"')} AND ${notStaff} GROUP BY 1`, tz, staff),
      q(`SELECT COALESCE(${aCh}, 'Unattributed') AS channel, COUNT(*) FILTER (WHERE e.type = 'purchase')::int AS pro,
                COALESCE(SUM(e.value), 0)::float8 AS revenue
           FROM "AnalyticsEvent" e LEFT JOIN "UserAttribution" a ON a."userId" = e."userId"
          WHERE e.type IN ('purchase','renewal') AND ${W('e."createdAt"')} GROUP BY 1`, tz),
      q(`SELECT source, channel, MIN(medium) AS medium, COUNT(DISTINCT "visitorId")::int AS visitors,
                COUNT(DISTINCT "sessionId")::int AS sessions
           FROM "AnalyticsEvent" WHERE ${PV} AND ${W()} GROUP BY 1, 2 ORDER BY sessions DESC LIMIT 25`, tz),
      q(`SELECT ${aSrc} AS source, ${aCh} AS channel, COUNT(*)::int AS signups FROM "User" u JOIN "UserAttribution" a ON a."userId" = u.id
          WHERE ${W('u."createdAt"')} AND ${notStaff} GROUP BY 1, 2`, tz, staff),
      q(`SELECT campaign, MIN(source) AS source, MIN(channel) AS channel, COUNT(DISTINCT "visitorId")::int AS visitors,
                COUNT(DISTINCT "sessionId")::int AS sessions
           FROM "AnalyticsEvent" WHERE ${PV} AND campaign IS NOT NULL AND ${W()} GROUP BY 1 ORDER BY sessions DESC LIMIT 25`, tz),
      q(`SELECT ${aCmp} AS campaign, COUNT(*)::int AS signups FROM "User" u JOIN "UserAttribution" a ON a."userId" = u.id
          WHERE ${W('u."createdAt"')} AND ${notStaff} AND ${aCmp} IS NOT NULL GROUP BY 1`, tz, staff),
      q(`SELECT ${aCmp} AS campaign, COUNT(*) FILTER (WHERE e.type = 'purchase')::int AS pro, COALESCE(SUM(e.value), 0)::float8 AS revenue
           FROM "AnalyticsEvent" e JOIN "UserAttribution" a ON a."userId" = e."userId"
          WHERE e.type IN ('purchase','renewal') AND ${W('e."createdAt"')} AND ${aCmp} IS NOT NULL GROUP BY 1`, tz),
      q(`SELECT referrer, MIN(channel) AS channel, COUNT(DISTINCT "sessionId")::int AS sessions
           FROM "AnalyticsEvent" WHERE ${PV} AND referrer IS NOT NULL AND ${W()} GROUP BY 1 ORDER BY 3 DESC LIMIT 15`, tz),
      q(`SELECT landing, COUNT(*)::int AS sessions, COUNT(*) FILTER (WHERE c = 1)::int AS bounced
           FROM (SELECT "sessionId", MIN(landing) AS landing, COUNT(*) AS c FROM "AnalyticsEvent"
                  WHERE ${PV} AND ${W()} GROUP BY 1) x WHERE landing IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 12`, tz),
      q(`SELECT a.landing, COUNT(*)::int AS signups FROM "User" u JOIN "UserAttribution" a ON a."userId" = u.id
          WHERE ${W('u."createdAt"')} AND ${notStaff} AND a.landing IS NOT NULL GROUP BY 1`, tz, staff),
      q(`SELECT path, COUNT(*)::int AS views, COUNT(DISTINCT "visitorId")::int AS visitors
           FROM "AnalyticsEvent" WHERE ${PV} AND ${W()} AND path IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 15`, tz),
      q(`SELECT COALESCE(device, 'Unknown') AS name, COUNT(DISTINCT "sessionId")::int AS sessions
           FROM "AnalyticsEvent" WHERE ${PV} AND ${W()} GROUP BY 1 ORDER BY 2 DESC`, tz),
      q(`SELECT COALESCE(browser, 'Unknown') AS name, COUNT(DISTINCT "sessionId")::int AS sessions
           FROM "AnalyticsEvent" WHERE ${PV} AND ${W()} GROUP BY 1 ORDER BY 2 DESC LIMIT 8`, tz),
      q(`SELECT COALESCE(country, '??') AS name, COUNT(DISTINCT "sessionId")::int AS sessions
           FROM "AnalyticsEvent" WHERE ${PV} AND ${W()} GROUP BY 1 ORDER BY 2 DESC LIMIT 10`, tz),
      q(`SELECT ${bucket} AS b, channel, COUNT(DISTINCT "sessionId")::int AS n
           FROM "AnalyticsEvent" WHERE ${PV} AND ${W()} GROUP BY 1, 2`, tz),
      q(`SELECT ${ubucket} AS b, COUNT(*)::int AS n FROM "User" u WHERE ${W('u."createdAt"')} AND ${notStaff} GROUP BY 1`, tz, staff),
    ]);

    // Channel table = traffic + signups + money, merged.
    const byCh = new Map();
    const ch = name => { if (!byCh.has(name)) byCh.set(name, { channel: name, visitors: 0, sessions: 0, pageviews: 0, signups: 0, pro: 0, revenue: 0 }); return byCh.get(name); };
    chTraffic.forEach(r => Object.assign(ch(r.channel), { visitors: r.visitors, sessions: r.sessions, pageviews: r.pageviews }));
    chSignups.forEach(r => { ch(r.channel).signups = r.signups; });
    chMoney.forEach(r => { const c = ch(r.channel); c.pro = r.pro; c.revenue = Math.round(r.revenue * 100) / 100; });
    const channels = orderChannels([...byCh.values()]).map(c => ({ ...c, signupRate: c.visitors ? Math.round(c.signups / c.visitors * 1000) / 10 : null }));

    const srcKey = r => `${r.source}|${r.channel}`;
    const srcSign = new Map(srcSignups.map(r => [srcKey(r), r.signups]));
    const sources = srcTraffic.map(r => ({ ...r, signups: srcSign.get(srcKey(r)) || 0 }));
    // sources that produced signups but no tracked visits in this window still deserve a row
    srcSignups.forEach(r => { if (!srcTraffic.some(t => srcKey(t) === srcKey(r))) sources.push({ source: r.source, channel: r.channel, medium: null, visitors: 0, sessions: 0, signups: r.signups }); });
    const cmpSign = new Map(cmpSignups.map(r => [r.campaign, r.signups]));
    const cmpPay = new Map(cmpMoney.map(r => [r.campaign, r]));
    const campaignNames = new Set([...cmpTraffic.map(r => r.campaign), ...cmpSignups.map(r => r.campaign)]);
    const campaigns = [...campaignNames].map(name => {
      const t = cmpTraffic.find(r => r.campaign === name) || { visitors: 0, sessions: 0, source: null, channel: null };
      const p = cmpPay.get(name) || { pro: 0, revenue: 0 };
      return { campaign: name, source: t.source, channel: t.channel, visitors: t.visitors, sessions: t.sessions,
        signups: cmpSign.get(name) || 0, pro: p.pro, revenue: Math.round(p.revenue * 100) / 100 };
    }).sort((a, b) => b.sessions - a.sessions || b.signups - a.signups).slice(0, 25);
    const landSign = new Map(landSignups.map(r => [r.landing, r.signups]));

    // Series buckets
    let buckets;
    if (N === 1) {
      const hourFmt = new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', hourCycle: 'h23' });
      const nowH = Number(hourFmt.format(new Date()));
      buckets = Array.from({ length: nowH + 1 }, (_, h) => String(h).padStart(2, '0'));
    } else buckets = dayList(tz, N);
    const series = buckets.map(b => {
      const row = { bucket: b, signups: 0, total: 0 };
      CHANNELS.forEach(c => { row[c] = 0; });
      return row;
    });
    const idx = new Map(buckets.map((b, i) => [b, i]));
    seriesCh.forEach(r => { const i = idx.get(r.b); if (i === undefined) return; const key = CHANNELS.includes(r.channel) ? r.channel : 'Other'; series[i][key] += r.n; series[i].total += r.n; });
    seriesSignups.forEach(r => { const i = idx.get(r.b); if (i !== undefined) series[i].signups = r.n; });

    return {
      generatedAt: Date.now(), range, tz, model, granularity: N === 1 ? 'hour' : 'day',
      kpis: cur, previous: prev, channels, sources, campaigns,
      referrers, landings: landings.map(l => ({ ...l, bounceRate: l.sessions ? Math.round(l.bounced / l.sessions * 1000) / 10 : 0, signups: landSign.get(l.landing) || 0 })),
      pages, devices, browsers, countries, series, channelOrder: CHANNELS,
    };
  });
}

// Writes everything still queued (used on shutdown), giving up after maxMs.
async function drain(maxMs = 2500) {
  const end = Date.now() + maxMs;
  while ((queue.length || flushing) && Date.now() < end) {
    if (flushing) await new Promise(r => setTimeout(r, 40));
    else await flush();
  }
}

// ---------------------------------------------------------------- housekeeping
async function pruneOldEvents() {
  if (!ready) return;
  try {
    await prisma.$executeRawUnsafe(`DELETE FROM "AnalyticsEvent" WHERE "createdAt" < ${AGO(400, 'days')}`);
  } catch (err) { console.error('Analytics prune failed:', err.message); }
}

module.exports = {
  CHANNELS, ensureAnalyticsTables, isReady, roleFor, isStaffEmail, classify, parseUA, isBot, validTz, countryFromTz,
  touchPresence, leavePresence, presenceSummary, recordEvent, recordSignup, recordMoney, liveSnapshot, ownerOverview,
  marketingReport, bus, scrubFor, flush, drain, pruneOldEvents, s,
};
