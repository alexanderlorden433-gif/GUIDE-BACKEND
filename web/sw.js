// The Guide — service worker
// Caches the app shell (the HTML page, manifest, icons) so the app still
// opens when offline. API calls always go to the network — there's no
// meaningful "offline" version of your live account data, so we don't try
// to fake one; apiFetch() in the app already handles those failures cleanly.

const CACHE_NAME = 'the-guide-shell-v2';
const SHELL_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls — always hit the network, and let the app's own
  // error handling deal with failures (it already does this gracefully).
  if (url.pathname.startsWith('/api/')) {
    return; // let the browser handle it normally
  }

  // Only handle same-origin GET requests for the app shell itself.
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  // Leave video and audio to the browser: it asks for them in pieces (Range
  // requests), and keeping a whole video here would fill the phone's storage.
  if (event.request.headers.has('range') ||
      event.request.destination === 'video' || event.request.destination === 'audio') {
    return;
  }

  event.respondWith(
    // Network-first for the page itself, so users get updates when online;
    // falls back to the cached shell when offline.
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match('/')))
  );
});

// ---------- push notifications (live calls) ----------
// The server sends a small JSON message: {title, body, url, tag}. Tapping it opens the app at that url.
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data ? event.data.text() : '' }; }
  const title = data.title || 'The Guide';
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/favicon-32.png',
    tag: data.tag || undefined,
    renotify: !!data.tag,
    data: { url: data.url || '/' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      const open = wins.find((w) => w.url.startsWith(self.location.origin));
      if (open) { return open.navigate(target).then((w) => (w || open).focus()); }
      return self.clients.openWindow(target);
    })
  );
});
