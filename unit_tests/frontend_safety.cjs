// Six SPEC-012 regressions against real application modules/DOM and mock I/O.
const assert = require('node:assert/strict');
const { startArtifacts, saveFailure, closeBrowser } = require('../scripts/browser_artifacts.cjs');

async function checkRunLogHome(browser, baseUrl) {
  const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 390, height: 844 } });
  await startArtifacts(context);
  const errors = [], writes = [];
  await context.addInitScript(() => {
    if (localStorage.getItem('home-fixture-seeded')) return;
    localStorage.setItem('home-fixture-seeded', 'true');
    localStorage.setItem('token', 'synthetic-home');
    localStorage.setItem('username', 'home-user');
    localStorage.setItem('activeTab', 'agent');
    localStorage.setItem('theme', 'light');
  });
  await context.route('**/api/**', route => {
    const request = route.request();
    if (request.method() !== 'GET') writes.push(request.method() + ' ' + request.url());
    const pathname = new URL(request.url()).pathname;
    const body = pathname === '/api/auth/me' ? { username: 'home-user' }
      : pathname === '/api/running-goal' ? { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 }
      : pathname === '/api/runs/year-summary' ? { shoes: [] }
      : pathname === '/api/analytics/dashboard' ? {} : [];
    return route.fulfill({ json: body });
  });
  const page = await context.newPage();
  const trackErrors = target => target.on('pageerror', error => errors.push(error.message));
  trackErrors(page);
  const assertHome = async target => {
    await target.locator('#app-view').waitFor({ state: 'visible' });
    await target.locator('#app-boot').waitFor({ state: 'hidden' });
    assert.deepEqual(await target.locator('.tab-panel.active').evaluateAll(nodes => nodes.map(node => node.dataset.panel)), ['runs']);
    assert.equal(await target.locator('.tab.active').getAttribute('data-tab'), 'runs');
    assert.equal(await target.locator('.tab[data-tab="runs"]').getAttribute('aria-selected'), 'true');
    assert.equal(await target.locator('#mobile-page-label').textContent(), '跑步日誌');
    assert.equal(await target.locator('#app-workspace').evaluate(node => node.classList.contains('agent-mode')), false);
    assert.equal(await target.evaluate(() => localStorage.getItem('token')), 'synthetic-home');
    assert.equal(await target.locator('body').evaluate(node => node.classList.contains('light-theme')), true);
  };
  try {
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    await assertHome(page);
    await page.locator('.mobile-menu-toggle').click();
    await page.locator('.tab[data-tab="agent"]').click();
    assert.equal(await page.locator('.tab-panel.active').getAttribute('data-panel'), 'agent');
    assert.equal(await page.locator('#sidebar-menu').evaluate(node => node.classList.contains('menu-open')), false);
    await page.reload({ waitUntil: 'networkidle' });
    await assertHome(page);
    await page.evaluate(() => {
      switchTab('monthly');
      // A normal pageshow / foreground transition must leave the selected page alone.
      window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: false }));
    });
    assert.equal(await page.locator('.tab-panel.active').getAttribute('data-panel'), 'monthly');
    assert.equal(await page.evaluate(() => localStorage.getItem('activeTab')), 'agent', 'switching tabs leaves the legacy key untouched');
    await page.evaluate(() => {
      switchTab('agent');
      window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
    });
    await assertHome(page);
    await page.evaluate(() => switchTab('agent'));
    const reopened = await context.newPage();
    trackErrors(reopened);
    await page.close();
    await reopened.goto(baseUrl, { waitUntil: 'networkidle' });
    await assertHome(reopened);
    assert.deepEqual(writes, [], 'home navigation must never mutate data or send AI messages');
    assert.deepEqual(errors, []);
    console.log(`PASS ${browser.browserType().name()} SPEC-015: legacy tab ignored, reload/reopen home, restored-page lifecycle, mobile/ARIA and session/theme preservation`);
  } catch (error) {
    await saveFailure(context, context.pages().at(-1), 'home-' + browser.browserType().name(), error);
    throw error;
  } finally { await closeBrowser(context); }
}

module.exports = async function checkFrontendSafety(browser, baseUrl) {
  await checkRunLogHome(browser, baseUrl);
  const context = await browser.newContext({ serviceWorkers: 'block' });
  await startArtifacts(context);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    await page.evaluate(async () => {
      const check = (condition, label) => { if (!condition) throw new Error(label); };
      const frame = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const json = body => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
      const event = body => 'data: ' + JSON.stringify(body) + '\n\n';
      const stream = body => new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
      const done = event({ type: 'done', model: 'mock', updated_at: '2026-10-01T00:00:00Z' });
      const token = text => event({ type: 'token', text });
      setAuth('synthetic-safety', 'safety-user');
      const created = [];
      const OriginalChart = Chart;
      Chart = new Proxy(Chart, { construct(target, args) {
        created.push(args[0].id);
        return Reflect.construct(target, args);
      } });
      Chart.defaults.animation = false;
      let annualReads = 0, trendReads = 0;
      window.fetch = async url => {
        if (String(url).includes('/runs/year-summary?')) { annualReads++; return json({ shoes: [] }); }
        if (String(url).includes('/analytics/trends?')) {
          trendReads++;
          return json({ year: 2026, end_date: '2026-01-31', thresholds: { spike_percent: 30 }, daily: [],
            streaks: { longest_days: 0, current_days: 0 }, weekly: [],
            cumulative: { goal_active: false, actual_km: [], goal_km: [], ytd_km: 0 } });
        }
        if (String(url).includes('/analytics/shoe-timeline')) return json({ as_of: '2026-01-31', idle_days: 30, shoes: [] });
        if (String(url).includes('/analytics/shoe-distance-mix')) return json({ buckets: ['<5'], shoes: [] });
        if (String(url).includes('/analytics/year-review?')) return json({ year: 2026, end_date: '2026-01-31', complete: false, has_runs: false });
        if (String(url).includes('/analytics/home')) return json({ as_of: '2026-01-31', suggestion: [] });
        return json({});
      };
      applyCoreResource('shoes', [[{ id: 1, brand: 'Test', model: 'Safety', date: '2026-01-01', size: 'US 9',
        price: 3000, orig_price: 5000, mileage: 300, expected_mileage: 900, monthly_km: 60,
        categories: ['Daily'], forecast_retirement_date: '2027-04-17', forecast_source: 'recent_90_days', forecast_monthly_km: 101.46 }], []]);
      applyCoreResource('monthly', [{ id: 10, year: 2026, month: 1, km: 100, version: 0, adjustment_km: 100 }]);
      showAppView();
      await frame();
      check(!created.includes('chart-progress') && !created.includes('chart-monthly-year'), 'initial runs must not build hidden charts');
      check(annualReads === 0, 'initial runs must not read annual logs');
      switchTab('monthly'); await frame();
      check(annualReads === 1 && created.includes('chart-shoe-stacked'), 'monthly lazily loads annual logs');
      const count = created.length;
      switchTab('runs'); await frame(); switchTab('monthly'); await frame();
      check(created.length === count && annualReads === 1 && trendReads === 1, 'unchanged tabs reuse charts and annual data');
      switchTab('runs'); await frame();
      toggleTheme();
      check(created.slice(count).every(id => id === 'chart-run-shoes'), 'theme only redraws visible charts');
      const afterTheme = created.length;
      render();
      check(created.slice(afterTheme).every(id => id === 'chart-run-shoes'), 'data render must leave hidden charts untouched');

      // A late annual read must not construct a chart after leaving monthly.
      switchTab('monthly'); await frame();
      resourceStore.invalidate(['annual-summary']);
      let finishAnnual;
      window.fetch = url => String(url).includes('/runs/year-summary?')
        ? new Promise(resolve => { finishAnnual = resolve; }) : Promise.resolve(json({}));
      const pending = renderShoeStackedChart();
      switchTab('runs'); await frame();
      const beforeFinish = created.length;
      finishAnnual(json({ shoes: [] })); await pending;
      check(created.length === beforeFinish, 'late monthly response cannot paint hidden panel');
      switchTab('monthly'); await frame();
      check(created.includes('chart-shoe-stacked') && resourceStore.peek('annual-summary'), 'return to monthly recovers from cached result');
      Chart = OriginalChart;

      setAuth('synthetic-stream', 'stream-user');
      const input = document.getElementById('agent-input');
      input.value = 'first question';
      window.fetch = async () => stream(token('partial answer'));
      await sendAgentMessage();
      check(agentHistory.length === 0 && document.getElementById('agent-messages').textContent.includes('內容不完整'), 'incomplete EOF is not history');
      let sent;
      window.fetch = async (_, options) => { sent = JSON.parse(options.body); return stream(token('complete answer') + done); };
      await sendAgentMessage(lastUserText);
      check(sent.history.length === 0 && agentHistory.length === 2, 'retry stores exactly one complete pair');
      input.value = 'second question';
      window.fetch = async () => stream(token('partial failure') + event({ type: 'error', text: 'model failed' }) + done);
      await sendAgentMessage();
      check(agentHistory.length === 2 && document.getElementById('agent-messages').textContent.includes('model failed'), 'server error never commits an answer');
      input.value = 'third question';
      window.fetch = async () => stream(new ReadableStream({ start(controller) {
        controller.enqueue(new TextEncoder().encode(token('network partial')));
        setTimeout(() => controller.error(new TypeError('network interrupted')), 0);
      } }));
      await sendAgentMessage();
      check(agentHistory.length === 2 && document.getElementById('agent-messages').textContent.includes('network partial'), 'network failure retains visible partial but not history');
      check(!input.disabled, 'failed streams unlock the input');

      document.getElementById('report-month').value = '2026-09';
      document.getElementById('report-model').innerHTML = '<option value="mock">mock</option>';
      window.fetch = async () => stream(token('report partial'));
      await generateReport();
      check(document.getElementById('report-status').textContent.includes('未儲存'), 'report EOF is not saved');
      window.fetch = async url => String(url).endsWith('/generate') ? stream(token('report complete') + done) : json([]);
      await generateReport();
      check(document.getElementById('report-status').textContent.includes('報告已儲存'), 'report completion semantics retained');
      check(!document.getElementById('generate-report-btn').disabled, 'report controls unlock');
    });
    await page.evaluate(async () => {
      const check = (condition, label) => { if (!condition) throw new Error(label); };
      const json = body => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
      const tick = () => new Promise(resolve => setTimeout(resolve, 0));
      // Exercise actual lifecycle functions with a transport that ignores cancellation.
      loadData = async () => {};
      loadAgentModels = async () => {};
      handleLogout();
      document.getElementById('login-username').value = 'A';
      document.getElementById('login-password').value = 'mock-pass';
      let finishBody, calls = 0;
      window.fetch = async () => {
        calls++;
        const response = json({});
        response.json = () => new Promise(resolve => { finishBody = resolve; });
        return response;
      };
      const oldLogin = handleLogin(); await tick(); await handleLogin();
      check(calls === 1 && document.querySelector('#login-form button[type="submit"]').disabled, 'duplicate login is locked');
      handleLogout();
      document.getElementById('login-username').value = 'B';
      document.getElementById('login-password').value = 'mock-pass';
      window.fetch = async () => json({ access_token: 'mock-B' });
      await handleLogin();
      finishBody({ access_token: 'mock-A' }); await oldLogin;
      check(currentUser === 'B' && authToken === 'mock-B', 'late login body cannot replace B');
      check(!document.querySelector('#login-form button[type="submit"]').disabled, 'login controls recover');

      const first = { id: 1, version: 3, brand: 'Test', model: 'A', date: '2026-01-01',
        mileage: 10, expected_mileage: 800, monthly_km: 60, categories: ['Daily'] };
      for (const action of ['submit', 'delete', 'move']) {
        for (const fails of [false, true]) {
          let finish, writes = 0, alerts = 0;
          window.confirm = () => true;
          window.alert = () => alerts++;
          window.fetch = (_, options) => {
            writes++;
            if (options.body) check(JSON.parse(options.body).expected_version === 3, 'original shoe version retained');
            return new Promise(resolve => { finish = resolve; });
          };
          shoeModal.openForEdit(first, false);
          const pending = shoeModal[action](); await shoeModal[action]();
          check(writes === 1 && document.getElementById('btn-delete').disabled, 'shoe mutation uses one snapshot lock');
          shoeModal.close();
          shoeModal.openForEdit({ ...first, id: 2, model: 'B' }, false);
          document.getElementById('f-model').value = 'B unsaved draft';
          const replacement = shoeModal.context;
          finish(fails ? new Response('{"detail":"old error"}', { status: 409 }) : json({}));
          await pending;
          check(shoeModal.context === replacement && document.getElementById('modal').classList.contains('active'), 'old shoe response cannot close B');
          check(document.getElementById('f-model').value === 'B unsaved draft' && alerts === 0, 'B draft and error state preserved');
          check(!document.querySelector('#modal .btn-primary').disabled, 'B controls remain unlocked');
        }
      }
      const timestamp = '2026-10-20T00:30:00+00:00';
      renderReport({ year: 2026, month: 9, model: 'mock', content_md: 'mock', updated_at: timestamp });
      check(document.getElementById('report-status').textContent.endsWith(formatLocalTimestamp(timestamp)), 'saved report uses local timestamp');
      handleLogout();
      check(shoeModal.context === null, 'logout resets shoe snapshot');
    });
    assert.deepEqual(errors, [], 'safety browser JavaScript errors');
    console.log(`PASS ${browser.browserType().name()} SPEC-012: lazy charts, stale reads, modal identity, AI/report stream completion/retry/errors`);
    console.log(`PASS ${browser.browserType().name()} SPEC-013: login races, shoe mutations, report timestamps and split modules`);
  } catch (error) {
    await saveFailure(context, page, 'safety-' + browser.browserType().name(), error);
    throw error;
  } finally { await closeBrowser(context); }
};
