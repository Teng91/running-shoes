// SPEC-025: real DOM regressions, synthetic HTTP responses and no production writes.
const assert = require('node:assert/strict');
const { startArtifacts, saveFailure, closeBrowser } = require('../scripts/browser_artifacts.cjs');
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

async function fixture(browser, url, scenario) {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  await startArtifacts(context);
  await context.addInitScript(() => { localStorage.setItem('token', 'synthetic-review'); localStorage.setItem('username', 'synthetic-review'); });
  const gate = deferred(), started = deferred();
  let km = 0, importCalls = 0, historyCalls = 0;
  let retired = false, nickname = '', shoeWrites = [], runWrites = [], runShoeId = scenario === 'deleted-run' ? 999 : 1;
  if (['deleted-run', 'slow'].includes(scenario)) km = 5;
  const shoe = { id: 1, version: 1, nickname: '', brand: 'Test', model: 'Runner', date: '2026-01-01', size: '', price: 800, orig_price: 1000,
    mileage: 0, expected_mileage: 800, monthly_km: 60, is_retired: false, categories: ['Daily'], discount_percent: 80,
    cost_per_km: null, expected_cost_per_km: 1, usage_percent: 0, remaining_mileage_km: 800 };
  const errors = [];
  await context.route('**/api/**', async route => {
    const request = route.request(), name = new URL(request.url()).pathname;
    let body = [];
    if (name === '/api/runs/1' && request.method() === 'PUT') {
      const payload = request.postDataJSON(); runWrites.push(payload); km = payload.km; runShoeId = payload.shoe_id;
      body = { id: 1, version: 1, ...payload };
    } else if (name === '/api/shoes/1' && request.method() === 'PUT') {
      const payload = request.postDataJSON(); shoeWrites.push(payload);
      if (payload.is_retired !== undefined) retired = payload.is_retired;
      if (payload.nickname !== undefined) nickname = payload.nickname;
      body = { ...shoe, ...payload, is_retired: retired, nickname, version: 2 };
    } else if (name === '/api/runs/import/strava/history') {
      historyCalls++;
      body = importCalls ? [{ id: 1, imported_at: '2026-10-23T00:00:00+00:00', start_date: '2026-09-01', end_date: '2026-09-30', imported_count: 1, imported_km: 5, duplicate_count: 0, unmapped_count: 0, invalid_count: 0 }] : [];
      if (scenario === 'history' && historyCalls === 1) { started.resolve(); await gate.promise; }
    } else if (name === '/api/runs/import/strava/preview') {
      body = { run_count: 1, importable_count: 1, importable_km: 5, duplicate_count: 0,
        gear_groups: [{ gear: 'Synthetic Shoe', suggested_shoe_id: 1, count: 1, km: 5 }] };
    } else if (name === '/api/runs/import/strava' && request.method() === 'POST') {
      importCalls++;
      if (['strava', 'strava-error', 'strava-input'].includes(scenario)) { started.resolve(); await gate.promise; }
      if (scenario === 'strava-error') return route.fulfill({ status: 500, json: { detail: 'Synthetic old import failure' } });
      body = { imported: 1, skipped_unmapped: 0, synced_mileage: 5 };
    } else if (name === '/api/runs' && request.method() === 'POST') {
      km = request.postDataJSON().km; body = { id: 1, version: 0, ...request.postDataJSON() };
    } else if (request.method() !== 'GET') throw Error('Unexpected mutation: ' + name);
    else if (name === '/api/auth/me') body = { username: 'synthetic-review' };
    else if (name === '/api/shoes/active') body = retired ? [] : [{ ...shoe, nickname, mileage: km, version: km ? 2 : 1 }];
    else if (name === '/api/shoes/retired') body = retired ? [{ ...shoe, nickname, is_retired: true, monthly_km: 0, version: 2 }] : [];
    else if (name === '/api/monthly-mileage') body = [{ id: 1, year: 2026, month: 10, km, adjustment_km: 0, version: km ? 1 : 0 }];
    else if (name === '/api/running-goal' && scenario === 'slow') { started.resolve(); await gate.promise; body = { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 }; }
    else if (name === '/api/running-goal') body = { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 };
    else if (name === '/api/running-goal/year') body = { year: Number(new URL(request.url()).searchParams.get('year')), active: false, start_year: 2026, months: [] };
    else if (name === '/api/runs') body = km ? [{ id: 1, version: 0, date: '2026-10-01', km, shoe_id: runShoeId }] : [];
    else if (name === '/api/runs/summary') body = { total_km: km, run_count: km ? 1 : 0, run_days: km ? 1 : 0, calendar: [], shoe_usage: [] };
    else if (name === '/api/analytics/dashboard') body = {};
    await route.fulfill({ json: body });
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  try {
    await page.clock.setFixedTime(new Date('2026-10-23T12:00:00Z'));
    await page.goto(url, { waitUntil: ['history', 'slow'].includes(scenario) ? 'domcontentloaded' : 'networkidle' });
    await page.locator('#app-boot').waitFor({ state: 'hidden' });
    if (scenario === 'slow') {
      await started.promise;
      await page.locator('#run-table').getByText('5.00 km', { exact: true }).waitFor();
      assert.equal(await page.locator('#app-boot').isHidden(), true, 'slow goals cannot hide ready runs');
      gate.resolve(); await page.waitForFunction(() => activeHttpRequests.size === 0);
    } else if (scenario === 'deleted-run') {
      await page.locator('#run-table .btn-edit').first().click();
      assert.equal(await page.locator('#edit-run-shoe').inputValue(), '');
      await page.locator('#edit-run-km').fill('6');
      await page.clock.setFixedTime(new Date('2026-10-24T12:00:00Z'));
      await page.evaluate(() => window.dispatchEvent(new Event('focus')));
      assert.equal(await page.locator('#edit-run-shoe').inputValue(), '');
      await page.locator('#run-modal .btn-primary').click();
      assert.equal(runWrites.length, 0, 'blank replacement cannot write or transfer mileage');
      assert.equal(await page.locator('#edit-run-km').inputValue(), '6');
      await page.locator('#edit-run-shoe').selectOption('1');
      await page.locator('#run-modal .btn-primary').click();
      await page.waitForFunction(() => !runController.editor);
      assert.equal(runWrites[0].shoe_id, 1);
    } else if (scenario === 'move') {
      await page.evaluate(() => switchTab('shoes'));
      await page.locator('#shoe-table .btn-edit').first().click();
      await page.locator('#f-nickname').fill('unsaved nickname before move');
      await page.locator('#btn-move').click();
      await page.waitForFunction(() => !shoeModal.saving);
      assert.equal(await page.locator('#modal').isVisible(), true);
      assert.equal(await page.locator('#f-nickname').inputValue(), 'unsaved nickname before move');
      assert.equal(retired, true); assert.equal(nickname, '');
      assert.equal(shoeWrites.length, 1); assert.equal(shoeWrites[0].nickname, undefined);
      await page.locator('#modal .btn-primary').click();
      await page.locator('#modal').waitFor({ state: 'hidden' });
      assert.deepEqual(shoeWrites[1], { nickname: 'unsaved nickname before move', expected_version: 2 });
      assert.equal(retired, true);
    } else {
      const chooseFile = async name => {
        await page.locator('#strava-file').setInputFiles({ name, mimeType: 'text/csv', buffer: Buffer.from('Activity ID,Activity Date,Activity Type,Distance,Gear\n1,2026-09-01,Run,5,Synthetic Shoe\n') });
        await page.waitForFunction(() => stravaController.state.preview && stravaController.state.key.startsWith(document.getElementById('strava-file').files[0].name + '|'));
      };
      if (scenario === 'history') await started.promise;
      await page.getByRole('button', { name: /匯入 Strava/ }).click();
      await chooseFile('first.csv'); await page.locator('#strava-import-btn').click();
      if (scenario === 'history') {
        await page.waitForFunction(() => coreData.stravaImports.length === 1);
        gate.resolve();
        await page.waitForFunction(() => activeHttpRequests.size === 0);
        assert.equal(await page.evaluate(() => coreData.stravaImports.length), 1);
        await page.getByRole('button', { name: /匯入 Strava/ }).click();
        assert.equal(await page.locator('#strava-start-date').inputValue(), '2026-10-01');
        assert.equal(importCalls, 1); assert.equal(historyCalls, 2);
        console.log('PASS', browser.browserType().name(), 'SPEC-025 history retains committed import after older GET');
        assert.deepEqual(errors, []); return;
      }
      await started.promise;
      if (scenario !== 'strava-input') {
        await page.locator('#strava-modal').getByRole('button', { name: '取消', exact: true }).click();
        await page.getByRole('button', { name: /匯入 Strava/ }).click();
      }
      await chooseFile('second.csv');
      if (scenario === 'strava-input') {
        await page.evaluate(() => importStrava());
        assert.equal(importCalls, 1, 'pending import cannot be duplicated by a new preview');
      }
      assert.equal(await page.locator('#strava-modal').isVisible(), true);
      assert.equal(await page.evaluate(() => document.getElementById('strava-file').files[0].name), 'second.csv');
      gate.resolve();
      await page.waitForFunction(() => activeHttpRequests.size === 0);
      assert.equal(await page.locator('#strava-modal').isVisible(), true);
      assert.equal(await page.evaluate(() => stravaController.state.preview.run_count), 1);
      assert.equal(await page.evaluate(() => document.getElementById('strava-file').files[0].name), 'second.csv');
      assert.equal(await page.locator('#strava-import-btn').isEnabled(), true);
      assert.equal(importCalls, 1);
      assert.equal(await page.locator('#strava-error').isVisible(), false, 'old failure cannot write into new preview');
    }
    assert.deepEqual(errors, []);
    console.log('PASS', browser.browserType().name(), 'SPEC-025', scenario);
  } catch (error) { await saveFailure(context, page, 'strava-ownership-' + scenario + '-' + browser.browserType().name(), error); throw error; }
  finally { gate.resolve(); await closeBrowser(context); }
}

module.exports = async function checkStravaOwnership(browser, baseUrl) {
  for (const scenario of ['deleted-run', 'move', 'strava', 'strava-error', 'strava-input', 'history', 'slow']) await fixture(browser, baseUrl, scenario);
};
