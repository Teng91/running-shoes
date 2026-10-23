const CACHE_PREFIX = 'running-shoes-shell-';
const CACHE_NAME = '{{cache_name}}';
const APP_ASSET_VERSION = '{{asset_version}}';
const versioned = path => `${path}?v=${APP_ASSET_VERSION}`;
const APP_SHELL = [
{{shell_assets}}
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
