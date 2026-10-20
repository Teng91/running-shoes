const CACHE_PREFIX = 'running-shoes-shell-';
const CACHE_NAME = 'running-shoes-shell-v21';
const APP_ASSET_VERSION = '3.2.4';
const versioned = path => `${path}?v=${APP_ASSET_VERSION}`;
const APP_SHELL = [
  '/',
  versioned('/app-boot.js'),
  versioned('/app-state.js'),
  versioned('/app-api.js'),
  versioned('/app-auth.js'),
  versioned('/app-streams.js'),
  versioned('/app-core.js'),
  versioned('/app-agent.js'),
  versioned('/app-reports.js'),
  versioned('/app-runs.js'),
  versioned('/app-strava.js'),
  versioned('/app-run-insights.js'),
  versioned('/app-shoes.js'),
  versioned('/app-dashboard.js'),
  versioned('/app-monthly.js'),
  versioned('/app-exports.js'),
  versioned('/app-goals.js'),
  versioned('/app-charts.js'),
  versioned('/app-shoe-charts.js'),
  versioned('/app-monthly-charts.js'),
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

async function installShell() {
  const existed = await caches.has(CACHE_NAME);
  try {
    const resources = await Promise.all(APP_SHELL.map(async path => {
      const response = await fetch(new Request(path, { cache: 'reload' }));
      if (!response.ok) throw new Error('App shell asset unavailable');
      const type = response.headers.get('content-type') || '';
      if ((path.includes('.js') && !type.includes('javascript')) ||
          (path.includes('.css') && !type.includes('text/css'))) {
        throw new Error('App shell asset has unexpected content type');
      }
      if (path === '/') {
        const html = await response.clone().text();
        if (!html.includes(`<meta name="app-asset-version" content="${APP_ASSET_VERSION}">`)) {
          throw new Error('App shell version mismatch');
        }
      }
      // Drain each response before waiting for all headers. Otherwise a large
      // unread body can occupy the limited connection pool during installation.
      await response.clone().arrayBuffer();
      return [path, response];
    }));
    const cache = await caches.open(CACHE_NAME);
    await Promise.all(resources.map(([path, response]) => cache.put(path, response)));
    await self.skipWaiting();
  } catch (error) {
    if (!existed) await caches.delete(CACHE_NAME);
    throw error;
  }
}

self.addEventListener('install', event => { event.waitUntil(installShell()); });

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(names => Promise.all(names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME).map(name => caches.delete(name))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate') {
    // The installed shell is immutable. A navigation response may be from a
    // newer deployment whose assets have not finished installing yet.
    event.respondWith(
      caches.open(CACHE_NAME).then(async cache =>
        (await cache.match('/')) || fetch(request).catch(() => cache.match('/offline.html'))
      )
    );
    return;
  }

  event.respondWith(
    caches.open(CACHE_NAME).then(async cache => (await cache.match(request)) || fetch(request))
  );
});
