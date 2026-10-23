// SPEC-024: real DOM state transitions with synthetic, session-scoped API data.
const assert = require('node:assert/strict');
const { startArtifacts, saveFailure, closeBrowser } = require('../scripts/browser_artifacts.cjs');

module.exports = async function checkDrafts(browser, baseUrl) {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  let page;
  try {
    await startArtifacts(context);
    await context.addInitScript(() => {
      localStorage.setItem('token', 'synthetic-drafts');
      localStorage.setItem('username', 'drafts-user');
    });
    let shoe = { id: 7, brand: 'Test', model: 'Runner', nickname: '', date: '2026-01-01',
      size: '', price: 1000, orig_price: 2000, mileage: 50, expected_mileage: 800,
      monthly_km: 60, is_retired: false, version: 3, categories: ['Daily'],
      discount_percent: 50, cost_per_km: 20, expected_cost_per_km: 1.25,
      usage_percent: 6.25, remaining_mileage_km: 750 };
    let goal = { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 };
    const shoeWrites = [], goalWrites = [], errors = [];
    let holdShoe, holdGoal, shoeStarted, goalStarted;
    const shoeGate = new Promise(resolve => { holdShoe = resolve; });
    const goalGate = new Promise(resolve => { holdGoal = resolve; });
    const shoePending = new Promise(resolve => { shoeStarted = resolve; });
    const goalPending = new Promise(resolve => { goalStarted = resolve; });
    await context.route('**/api/**', async route => {
      const request = route.request(), name = new URL(request.url()).pathname;
      let body = [];
      if (request.method() === 'PUT' && name === '/api/shoes/7') {
        const payload = request.postDataJSON(); shoeWrites.push(payload);
        assert.equal(payload.expected_version, shoe.version);
        if (shoeWrites.length === 1) { shoeStarted(); await shoeGate; }
        shoe = { ...shoe, ...payload, version: shoe.version + 1 }; body = shoe;
      } else if (request.method() === 'PUT' && name === '/api/running-goal') {
        const payload = request.postDataJSON(); goalWrites.push(payload);
        assert.equal(payload.expected_version, goal.version);
        if (goalWrites.length === 1) { goalStarted(); await goalGate; }
        goal = { ...goal, ...payload, yearly_km: payload.monthly_km * 12, version: goal.version + 1 }; body = goal;
      } else if (request.method() !== 'GET') throw Error('Unexpected fixture mutation: ' + name);
      else if (name === '/api/auth/me') body = { username: 'drafts-user' };
      else if (name === '/api/shoes/active') body = shoe.is_retired ? [] : [shoe];
      else if (name === '/api/shoes/retired') body = shoe.is_retired ? [shoe] : [];
      else if (name === '/api/running-goal') body = goal;
      else if (name === '/api/running-goal/progress') body = { active: false, start_year: 2026 };
      else if (name === '/api/runs/year-summary') body = { shoes: [] };
      else if (name === '/api/runs/summary') body = { calendar: [], shoe_usage: [], total_km: 0, run_count: 0, run_days: 0 };
      else if (name === '/api/analytics/dashboard') body = {};
      return route.fulfill({ json: body });
    });
    page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    await page.locator('#app-boot').waitFor({ state: 'hidden' });
    // Hold the first panel frame so typing before its render is deterministic.
    await page.evaluate(() => {
      const frames = [], original = window.requestAnimationFrame;
      window.requestAnimationFrame = callback => { frames.push(callback); return 0; };
      switchTab('monthly');
      window.requestAnimationFrame = original;
      window.__resumeGoalPanel = () => frames.forEach(callback => callback(performance.now()));
    });
    await page.locator('#goal-monthly-km').fill('180');
    await page.locator('#goal-start-year').focus();
    await page.evaluate(() => { window.__resumeGoalPanel(); toggleTheme(); });
    assert.equal(await page.locator('#goal-monthly-km').inputValue(), '180', 'blurred goal draft survives theme redraw');
    await page.locator('#save-goal-btn').click(); await goalPending;
    await page.locator('#goal-monthly-km').fill('200');
    await page.locator('#goal-start-year').focus();
    await page.evaluate(() => toggleTheme());
    holdGoal();
    await page.waitForFunction(() => !document.getElementById('save-goal-btn').disabled);
    assert.equal(goal.monthly_km, 180);
    assert.equal(await page.locator('#goal-monthly-km').inputValue(), '200');
    await page.locator('#save-goal-btn').click();
    await page.waitForFunction(() => !document.getElementById('save-goal-btn').disabled);
    assert.equal(goal.monthly_km, 200);
    assert.equal(goalWrites[1].expected_version, 1);

    await page.evaluate(() => switchTab('shoes'));
    await page.locator('#shoe-table .btn-edit').first().click();
    await page.locator('#btn-move').click(); await shoePending;
    await page.locator('#f-nickname').fill('new nickname draft'); holdShoe();
    await page.waitForFunction(() => !shoeModal.saving);
    assert.equal(await page.locator('#modal').isVisible(), true);
    assert.equal(await page.locator('#btn-move').textContent(), '移至現役');
    assert.equal(await page.locator('#f-monthly').inputValue(), '0');
    assert.equal(shoe.is_retired, true);
    await page.locator('#modal .btn-primary').click();
    await page.locator('#modal').waitFor({ state: 'hidden' });
    assert.deepEqual(shoeWrites[1], { nickname: 'new nickname draft', expected_version: 4 });
    assert.equal(shoe.is_retired, true); assert.equal(shoe.monthly_km, 0);
    assert.deepEqual(errors, []);
    console.log(`PASS ${browser.browserType().name()} SPEC-024: blurred goal drafts, pending goal edits and retirement followed by nickname save`);
  } catch (error) {
    await saveFailure(context, page, 'drafts-' + browser.browserType().name(), error);
    throw error;
  } finally { await closeBrowser(context); }
};
