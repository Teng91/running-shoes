const CACHE_NAME = 'running-shoes-shell-v17';
const APP_ASSET_VERSION = '3.2.0';
const versioned = path => `${path}?v=${APP_ASSET_VERSION}`;
const APP_SHELL = [
  '/',
  versioned('/app-boot.js'),
  versioned('/app-state.js'),
  versioned('/app-api.js'),
  versioned('/app-auth.js'),
  versioned('/app-core.js'),
  versioned('/app-agent.js'),
  versioned('/app-reports.js'),
  versioned('/app-runs.js'),
  versioned('/app-strava.js'),
  versioned('/app-run-insights.js'),
  versioned('/app-shoes.js'),
  versioned('/app-dashboard.js'),
  versioned('/app-monthly.js'),
  versioned('/app-charts.js'),
  versioned('/app-spending.js'),
  versioned('/app.js'),
  versioned('/styles.css'),
  '/offline.html',
  '/manifest.webmanifest',
  '/favicon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.png',
  '/vendor/chart.umd.min.js',
  '/vendor/marked.min.js',
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(names => Promise.all(names.filter(name => name !== CACHE_NAME).map(name => caches.delete(name))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate') {
    const networkResponse = fetch(request).then(async response => {
      if (response.ok) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put('/', response.clone());
      }
      return response;
    });
    // A cached app shell renders the startup UI immediately while a Fly
    // Machine wakes. Refresh that shell in the background for the next open.
    event.waitUntil(networkResponse.then(() => undefined, () => undefined));
    event.respondWith(
      caches.match('/').then(cached => cached || networkResponse)
        .catch(() => caches.match('/offline.html'))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request))
  );
});
