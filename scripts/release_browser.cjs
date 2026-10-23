// Anonymous, read-only deployment smoke. No account, token or production mutations.
const { chromium, webkit } = require('playwright');
const assert = require('node:assert/strict');
const { startArtifacts, saveFailure, closeBrowser, withDeadline } = require('./browser_artifacts.cjs');
const [origin, version, cacheName] = process.argv.slice(2);

(async () => {
  for (const engine of [chromium, webkit]) {
    let browser, context, page;
    try {
      await withDeadline(async () => {
        browser = await engine.launch({ headless: true, timeout: 30000 });
        context = await browser.newContext({ viewport: { width: 390, height: 844 } });
        await startArtifacts(context);
        const blockedWrites = [];
        await context.route('**/*', route => {
          if (!['GET', 'HEAD'].includes(route.request().method())) {
            blockedWrites.push(route.request().method());
            return route.abort('blockedbyclient');
          }
          return route.continue();
        });
        page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(origin, { waitUntil: 'networkidle', timeout: 45000 });
        await page.locator('#app-boot').waitFor({ state: 'hidden', timeout: 30000 });
        await page.locator('#login-form').waitFor({ state: 'visible' });
        assert.equal(await page.locator('meta[name="app-asset-version"]').getAttribute('content'), version);
        assert.equal(await page.locator('#app-version').textContent(), 'v' + version);
        await page.waitForFunction(() => !!navigator.serviceWorker.controller, null, { timeout: 45000 });
        const state = await page.evaluate(async ({ cacheName, version }) => {
          const names = await caches.keys(), cache = await caches.open(cacheName);
          const requests = await cache.keys();
          return { names, runtime: !!await cache.match('/runtime/feature-lifecycle.mjs?v=' + version),
            hasPrivateData: requests.some(request => new URL(request.url).pathname.startsWith('/api/')),
            runtimeReady: typeof featureLifecycle?.reset === 'function' };
        }, { cacheName, version });
        assert.deepEqual(state.names.filter(name => name.startsWith('running-shoes-shell-')), [cacheName]);
        assert(state.runtime); assert(state.runtimeReady); assert.equal(state.hasPrivateData, false);
        if (engine === chromium) {
          await context.setOffline(true);
          await page.reload({ waitUntil: 'networkidle' });
          await page.locator('#app-boot').waitFor({ state: 'hidden' });
          await page.locator('#login-form').waitFor({ state: 'visible' });
          assert.equal(await page.locator('meta[name="app-asset-version"]').getAttribute('content'), version);
        }
        assert.deepEqual(errors, []);
        assert.deepEqual(blockedWrites, [], 'anonymous release check must never write to the server');
        console.log(`PASS release ${engine.name()} v${version}: anonymous mobile boot/runtime/cache${engine === chromium ? '/offline reload' : ''}`);
      }, 90000, 'release engine ' + engine.name());
    } catch (error) {
      await saveFailure(context, page, 'release-' + engine.name(), error);
      throw error;
    } finally { await closeBrowser(context, browser); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
