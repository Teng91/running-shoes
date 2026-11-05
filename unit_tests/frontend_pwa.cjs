// Real service-worker upgrade/offline regression. Local fixture only; no Fly/API writes.
const { chromium, webkit } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { startArtifacts, saveFailure, closeBrowser, withDeadline } = require('../scripts/browser_artifacts.cjs');
const { waitForAsync } = require('./browser_waits.cjs');

const frontend = path.resolve(__dirname, '../frontend');
const htmlSource = fs.readFileSync(path.join(frontend, 'index.html'), 'utf8');
const workerSource = fs.readFileSync(path.join(frontend, 'service-worker.js'), 'utf8');
const legacySource = fs.readFileSync(path.join(__dirname, 'fixtures/service-worker-v3.2.2.js'), 'utf8');
const assetVersion = workerSource.match(/APP_ASSET_VERSION = '([^']+)'/)[1];
const cacheName = workerSource.match(/const CACHE_NAME = '([^']+)'/)[1];
const mime = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.html': 'text/html',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };
const debug = (...args) => { if (process.env.PWA_DEBUG) console.log(...args); };

const { observeWorkerUpdate } = require('../scripts/worker_update.cjs');
async function updateWorker(page) {
  return withDeadline(() => page.evaluate(observeWorkerUpdate, {}), 20000, 'service worker update');
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
  let candidateGate = null, candidateStarted = null;
  let moduleOriginRequests = 0, offlineApiFailures = 0, offlineWorkerFailures = 0, stage = 'startup';
  const requests = [];
  // A redundant candidate's sibling precache fetches can outlive install failure. WebKit retries
  // those requests if the transport drops mid-flight, holding the scope job queue, so the
  // fixture only disconnects once candidate traffic has drained.
  let inFlight = 0, lastRequestAt = 0;
  async function waitForFixtureQuiet(quietMs = 300, timeoutMs = 10000) {
    const deadline = Date.now() + timeoutMs;
    while (inFlight > 0 || Date.now() - lastRequestAt < quietMs) {
      if (Date.now() >= deadline) throw Error(`fixture traffic did not drain (${inFlight} in flight)`);
      await new Promise(resolve => setTimeout(resolve, 25));
    }
  }
  const phase = value => { stage = value; console.log('PWA phase:', value); };
  const failedKinds = new Set();
  // Background retries may still fetch an older candidate after the next phase.
  // Keep each deliberately broken deployment broken for its own asset version.
  const rejectedRevisions = new Map([['fixture-b', 'http'], ['fixture-c', 'mime'], ['fixture-e', 'disconnect'], ['fixture-f', 'html-version'], ['fixture-g', 'module-mime']]);
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, 'http://127.0.0.1');
    requests.push({ path: url.pathname, version: url.searchParams.get('v'), release, failure, networkDown });
    inFlight++; lastRequestAt = Date.now();
    response.once('close', () => { inFlight--; lastRequestAt = Date.now(); });
    if (requests.length > 100) requests.shift();
    if (networkDown) {
      if (url.pathname === '/service-worker.js') {
        // WebKit retries TCP drops for background register/update jobs. A failed
        // HTTP update ends that job, allowing the next online update to start.
        offlineWorkerFailures++;
        response.writeHead(503, { 'Content-Type': 'text/javascript', 'Cache-Control': 'no-store' });
        response.end('// worker update unavailable offline');
      } else if (url.pathname === '/api/test') {
        // WebKit may keep retrying a connection closed before HTTP headers.
        // Deliver headers first, then end an incomplete body: consuming JSON
        // must fail, while a worker-cached valid response would still succeed.
        offlineApiFailures++;
        response.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': '1000', 'Connection': 'close' });
        response.end('{"interrupted":');
      } else request.socket.destroy();
      return;
    }
    if (candidateGate && url.pathname === '/release-marker.js') { candidateStarted(); await candidateGate; }
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
    const assetFailure = rejectedRevisions.get(url.searchParams.get('v'));
    if (url.pathname === '/app-goals.js' && ['http', 'mime', 'disconnect'].includes(assetFailure) ||
        url.pathname === '/runtime/feature-lifecycle.mjs' && assetFailure === 'module-mime') {
      failedAssets++;
      failedKinds.add(assetFailure);
      if (assetFailure === 'disconnect') {
        // Headers plus a truncated declared body avoid WebKit retrying a socket
        // dropped before an HTTP response, while Response.text() must still reject.
        response.writeHead(200, { 'Content-Type': 'text/javascript', 'Content-Length': '1000', 'Connection': 'close' });
        response.end('// interrupted asset'); return;
      }
      response.statusCode = assetFailure === 'http' ? 503 : 200;
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
      moduleOriginRequests = 0; offlineApiFailures = 0; offlineWorkerFailures = 0;
      failedKinds.clear(); requests.length = 0; phase(engine.name() + ': launch');
      let browser, context, page, webkitQueueStalls = 0;
      const errors = [];
      const openBrowser = async () => {
        browser = await engine.launch({ headless: true, timeout: 30000 });
        context = await browser.newContext({ serviceWorkers: 'allow', locale: 'zh-TW' });
        await startArtifacts(context);
        page = await context.newPage();
        page.setDefaultTimeout(15000);
        page.setDefaultNavigationTimeout(15000);
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => { if (process.env.PWA_DEBUG && message.type() === 'error') console.error('PWA fixture console:', message.text()); });
      };
      try {
        await withDeadline(async () => {
          await openBrowser();
          const setOffline = async offline => {
            // WebKit's network-emulation switch also prevents cached SW navigations.
            // A dropped fixture transport tests actual network failure without disabling SW itself.
            if (offline) await waitForFixtureQuiet();
            networkDown = offline;
            if (engine === chromium) await context.setOffline(offline);
          };
          const recoverFromWebKitQueueStall = async () => {
            // Fresh browser with the installed safe release, back in the offline state the
            // interrupted check expected (sentinel cache included).
            await closeBrowser(context, browser);
            await openBrowser();
            legacy = false; release = 'fixture-a-safe'; failure = null; networkDown = false;
            await page.goto(origin, { waitUntil: 'networkidle' });
            await waitForAsync(page, async () => (await navigator.serviceWorker.getRegistration())?.active?.state === 'activated', null, { timeout: 15000 });
            await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
            await assertShell(page, 'fixture-a-safe');
            await page.evaluate(async () => { await (await caches.open('unrelated-cache')).put('/sentinel', new Response('keep')); });
            await setOffline(true);
            await page.reload({ waitUntil: 'networkidle' });
            await assertShell(page, 'fixture-a-safe');
          };
          const assertOfflineUpdate = async () => {
            phase(`PWA ${engine.name()}: offline worker update rejects`);
            const dispatchedBefore = offlineWorkerFailures;
            const evaluation = page.evaluate(async () => {
              // WebKit can briefly resolve getRegistration() to undefined right after an offline
              // reload of a controlled page; ready waits for the active registration instead.
              const registration = await navigator.serviceWorker.ready;
              return registration.update().then(() => false, () => true);
            });
            evaluation.catch(() => {});
            let failed;
            try {
              failed = await withDeadline(() => evaluation, 10000, engine.name() + ' offline worker update');
            } catch (error) {
              // In roughly 1 of 70 CI updates WebKit's registration job queue stalls permanently
              // without ever requesting the worker script, so no application code runs. Only that
              // exact signature is recovered, once per engine; a dispatched-but-unsettled update
              // (an application bug) still fails.
              const neverDispatched = offlineWorkerFailures === dispatchedBefore;
              if (engine !== webkit || error.name !== 'BrowserDeadlineError' || !neverDispatched || webkitQueueStalls > 0) throw error;
              webkitQueueStalls++;
              console.warn(`PWA ${stage}: WebKit never dispatched the update job; retrying once in a fresh browser`);
              await recoverFromWebKitQueueStall();
              return assertOfflineUpdate();
            }
            assert.equal(failed, true, 'offline update must settle as a failure, not hold the scope job queue');
            if (engine === webkit) assert.ok(offlineWorkerFailures > 0, 'WebKit update reached the HTTP failure fixture');
          };
          const settleBackgroundUpdates = async () => {
            // A navigation schedules a background update check. While a broken deployment is
            // live, WebKit may start reinstalling it after any fixed delay; cutting the transport
            // mid-install makes WebKit retry those fetches and hold the scope job queue. Roll the
            // fixture back to the installed release (byte-identical worker, so no new install can
            // start) and wait until no candidate is installing and fixture traffic has drained.
            release = 'fixture-a-safe'; failure = null;
            const noCandidate = async () => {
              const registration = await navigator.serviceWorker.ready;
              return !registration.installing && !registration.waiting;
            };
            // Require two consecutive idle checks around a quiet window, so a candidate whose
            // worker script was fetched just before the rollback is also observed and settled.
            for (let settled = 0; settled < 2;) {
              await waitForAsync(page, noCandidate, null, { timeout: 15000 });
              await waitForFixtureQuiet();
              settled = await page.evaluate(noCandidate) ? settled + 1 : 0;
            }
          };
          phase(`PWA ${engine.name()}: first offline / online install`);
          // Without a previously installed shell, an offline first visit cannot load.
          await setOffline(true);
          await assert.rejects(page.goto(origin, { timeout: 5000 }));
          phase(`PWA ${engine.name()}: offline first visit rejected`);
          await setOffline(false);
          phase(`PWA ${engine.name()}: fetching initial online document`);
          await page.goto(origin, { waitUntil: 'networkidle' });
          await waitForAsync(page, async () => (await navigator.serviceWorker.getRegistration())?.active?.state === 'activated', null, { timeout: 15000 });
          await page.evaluate(() => navigator.serviceWorker.ready);
          await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
          await assertShell(page, 'fixture-a');
          // Migrate the frozen real v3.2.2 worker online before testing failure-safe future upgrades.
          legacy = false; release = 'fixture-a-safe';
          assert.equal(await updateWorker(page), 'activated');
          await page.waitForFunction(() => window.__pwaRelease === 'fixture-a-safe', null, { timeout: 15000 });
          await assertShell(page, 'fixture-a-safe');
          assert.ok(moduleOriginRequests > 0, 'native module actually requests an Origin variant');
          assert.equal(await page.evaluate(async () => {
            const cache = await caches.open('running-shoes-shell-fixture-a-safe');
            const response = await cache.match('/runtime/feature-lifecycle.mjs?v=fixture-a-safe');
            return response.headers.get('Vary');
          }), 'Origin', 'precache retains the production Vary response header');
          phase(`PWA ${engine.name()}: installed shell ready`);
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
          const apiFailed = await withDeadline(
            () => page.evaluate(() => fetch('/api/test').then(response => response.json()).then(() => false, () => true)),
            10000, engine.name() + ' offline API network probe',
          );
          assert.equal(apiFailed, true, 'offline API must fail instead of using cache');
          if (engine === webkit) assert.ok(offlineApiFailures > 0, 'API request reached the disconnected transport rather than a worker cache');
          await assertOfflineUpdate();
          await setOffline(false);

          for (const [revision, problem] of [['fixture-b', 'http'], ['fixture-c', 'mime'], ['fixture-e', 'disconnect'], ['fixture-f', 'html-version'], ['fixture-g', 'module-mime']]) {
            phase(`PWA ${engine.name()}: reject ${problem} upgrade`);
            release = revision; failure = problem;
            assert.equal(await updateWorker(page), 'redundant', 'incomplete install must not activate');
            await waitForFixtureQuiet();
            // A navigation while a newer deployment exists must not rewrite old HTML.
            await page.reload({ waitUntil: 'networkidle' });
            await assertShell(page, 'fixture-a-safe');
            await settleBackgroundUpdates();
            await setOffline(true);
            await page.reload({ waitUntil: 'networkidle' });
            await assertShell(page, 'fixture-a-safe');
            await assertOfflineUpdate();
            await setOffline(false);
            assert.ok(await page.evaluate(() => caches.has('unrelated-cache')));
            assert.equal(await page.evaluate(name => caches.has(name), 'running-shoes-shell-' + revision), false);
          }
          assert.ok(failedAssets >= 5, 'fixture actually interrupted candidate installs');
          assert.deepEqual([...failedKinds].sort(), ['disconnect', 'html-version', 'http', 'mime', 'module-mime']);

          release = 'fixture-d'; failure = null;
          phase(`PWA ${engine.name()}: reconnect and activate complete upgrade`);
          let releaseCandidate, markStarted;
          candidateGate = new Promise(resolve => { releaseCandidate = resolve; });
          const started = new Promise(resolve => { markStarted = resolve; }); candidateStarted = markStarted;
          await page.evaluate(() => { navigator.serviceWorker.getRegistration().then(reg => reg.update()).catch(() => {}); });
          await withDeadline(() => started, 15000, 'candidate install begins');
          assert.equal(await page.evaluate(async () => (await navigator.serviceWorker.getRegistration()).installing?.state), 'installing');
          await page.evaluate(() => { window.__workerUpdateTimeline = null; });
          const observing = page.evaluate(observeWorkerUpdate, { trigger: false });
          await page.waitForFunction(() => window.__workerUpdateTimeline?.length > 0);
          releaseCandidate(); candidateGate = null;
          assert.equal(await withDeadline(() => observing, 20000, 'already installing candidate'), 'activated');
          await page.waitForFunction(() => window.__pwaRelease === 'fixture-d', null, { timeout: 15000 });
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
          console.log(`PASS ${engine.name()} PWA: legacy migration, bounded offline worker failure and queued-update recovery, first/installed offline with CORS Vary/Origin module requests, HTTP/MIME/disconnect/revision failed upgrades, immutable shell, recovery, API exclusion and scoped cleanup`);
        }, 120000, 'PWA engine ' + engine.name());
      } catch (error) {
        error.message += '\nPWA fixture: ' + JSON.stringify({ stage, release, failure, networkDown, failedAssets, requests });
        error.stack += '\n' + error.message;
        await saveFailure(context, page, 'pwa-' + engine.name(), error);
        console.error(`PWA ${engine.name()} case failed:`, error);
        throw error;
      } finally { await closeBrowser(context, browser); }
    }
  } finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
