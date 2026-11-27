// SPEC-055: correctness fixes that the dashboard, run log and login form render.
const { runContext, test, assert, vm, extract, htmlSource, source, readText } = require('./helpers.cjs');

function nodes() {
  return new Proxy({}, { get: (target, id) => target[id] ||= {
    id, value: '', textContent: '', innerHTML: '', hidden: false, disabled: false, dataset: {}, style: {},
  } });
}
const esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const lifecycleConstants = source.match(/const LIFECYCLE_MONITOR_PERCENT = \d+;\s*const LIFECYCLE_REPLACE_SOON_PERCENT = \d+;/)[0];

test('SPEC-055 every lifespan alert uses the shared 80% watch and 90% replace thresholds', () => {
  const elements = nodes();
  const shoe = (id, usage) => ({ id, brand: 'B', model: `M${id}`, categories: ['Daily'], usage_percent: usage });
  const context = runContext({ document: { getElementById: id => elements[id] }, esc,
    shoes: [shoe(1, 95), shoe(2, 85), shoe(3, 79.9)] });
  vm.runInContext(`${lifecycleConstants}\n${['calc', 'shoeCategories', 'renderAlerts'].map(extract).join('\n')}`, context);
  context.renderAlerts();
  const html = elements['shoe-alerts'].innerHTML;
  assert.match(html, /shoe-alert urgent">\s*<strong>B M1<\/strong>：<span>已使用 95%，可以準備換鞋/);
  assert.match(html, /shoe-alert">\s*<strong>B M2<\/strong>：<span>已使用 85%，開始注意/);
  assert.doesNotMatch(html, /M3/, 'below 80% raises no alert');
  assert.match(lifecycleConstants, /MONITOR_PERCENT = 80;\s*const LIFECYCLE_REPLACE_SOON_PERCENT = 90;/);
  assert.doesNotMatch(extract('renderCards') + extract('renderAlerts'), /lifeProgress >= 0\.[89]/, 'no local copy of the thresholds');
});

test('SPEC-055 run log cards name the selected month instead of this month', () => {
  const elements = nodes();
  const runs = [{ id: 1, date: '2026-09-03', km: 10, shoe_id: 7 }, { id: 2, date: '2026-09-05', km: 5, shoe_id: 7 }];
  const context = runContext({ document: { getElementById: id => elements[id] }, esc,
    selectedRunMonth: () => '2026-09', monthRuns: () => runs, RUN_PAGE_SIZE: 200,
    runController: { state: { summary: null, offset: 0, hasMore: false, day: null } },
    runShoe: id => ({ id, brand: 'Mizuno', model: 'Neo' }), shoeColor: () => '#000',
    renderStravaStatus() {}, renderRunCalendar() {}, renderRunShoeChart() {}, loadDashboardAnalytics() {} });
  vm.runInContext(extract('renderRunLog'), context);
  context.renderRunLog();
  const cards = elements['run-stats'].innerHTML;
  assert.match(cards, /9 月總里程<\/div><div class="card-value">15\.00 km/);
  assert.match(cards, /9 月主力鞋<\/div><div class="card-value">Neo/);
  assert.doesNotMatch(cards, /本月/);
});

test('SPEC-055 a retired shoe analysis says retired instead of forecasting a date', () => {
  const elements = nodes();
  const context = runContext({ document: { getElementById: id => elements[id] }, esc, chartInstances: {} });
  vm.runInContext(['floorShoeKm', 'formatShoeMileage', 'forecastSourceText', 'renderShoeAnalytics'].map(extract).join('\n'), context);
  const data = retired => ({
    shoe: { brand: 'Mizuno', model: 'Sky', is_retired: retired, categories: ['Daily'], purchase_date: '2025-01-01' },
    lifecycle: { total_mileage_km: 500, usage_percent: 62.5, remaining_mileage_km: 300, forecast_monthly_km: 0,
      forecast_retirement_date: retired ? null : '2027-03-01', forecast_source: retired ? 'retired' : 'recent_90_days' },
    usage: { count: 0, km_30_days: 0, km_90_days: 0, actual_monthly_km_90_days: 0, last_run_date: null, first_run_date: null },
    monthly_history: [], recent_runs: [],
  });
  context.renderShoeAnalytics(data(true));
  assert.match(elements['shoe-analysis-content'].innerHTML, /預估退役<\/div><div class="insight-card-value">已退役<\/div><div class="insight-card-sub">退役後不再預估/);
  context.renderShoeAnalytics(data(false));
  assert.match(elements['shoe-analysis-content'].innerHTML, /預估退役<\/div><div class="insight-card-value">2027\/03\/01<\/div><div class="insight-card-sub">依近 90 天實際使用/);
  // SPEC-069: a pair idle for 90 days shows no date instead of one invented from the plan.
  const idle = data(false);
  idle.lifecycle = { ...idle.lifecycle, forecast_retirement_date: null, forecast_source: 'idle_90_days' };
  context.renderShoeAnalytics(idle);
  assert.match(elements['shoe-analysis-content'].innerHTML, /預估退役<\/div><div class="insight-card-value">—<\/div><div class="insight-card-sub">近 90 天沒穿，不預估/);
  assert.equal(context.forecastSourceText('idle_90_days'), '近 90 天沒穿，不預估');
  assert.match(extract('shoeTableRow'), /title="\$\{forecastSourceText\(s\.forecast_source\)\}"/);
});

test('SPEC-138 shoe form drops monthly_km and never-run shoes show no forecast', () => {
  assert.doesNotMatch(htmlSource, /f-monthly/);
  assert.doesNotMatch(readText('frontend/templates/shoe-modal.html'), /f-monthly/);
  const elements = nodes();
  const context = runContext({ document: { getElementById: id => elements[id], querySelectorAll: () => [] }, esc, chartInstances: {} });
  const definition = source.slice(source.indexOf('class ShoeModal {'), source.indexOf('// 初始化一次'));
  vm.runInContext(definition + '\nglobalThis.Modal = ShoeModal;', context);
  const modal = new context.Modal();
  modal.mode = 'create';
  assert.equal('monthly_km' in modal._payload(), false);

  vm.runInContext(['floorShoeKm', 'formatShoeMileage', 'forecastSourceText', 'renderShoeAnalytics'].map(extract).join('\n'), context);
  assert.equal(context.forecastSourceText('no_runs'), '還沒有跑步紀錄，不預估');
  context.renderShoeAnalytics({
    shoe: { brand: 'Mizuno', model: 'Sky', is_retired: false, categories: ['Daily'], purchase_date: '2026-11-01' },
    lifecycle: { total_mileage_km: 0, usage_percent: 0, remaining_mileage_km: 800, forecast_monthly_km: 0,
      forecast_retirement_date: null, forecast_source: 'no_runs' },
    usage: { count: 0, km_30_days: 0, km_90_days: 0, actual_monthly_km_90_days: 0, last_run_date: null, first_run_date: null },
    monthly_history: [], recent_runs: [],
  });
  assert.match(elements['shoe-analysis-content'].innerHTML, /預估退役<\/div><div class="insight-card-value">—<\/div><div class="insight-card-sub">還沒有跑步紀錄，不預估/);
});

test('SPEC-055 the Strava preview explains activities deleted earlier', () => {
  const context = runContext({});
  vm.runInContext(extract('stravaDeletedText'), context);
  assert.equal(context.stravaDeletedText({ deleted_count: 0 }), '');
  assert.equal(context.stravaDeletedText({ deleted_count: 2 }), '另有 2 筆先前刪除過的活動不會重新匯入（可從異動歷史復原）。');
  assert.match(extract('importStrava'), /skipped_deleted \? `，略過 \$\{result\.skipped_deleted\} 筆先前刪除的活動`/);
});

test('SPEC-055 sign-in fields let password managers fill and save credentials', () => {
  assert.doesNotMatch(htmlSource, /autocomplete="off"/);
  for (const id of ['login-username', 'reg-username']) {
    assert.match(htmlSource, new RegExp(`id="${id}" autocomplete="username"`));
  }
  for (const id of ['login-password', 'account-old-password']) {
    assert.match(htmlSource, new RegExp(`id="${id}" type="password" autocomplete="current-password"`));
  }
  for (const id of ['reg-password', 'reg-password2', 'account-new-password', 'account-new-password2']) {
    assert.match(htmlSource, new RegExp(`id="${id}" type="password" autocomplete="new-password"`));
  }
  // The standard capability meta sits next to the legacy iOS one.
  assert.match(htmlSource, /<meta name="mobile-web-app-capable" content="yes">\s*<meta name="apple-mobile-web-app-capable" content="yes">/);
});

test('SPEC-070 the summary shows the Strava running total next to the shoe total with walks', async () => {
  const card = () => ({ value: { textContent: '' }, sub: { textContent: '' } });
  const run = card();
  const elements = nodes();
  const reads = [];
  const shoe = (id, mileage, price) => ({ id, brand: 'B', model: `M${id}`, categories: ['Daily'], usage_percent: 10, mileage, price });
  const context = runContext({
    document: { getElementById: id => (id === 'run-total'
      ? { querySelector: selector => (selector === '.card-value' ? run.value : run.sub) } : elements[id]) },
    esc, shoes: [shoe(1, 401.77, 4000), shoe(2, 261.86, 3000)], retiredShoes: [shoe(3, 629.86, 2000)],
    apiGet: async path => { reads.push(path); return { run_count: 210, total_km: 1234.56 }; },
    resourceStore: { read: async (name, { loader }) => ({ resource: name, status: 'fulfilled', value: await loader() }), current: () => true },
  });
  vm.runInContext(`${lifecycleConstants}\n${['calc', 'floorShoeKm', 'formatKmTotal', 'renderCards'].map(extract).join('\n')}\n`
    + `let runTotalsRequestId = 0;\n${extract('renderRunTotalCard')}`, context);
  context.renderCards();
  await new Promise(resolve => setImmediate(resolve));
  const labels = [...elements['summary-cards'].innerHTML.matchAll(/card-label">([^<]+)/g)].map(match => match[1]);
  assert.deepEqual(labels, ['現役跑鞋', '跑步里程', '跑鞋里程', '總花費', '平均每km成本', '換鞋提醒']);
  assert.match(elements['summary-cards'].innerHTML, /跑鞋里程<\/div><div class="card-value">1,293\.4<\/div><div class="card-sub">km · 含步行、健行/);
  assert.deepEqual(reads, ['/runs/totals']);
  assert.equal(run.value.textContent, '1,234.5', 'truncated like Strava');
  assert.equal(run.sub.textContent, 'km · 210 次跑步');
  assert.doesNotMatch(extract('renderCards'), /需補鞋類別/);
});
