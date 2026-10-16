// AI-designed member pages (My website, the Lovable-style builder): the AI writes the page's own HTML and CSS, so
// every member can have a page that looks the way they described it. Member pages are served from
// theguide.company/s/<address>, the same site as the app, so what the AI writes is never trusted:
//
//  1. cleanDesign() keeps only plain page markup (headings, text, links, lists, images, simple SVG icons…) and
//     drops everything that could run code or load things it shouldn't: scripts, event attributes, javascript:
//     links, frames, objects, forms, inline style attributes, meta/base tags. CSS loses @import, scripting
//     tricks and any url() that isn't an https image. It runs on every save, not just when the AI writes.
//  2. The page is served with CUSTOM_CSP, which forbids scripts outright and sandboxes the page (it can't see the
//     app's storage even if something slipped through), and only allows https images, Google Fonts and the
//     page's own request form.
//
// The AI marks where our own pieces go: <div data-guide="form"></div> for the request form, and links with
// data-guide="phone" / data-guide="email" for the owner's contact details (the AI never sees those).
const sanitizeHtml = require('sanitize-html');

const MAX_HTML = 60000;
const MAX_CSS = 30000;
const FONT_RE = /^[A-Za-z][A-Za-z0-9 ]{1,39}$/;

// (the parser keeps SVG's camelCase names, so both spellings are listed)
const SVG_TAGS = ['svg', 'g', 'path', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon', 'defs', 'lineargradient', 'linearGradient',
  'radialgradient', 'radialGradient', 'stop', 'text', 'tspan', 'clippath', 'clipPath', 'mask'];
const SVG_ATTRS = ['viewbox', 'viewBox', 'xmlns', 'width', 'height', 'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
  'stroke-dasharray', 'stroke-opacity', 'fill-opacity', 'fill-rule', 'clip-rule', 'opacity', 'preserveaspectratio', 'preserveAspectRatio', 'd', 'cx', 'cy',
  'r', 'rx', 'ry', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'points', 'transform', 'offset', 'stop-color', 'stop-opacity', 'gradientunits',
  'gradientUnits', 'gradienttransform', 'gradientTransform', 'font-size', 'font-weight', 'text-anchor', 'dominant-baseline', 'clip-path', 'mask'];

const HTML_OPTIONS = {
  allowedTags: ['section', 'header', 'footer', 'nav', 'main', 'article', 'aside', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'a', 'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'img', 'figure', 'figcaption', 'blockquote', 'q', 'cite', 'strong', 'em', 'b', 'i',
    'u', 's', 'small', 'mark', 'sub', 'sup', 'br', 'hr', 'time', 'address', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
    'caption', 'details', 'summary', 'abbr'].concat(SVG_TAGS),
  allowedAttributes: Object.assign({
    '*': ['class', 'id', 'aria-label', 'aria-hidden', 'role', 'title', 'lang', 'dir', 'data-guide'],
    a: ['href', 'target', 'rel'],
    img: ['src', 'alt', 'width', 'height', 'loading'],
    time: ['datetime'], td: ['colspan', 'rowspan'], th: ['colspan', 'rowspan', 'scope'], details: ['open'],
  }, Object.fromEntries(SVG_TAGS.map(t => [t, SVG_ATTRS]))),
  allowedSchemes: ['https', 'mailto', 'tel'],
  allowedSchemesByTag: { img: ['https'] },
  allowedSchemesAppliedToAttributes: ['href', 'src'],
  allowProtocolRelative: false,
  allowedIframeHostnames: [],
  disallowedTagsMode: 'discard',
  transformTags: {
    a: (tagName, attribs) => {
      const out = Object.assign({}, attribs);
      if (out.target === '_blank') out.rel = 'noopener noreferrer';
      else delete out.target;
      return { tagName, attribs: out };
    },
  },
  exclusiveFilter: (frame) => !!(frame.attribs && frame.attribs['data-guide'] && !['form', 'phone', 'email'].includes(frame.attribs['data-guide'])),
  parser: { lowerCaseAttributeNames: true },
};

/** Page markup from the AI (or saved before), cleaned so nothing in it can run. */
function cleanHtml(html) {
  const raw = String(html == null ? '' : html).slice(0, MAX_HTML * 2);
  const out = sanitizeHtml(raw, HTML_OPTIONS).trim();
  return out.length > MAX_HTML ? '' : out;
}

/** The page's CSS, cleaned: no imports, no scripting tricks, no loading anything but https images. */
function cleanCss(css) {
  let s = String(css == null ? '' : css).slice(0, MAX_CSS);
  s = s.replace(/\/\*[\s\S]*?\*\//g, '');                              // comments (they can hide the rest)
  s = s.replace(/@(import|charset|namespace)[^;{}]*;?/gi, '');
  s = s.replace(/expression\s*\(|javascript\s*:|vbscript\s*:|behavior\s*:|-moz-binding/gi, 'blocked');
  s = s.replace(/url\(\s*(['"]?)([^'")]*)\1\s*\)/gi, (m, q, u) => (/^https:\/\/[^\s'"<>()\\]+$/i.test(u.trim()) ? `url("${u.trim()}")` : 'none'));
  s = s.replace(/<\/?\s*style/gi, '').replace(/</g, '\\3C ');          // can't close the <style> it sits in
  return s.trim();
}

/** Google Fonts the page asked for: real-looking family names only, at most three. */
function cleanFonts(fonts) {
  return [...new Set((Array.isArray(fonts) ? fonts : []).map(f => String(f || '').replace(/\s+/g, ' ').trim()).filter(f => FONT_RE.test(f)))].slice(0, 3);
}

/** A design as saved on the page: {html, css, fonts}, or null when there isn't one. */
function cleanDesign(d) {
  if (!d || typeof d !== 'object') return null;
  const html = cleanHtml(d.html);
  if (!html) return null;
  return { html, css: cleanCss(d.css), fonts: cleanFonts(d.fonts) };
}

/** The Google Fonts stylesheet for the page's fonts (the lenient API, so a weight a font lacks doesn't break it). */
function fontsHref(fonts) {
  if (!fonts || !fonts.length) return '';
  return 'https://fonts.googleapis.com/css?family=' + fonts.map(f => f.replace(/ /g, '+') + ':400,500,600,700,800').join('|') + '&display=swap';
}

// No scripts at all, a sandbox (the page gets no access to the app's storage or cookies), https images,
// Google Fonts, and the page's own request form. Links and phone/email links still work when tapped.
const CUSTOM_CSP = [
  "default-src 'none'",
  "style-src 'unsafe-inline' https://fonts.googleapis.com",
  'font-src https://fonts.gstatic.com data:',
  'img-src https: data:',
  "form-action 'self'",
  "base-uri 'none'",
  "frame-ancestors 'self'",
  'sandbox allow-forms allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation',
].join('; ');

/**
 * Puts the owner's pieces into the cleaned markup: the request form where the AI left <div data-guide="form">,
 * and their phone/email on the links marked for them (links for details they haven't set are left out).
 */
function fillDesign(html, { formHtml, phone, phoneHref, email }) {
  const esc = (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  let placed = false;
  let out = html.replace(/<div\b[^>]*\bdata-guide="form"[^>]*>[\s\S]*?<\/div>/g, () => {
    if (placed) return '';
    placed = true;
    return formHtml;
  });
  out = out.replace(/<a\b([^>]*)\bdata-guide="(phone|email)"([^>]*)>([\s\S]*?)<\/a>/g, (m, pre, kind, post, inner) => {
    const value = kind === 'phone' ? phone : email;
    if (!value) return '';
    const attrs = (pre + post).replace(/\s*\b(href|target|rel)="[^"]*"/g, '').replace(/\s+/g, ' ').trim();
    const href = kind === 'phone' ? phoneHref : 'mailto:' + value;
    const text = inner.replace(/<[^>]*>/g, '').trim() ? inner : esc(value);
    return `<a${attrs ? ' ' + attrs : ''} data-guide="${kind}" href="${esc(href)}">${text}</a>`;
  });
  return { html: out, formPlaced: placed };
}

module.exports = { cleanDesign, cleanHtml, cleanCss, cleanFonts, fontsHref, fillDesign, CUSTOM_CSP, MAX_HTML, MAX_CSS };
