// Six SPEC-012 regressions against real application modules/DOM and mock I/O.
const assert = require('node:assert/strict');

module.exports = async function checkFrontendSafety(browser, baseUrl) {
  const context = await browser.newContext({ serviceWorkers: 'block' });
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
      let annualReads = 0;
      window.fetch = async url => {
        if (String(url).includes('/runs?')) { annualReads++; return json([]); }
        return json({});
      };
      shoes = [{ id: 1, brand: 'Test', model: 'Safety', date: '2026-01-01', size: 'US 9',
        price: 3000, orig_price: 5000, mileage: 300, expected_mileage: 900, monthly_km: 60,
        categories: ['Daily'], forecast_retirement_date: '2027-04-17', forecast_source: 'recent_90_days', forecast_monthly_km: 101.46 }];
      monthlyMileages = [{ id: 10, year: 2026, month: 1, km: 100, version: 0, adjustment_km: 100 }];
      showAppView();
      await frame();
      check(!created.includes('chart-progress') && !created.includes('chart-monthly-year'), 'initial runs must not build hidden charts');
      check(annualReads === 0, 'initial runs must not read annual logs');
      switchTab('monthly'); await frame();
      check(annualReads === 1 && created.includes('chart-shoe-stacked'), 'monthly lazily loads annual logs');
      const count = created.length;
      switchTab('runs'); await frame(); switchTab('monthly'); await frame();
      check(created.length === count && annualReads === 1, 'unchanged tabs reuse charts and annual data');
      switchTab('runs'); await frame();
      toggleTheme();
      check(created.slice(count).every(id => id === 'chart-run-shoes'), 'theme only redraws visible charts');
      const afterTheme = created.length;
      render();
      check(created.slice(afterTheme).every(id => id === 'chart-run-shoes'), 'data render must leave hidden charts untouched');

      // A late annual read must not construct a chart after leaving monthly.
      switchTab('monthly'); await frame();
      yearlyRunsCache.clear();
      let finishAnnual;
      window.fetch = url => String(url).includes('/runs?')
        ? new Promise(resolve => { finishAnnual = resolve; }) : Promise.resolve(json({}));
      const pending = renderShoeStackedChart();
      switchTab('runs'); await frame();
      const beforeFinish = created.length;
      finishAnnual(json([])); await pending;
      check(created.length === beforeFinish, 'late monthly response cannot paint hidden panel');
      switchTab('monthly'); await frame();
      check(created.includes('chart-shoe-stacked') && yearlyRunsCache.has(2026), 'return to monthly recovers from cached result');
      Chart = OriginalChart;

      // A reordered list must not change the month captured by the modal.
      editMonthlyMileage(0);
      monthlyMileages = [{ id: 20, year: 2026, month: 2, km: 200, version: 4, adjustment_km: 200 }];
      let write;
      window.fetch = async (url, options) => {
        write = { url: String(url), payload: JSON.parse(options.body) };
        return new Response('{"detail":"deleted"}', { status: 404 });
      };
      await saveMonthlyMileage();
      check(write.url.endsWith('/monthly-mileage/10') && write.payload.expected_version === 0, 'modal submitted original identity/version');
      check(document.getElementById('monthly-error').textContent.includes('deleted'), 'deleted original remains a visible error');
      closeMonthlyModal();

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
  } finally { await context.close(); }
};
