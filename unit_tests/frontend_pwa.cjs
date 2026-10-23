// Real service-worker upgrade/offline regression. Local fixture only; no Fly/API writes.
const { chromium, webkit } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { startArtifacts, saveFailure, closeBrowser, withDeadline } = require('../scripts/browser_artifacts.cjs');

const frontend = path.resolve(__dirname, '../frontend');
const htmlSource = fs.readFileSync(path.join(frontend, 'index.html'), 'utf8');
const workerSource = fs.readFileSync(path.join(frontend, 'service-worker.js'), 'utf8');
const legacySource = fs.readFileSync(path.join(__dirname, 'fixtures/service-worker-v3.2.2.js'), 'utf8');
const assetVersion = workerSource.match(/APP_ASSET_VERSION = '([^']+)'/)[1];
const cacheName = workerSource.match(/const CACHE_NAME = '([^']+)'/)[1];
const mime = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.html': 'text/html',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };
const debug = (...args) => { if (process.env.PWA_DEBUG) console.log(...args); };

async function updateWorker(page) {
  return page.evaluate(async () => {
    const registration = await navigator.serviceWorker.getRegistration();
    const finished = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('worker update timed out')), 15000);
      registration.addEventListener('updatefound', () => {
        const worker = registration.installing;
        const changed = () => {
          if (['activated', 'redundant'].includes(worker.state)) {
            clearTimeout(timer); resolve(worker.state);
          }
        };
        worker.addEventListener('statechange', changed);
        changed();
      }, { once: true });
    });
    await registration.update();
    return finished;
  });
}

async function assertShell(page, release) {
  await page.locator('#login-form').waitFor({ state: 'visible' });
  await page.locator('#app-boot').waitFor({ state: 'hidden' });
  assert.equal(await page.evaluate(() => window.__pwaRelease), release);
  assert.equal(await page.locator('meta[name="app-asset-version"]').getAttribute('content'), release);
  assert.equal(await page.locator('.tab-panel.active').getAttribute('data-panel'), 'runs', 'cached document must start at home');
  assert.equal(await page.locator('#mobile-page-label').textContent(), '跑步日誌');
}

async function run() {
  let release = 'fixture-a', failure = null, failedAssets = 0, networkDown = false, legacy = true;
  let moduleOriginRequests = 0;
  const failedKinds = new Set();
  const server = http.createServer((request, response) => {
    if (networkDown) { request.socket.destroy(); return; }
    const url = new URL(request.url, 'http://127.0.0.1');
    if (process.env.PWA_DEBUG) console.log('PWA fixture request', url.pathname, url.search);
    response.setHeader('Cache-Control', 'no-store');
    // Match production CORSMiddleware: module requests have Origin, precache requests do not.
    response.setHeader('Vary', 'Origin');
    if (request.headers.origin) response.setHeader('Access-Control-Allow-Origin', request.headers.origin);
    if (url.pathname === '/runtime/feature-lifecycle.mjs' && request.headers.origin) moduleOriginRequests++;
    if (url.pathname === '/service-worker.js') {
      response.setHeader('Content-Type', 'text/javascript');
      response.end((legacy ? legacySource : workerSource).replaceAll(legacy ? '3.2.2' : assetVersion, release)
        .replaceAll(legacy ? 'running-shoes-shell-v19' : cacheName, 'running-shoes-shell-' + release)
        .replace('const APP_SHELL = [', "const APP_SHELL = [versioned('/release-marker.js'),"));
      return;
    }
    if (url.pathname === '/api/test') {
      response.setHeader('Content-Type', 'application/json');
      response.end('{"synthetic_private_data":true}'); return;
    }
    if ((url.pathname === '/app-goals.js' && ['http', 'mime', 'disconnect'].includes(failure) ||
         url.pathname === '/runtime/feature-lifecycle.mjs' && failure === 'module-mime') && url.searchParams.get('v') === release) {
      failedAssets++;
      failedKinds.add(failure);
      if (failure === 'disconnect') {
        response.setHeader('Content-Type', 'text/javascript');
        response.flushHeaders(); response.write('// interrupted asset');
        setImmediate(() => response.destroy()); return;
      }
      response.statusCode = failure === 'http' ? 503 : 200;
      response.setHeader('Content-Type', 'text/html');
      response.end('<html>not a JavaScript asset</html>'); return;
    }
    if (url.pathname === '/release-marker.js') {
      response.setHeader('Content-Type', 'text/javascript');
      response.end('window.__pwaRelease=' + JSON.stringify(url.searchParams.get('v')) + ';'); return;
    }
    if (url.pathname === '/') {
      response.setHeader('Content-Type', 'text/html');
      let html = htmlSource.replaceAll(assetVersion, release)
        .replace('</head>', `<script src="/release-marker.js?v=${release}"></script></head>`);
      if (failure === 'html-version') {
        failedAssets++; failedKinds.add(failure);
        html = html.replace(`content="${release}"`, 'content="wrong-version"');
      }
      response.end(html); return;
    }
    const local = path.resolve(frontend, '.' + url.pathname);
    if (!local.startsWith(frontend + path.sep) || !fs.existsSync(local) || !fs.statSync(local).isFile()) {
      response.statusCode = 404; response.end('Not found'); return;
    }
    response.setHeader('Content-Type', mime[path.extname(local)] || 'application/octet-stream');
    response.end(fs.readFileSync(local));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  debug('PWA local fixture:', origin);
  try {
    for (const engine of [chromium, webkit]) {
      release = 'fixture-a'; failure = null; failedAssets = 0; networkDown = false; legacy = true;
      moduleOriginRequests = 0;
      failedKinds.clear();
      let browser, context, page;
      try {
        await withDeadline(async () => {
          browser = await engine.launch({ headless: true, timeout: 30000 });
          context = await browser.newContext({ serviceWorkers: 'allow', locale: 'zh-TW' });
          await startArtifacts(context);
          page = await context.newPage();
          page.setDefaultTimeout(15000);
          page.setDefaultNavigationTimeout(15000);
          const errors = [];
          page.on('pageerror', error => errors.push(error.message));
          page.on('console', message => { if (process.env.PWA_DEBUG && message.type() === 'error') console.error('PWA fixture console:', message.text()); });
          const setOffline = async offline => {
            // WebKit's network-emulation switch also prevents cached SW navigations.
            // A dropped fixture transport tests actual network failure without disabling SW itself.
            networkDown = offline;
            if (engine === chromium) await context.setOffline(offline);
          };
          debug(`PWA ${engine.name()}: first offline / online install`);
          // Without a previously installed shell, an offline first visit cannot load.
          await setOffline(true);
          await assert.rejects(page.goto(origin, { timeout: 5000 }));
          debug(`PWA ${engine.name()}: offline first visit rejected`);
          await setOffline(false);
          debug(`PWA ${engine.name()}: fetching initial online document`);
          await page.goto(origin, { waitUntil: 'networkidle' });
          await page.waitForFunction(async () => (await navigator.serviceWorker.getRegistration())?.active?.state === 'activated', null, { timeout: 15000 });
          await page.evaluate(() => navigator.serviceWorker.ready);
          await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
          await assertShell(page, 'fixture-a');
          // Migrate the frozen real v3.2.2 worker online before testing failure-safe future upgrades.
          legacy = false; release = 'fixture-a-safe';
          assert.equal(await updateWorker(page), 'activated');
          await page.reload({ waitUntil: 'networkidle' });
          await assertShell(page, 'fixture-a-safe');
          assert.ok(moduleOriginRequests > 0, 'native module actually requests an Origin variant');
          assert.equal(await page.evaluate(async () => {
            const cache = await caches.open('running-shoes-shell-fixture-a-safe');
            const response = await cache.match('/runtime/feature-lifecycle.mjs?v=fixture-a-safe');
            return response.headers.get('Vary');
          }), 'Origin', 'precache retains the production Vary response header');
          debug(`PWA ${engine.name()}: installed shell ready`);
          await page.evaluate(async () => {
            const other = await caches.open('unrelated-cache');
            await other.put('/sentinel', new Response('keep'));
            await fetch('/api/test');
          });
          await setOffline(true);
          await page.evaluate(() => {
            localStorage.setItem('activeTab', 'agent');
            switchTab('agent');
          });
          await page.reload({ waitUntil: 'networkidle' });
          await assertShell(page, 'fixture-a-safe');
          assert.equal(await page.evaluate(() => fetch('/api/test').then(() => false, () => true)), true, 'offline API must fail instead of using cache');
          await setOffline(false);

          for (const [revision, problem] of [['fixture-b', 'http'], ['fixture-c', 'mime'], ['fixture-e', 'disconnect'], ['fixture-f', 'html-version'], ['fixture-g', 'module-mime']]) {
            debug(`PWA ${engine.name()}: reject ${problem} upgrade`);
            release = revision; failure = problem;
            assert.equal(await updateWorker(page), 'redundant', 'incomplete install must not activate');
            // A navigation while a newer deployment exists must not rewrite old HTML.
            await page.reload({ waitUntil: 'networkidle' });
            await assertShell(page, 'fixture-a-safe');
            await setOffline(true);
            await page.reload({ waitUntil: 'networkidle' });
            await assertShell(page, 'fixture-a-safe');
            await setOffline(false);
            assert.ok(await page.evaluate(() => caches.has('unrelated-cache')));
            assert.equal(await page.evaluate(name => caches.has(name), 'running-shoes-shell-' + revision), false);
          }
          assert.ok(failedAssets >= 5, 'fixture actually interrupted candidate installs');
          assert.deepEqual([...failedKinds].sort(), ['disconnect', 'html-version', 'http', 'mime', 'module-mime']);

          release = 'fixture-d'; failure = null;
          debug(`PWA ${engine.name()}: reconnect and activate complete upgrade`);
          assert.equal(await updateWorker(page), 'activated');
          await page.locator('#app-update-notice').waitFor({ state: 'visible' });
          assert.equal(await page.evaluate(() => window.__pwaRelease), 'fixture-a-safe', 'upgrade does not reload a live draft');
          await page.reload({ waitUntil: 'networkidle' });
          await assertShell(page, 'fixture-d');
          const state = await page.evaluate(async () => {
            const names = await caches.keys();
            const owned = names.filter(name => name.startsWith('running-shoes-shell-'));
            const cache = await caches.open(owned[0]);
            return { owned, other: await (await caches.open('unrelated-cache')).match('/sentinel').then(Boolean),
              api: !!(await cache.match('/api/test')), urls: (await cache.keys()).map(request => request.url),
              html: await (await cache.match('/')).text() };
          });
          assert.deepEqual(state.owned, ['running-shoes-shell-fixture-d']);
          assert.equal(state.other, true); assert.equal(state.api, false);
          assert.ok(state.urls.filter(url => url.includes('?v=')).every(url => url.endsWith('?v=fixture-d')));
          assert.ok(state.html.includes('content="fixture-d"'));
          await setOffline(true);
          await page.reload({ waitUntil: 'networkidle' });
          await assertShell(page, 'fixture-d');
          assert.deepEqual(errors, []);
          console.log(`PASS ${engine.name()} PWA: legacy migration, first/installed offline with CORS Vary/Origin module requests, HTTP/MIME/disconnect/revision failed upgrades, immutable shell, recovery, API exclusion and scoped cleanup`);
        }, 120000, 'PWA engine ' + engine.name());
      } catch (error) {
        await saveFailure(context, page, 'pwa-' + engine.name(), error);
        console.error(`PWA ${engine.name()} case failed:`, error);
        throw error;
      } finally { await closeBrowser(context, browser); }
    }
  } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
