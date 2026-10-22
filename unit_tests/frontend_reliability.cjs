// SPEC-019: real same-origin tabs; isolated mock APIs, no external account writes.
const assert = require('node:assert/strict');
const { startArtifacts, saveFailure } = require('../scripts/browser_artifacts.cjs');

module.exports = async function checkReliability(browser, baseUrl) {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  await startArtifacts(context);
  let failRuns = false;
  await context.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/runs' && failRuns) return route.fulfill({ status: 503, json: {} });
    let body = [];
    if (path === '/api/auth/me') body = { username: 'synthetic-A' };
    if (path === '/api/running-goal') body = { start_year: 2026, monthly_km: 125, yearly_km: 1500, version: 0 };
    if (path === '/api/runs/summary') body = { total_km: 0, run_count: 0, run_days: 0, calendar: [], shoe_usage: [] };
    if (path === '/api/analytics/dashboard') body = {};
    return route.fulfill({ json: body });
  });
  const a = await context.newPage(), b = await context.newPage(), errors = [];
  for (const page of [a, b]) page.on('pageerror', error => errors.push(error.message));
  try {
    await a.goto(baseUrl, { waitUntil: 'networkidle' });
    await a.locator('#app-boot').waitFor({ state: 'hidden' });
    await a.evaluate(async () => { setAuth('synthetic-A', 'synthetic-A'); showAppView(); await loadData(); });
    await b.goto(baseUrl, { waitUntil: 'networkidle' });
    await b.locator('#app-boot').waitFor({ state: 'hidden' });
    await b.evaluate(() => {
      const original = window.fetch;
      window.fetch = (url, options) => String(url).includes('synthetic-pending') ? new Promise(() => {}) : original(url, options);
      window.oldRead = apiGet('/synthetic-pending').catch(error => error.name);
    });
    await a.evaluate(() => handleLogout());
    await b.locator('#login-form').waitFor({ state: 'visible' });
    assert.equal(await b.evaluate(() => authToken), null);
    assert.equal(await b.evaluate(() => window.oldRead), 'AbortError');
    await a.evaluate(async () => { setAuth('synthetic-A', 'synthetic-A'); showAppView(); await loadData(); });
    await b.reload({ waitUntil: 'networkidle' });
    await b.locator('#app-boot').waitFor({ state: 'hidden' });
    await a.evaluate(() => setAuth('synthetic-B', 'synthetic-B'));
    await b.locator('#login-form').waitFor({ state: 'visible' });
    assert.equal(await b.evaluate(() => authToken), null);
    assert.equal(await b.evaluate(() => localStorage.getItem('token')), 'synthetic-B', 'invalidation must not erase the other tab login');

    failRuns = true;
    await a.evaluate(async () => { showAppView(); await loadRunsForSelectedMonth(); });
    assert.equal(await a.locator('#run-load-error').isVisible(), true);
    await a.evaluate(() => { document.getElementById('data-load-error').hidden = false; });
    failRuns = false;
    await a.locator('#run-load-error button').click();
    await a.locator('#run-load-error').waitFor({ state: 'hidden' });
    assert.equal(await a.locator('#data-load-error').isVisible(), true, 'local recovery preserves aggregate errors');
    assert.deepEqual(errors, []);
    console.log(`PASS ${browser.browserType().name()} SPEC-019: cross-tab logout/switch, aborted stale reads and independent run retry recovery`);
  } catch (error) {
    await saveFailure(context, a, 'reliability-' + browser.browserType().name(), error);
    throw error;
  } finally { await context.close(); }
};
