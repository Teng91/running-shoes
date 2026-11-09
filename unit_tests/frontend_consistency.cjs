// SPEC-017 real DOM/engines with isolated API fixtures. Never contacts production.
const assert = require('node:assert/strict');
const { startArtifacts, saveFailure, closeBrowser } = require('../scripts/browser_artifacts.cjs');

module.exports = async function checkConsistency(browser, baseUrl) {
  const context = await browser.newContext({ serviceWorkers: 'block', timezoneId: 'America/Los_Angeles' });
  await startArtifacts(context);
  await context.addInitScript(() => {
    localStorage.setItem('token', 'synthetic-consistency');
    localStorage.setItem('username', 'consistency-user');
  });
  const shoe = { id: 1, brand: 'Test', model: 'Calendar', date: '2026-03-01', price: 800,
    orig_price: 1000, mileage: 205, expected_mileage: 800, monthly_km: 60, categories: ['Daily'],
    discount_percent: 80, cost_per_km: 3.9, expected_cost_per_km: 1, usage_percent: 25.625, remaining_mileage_km: 595 };
  const runs = Array.from({ length: 205 }, (_, id) => ({ id: id + 1, shoe_id: 1, date: '2026-08-05', km: 1 }));
  const goal = { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 };
  const progress = { ...goal, active: true, month_km: 50, ytd_km: 50,
    month_achievement_percent: 40, year_achievement_percent: 3.3, year_remaining_km: 1450,
    month_state: 'past', month_remaining_km: 75 };
  const errors = [], writes = []; let spendingCalls = 0;
  await context.route('**/api/**', route => {
    const request = route.request(), url = new URL(request.url()), name = url.pathname;
    if (request.method() !== 'GET') writes.push(name);
    let body = [];
    if (name === '/api/auth/me') body = { username: 'consistency-user' };
    else if (name === '/api/shoes/active') body = [shoe];
    else if (name === '/api/monthly-mileage') body = [{ id: 1, year: 2026, month: 8, km: 150, adjustment_km: 100, version: 0 }];
    else if (name === '/api/running-goal') body = goal;
    else if (name === '/api/running-goal/progress') body = progress;
    else if (name === '/api/runs/year-summary') body = { shoes: [] };
    else if (name === '/api/analytics/dashboard') body = { goal: progress };
    else if (name === '/api/runs') {
      const rows = url.searchParams.get('month') === '8' || !url.searchParams.has('month') ? runs : [];
      const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 500);
      body = rows.slice(offset, offset + limit);
    } else if (name === '/api/runs/summary') {
      const month = Number(url.searchParams.get('month'));
      body = { year: 2026, month, total_km: month === 8 ? 205 : 0, run_count: month === 8 ? 205 : 0,
        run_days: month === 8 ? 1 : 0, shoe_usage: month === 8 ? [{ shoe_id: 1, km: 205, count: 205 }] : [],
        calendar: month === 8 ? [{ date: '2026-08-05', km: 205, count: 205, shoes: [{ shoe_id: 1, km: 205, count: 205 }] }] : [] };
    } else if (name === '/api/spending/summary') {
      if (++spendingCalls <= 2) return route.fulfill({ status: 503, json: { detail: 'synthetic-unavailable' } });
      body = { total_paid: 800, total_original: 1000, savings: 200, average_discount_percent: 80,
        average_monthly_paid: 100, start_month: '2026-03', month_span: 8,
        highest_month: { year: 2026, month: 3, total_paid: 800 },
        monthly: [{ year: 2026, month: 3, total_paid: 800, total_orig: 1000 }] };
    }
    return route.fulfill({ json: body });
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.clock.install({ time: new Date('2026-10-19T12:00:00Z') });
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    await page.locator('#app-boot').waitFor({ state: 'hidden' });
    assert.equal(spendingCalls, 0, 'home does not fetch spending');
    await page.evaluate(async () => { document.getElementById('run-month').value = '2026-08'; await loadRunsForSelectedMonth(); });
    assert.equal(await page.locator('#run-table tr').count(), 200);
    assert.match(await page.locator('#run-stats').textContent(), /205\.00 km/);
    await page.locator('#run-next').click();
    await page.waitForFunction(() => document.querySelectorAll('#run-table tr').length === 5);
    assert.match(await page.locator('#run-stats').textContent(), /205 次跑步/);
    assert.match(await page.locator('#run-calendar').textContent(), /205\.00 km/);
    await page.locator('.calendar-run').click();
    await page.waitForFunction(() => document.querySelectorAll('#run-table tr').length === 200);
    assert.match(await page.locator('#run-page-label').textContent(), /5 日/);
    await page.locator('#run-date').fill('2026-10-18');
    await page.locator('#run-km').fill('7.50');
    await page.clock.setFixedTime(new Date('2026-10-20T12:00:00Z'));
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    assert.equal(await page.locator('#run-date').getAttribute('max'), '2026-10-20');
    assert.equal(await page.locator('#run-date').inputValue(), '2026-10-18');
    assert.equal(await page.locator('#run-km').inputValue(), '7.50');
    assert.equal(await page.locator('#run-month').inputValue(), '2026-08');
    await page.evaluate(() => switchTab('monthly'));
    await page.waitForFunction(() => document.getElementById('goal-cards').textContent.includes('40.0%'));
    assert.doesNotMatch(await page.locator('#goal-cards').textContent(), /120\.0%/);
    assert.deepEqual(writes, [], 'viewing goals never sends a mutation');
    // SPEC-043: spending loads lazily with the shoes tab.
    await page.evaluate(() => switchTab('shoes'));
    await page.locator('#spending-cards').getByText(/支出載入失敗/).waitFor();
    assert.equal(await page.locator('#data-load-error').isVisible(), false);
    await page.locator('#spending-cards').getByRole('button', { name: '重試' }).click();
    await page.locator('#spending-cards').getByText('從 2026/03 到今月，共 8 個月').waitFor();
    assert.equal(spendingCalls, 3, 'GET retries once before showing a local retry action');
    await page.evaluate(() => setAuth('synthetic-replacement', 'replacement'));
    assert.equal(await page.locator('#spending-table tr').count(), 0, 'logout clears old hidden purchases');
    assert.equal(await page.evaluate(() => featureLifecycle.names().length >= 10), true);
    assert.deepEqual(errors, []);
    console.log(`PASS ${browser.browserType().name()} SPEC-017: complete paged stats/calendar, cross-day drafts, goals, modal keyboard/focus, lazy spending retry/timezone, lifecycle privacy`);
  } catch (error) {
    await saveFailure(context, page, 'consistency-' + browser.browserType().name(), error);
    throw error;
  } finally { await closeBrowser(context); }
};
