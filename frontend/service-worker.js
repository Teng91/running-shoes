const CACHE_PREFIX = 'running-shoes-shell-';
const CACHE_NAME = 'running-shoes-shell-v52';
const APP_ASSET_VERSION = '4.5.1';
const versioned = path => `${path}?v=${APP_ASSET_VERSION}`;
const APP_SHELL = [
  '/',
  versioned('/app-boot.js'),
  versioned('/app-lifecycle.js'),
  versioned('/app-state.js'),
  versioned('/app-api.js'),
  versioned('/app-auth.js'),
  versioned('/app-streams.js'),
  versioned('/app-resources.js'),
  versioned('/app-inline-editors.js'),
  versioned('/app-local-store.js'),
  versioned('/app-workspace.js'),
  versioned('/app-account-restore.js'),
  versioned('/app-history.js'),
  versioned('/app-core.js'),
  versioned('/app-models.js'),
  versioned('/app-markdown.js'),
  versioned('/app-agent.js'),
  versioned('/app-reports.js'),
  versioned('/app-runs.js'),
  versioned('/app-dates.js'),
  versioned('/app-strava.js'),
  versioned('/app-run-insights.js'),
  versioned('/app-shoes.js'),
  versioned('/app-dashboard.js'),
  versioned('/app-exports.js'),
  versioned('/app-goals.js'),
  versioned('/app-charts.js'),
  versioned('/app-shoe-charts.js'),
  versioned('/app-monthly-charts.js'),
  versioned('/app-spending.js'),
  versioned('/app-dialogs.js'),
  versioned('/app-updates.js'),
  versioned('/app.js'),
  versioned('/runtime/feature-lifecycle.mjs'),
  versioned('/runtime/run-controller.mjs'),
  versioned('/runtime/form-operations.mjs'),
  versioned('/runtime/resource-store.mjs'),
  versioned('/runtime/strava-controller.mjs'),
  versioned('/runtime/workspace-controller.mjs'),
  versioned('/runtime/account-restore-controller.mjs'),
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
      if ((/\.m?js(?:\?|$)/.test(path) && !type.includes('javascript')) ||
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
      const body = await response.clone().arrayBuffer();
      // Some engines resolve a truncated unencoded HTTP body. Compressed
      // lengths describe wire bytes, so only compare identity responses.
      const length = response.headers.get('content-length');
      const encoding = response.headers.get('content-encoding');
      if ((!encoding || encoding === 'identity') && /^\d+$/.test(length || '') && Number(length) !== body.byteLength) {
        throw new Error('App shell asset truncated');
      }
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

self.addEventListener('message', event => {
  if (event.data?.type === 'GET_SHELL_VERSION') {
    event.source?.postMessage({ type: 'SHELL_VERSION', version: APP_ASSET_VERSION });
  }
});

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
    // This cache contains only public, same-origin APP_SHELL assets. Production
    // CORS adds Vary: Origin, but module requests and precache fetches send
    // different Origin headers. Ignore that transport variant, not URL/query.
    caches.open(CACHE_NAME).then(async cache =>
      (await cache.match(request, { ignoreVary: true })) || fetch(request)
    )
  );
});
