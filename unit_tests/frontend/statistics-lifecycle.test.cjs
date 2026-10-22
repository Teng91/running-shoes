const { runContext, test, assert, fs, vm, extract } = require('./helpers.cjs');

function elements() {
  return new Proxy({}, { get: (target, id) => target[id] ||= {
    value: '', textContent: '', innerHTML: '', hidden: false, style: {},
    classList: { add() {}, remove() {}, contains() { return false; } },
  } });
}

test('SPEC-017 monthly edit rejects blank/non-finite inputs but accepts explicit zero', async () => {
  const nodes = elements(), writes = [];
  const context = vm.createContext({ document: { getElementById: id => nodes[id] },
    isCurrentAuthSession: () => true, translateError: value => value,
    apiPut: async (_, payload) => writes.push(payload), closeMonthlyModal() {}, loadData: async () => {},
  });
  vm.runInContext('let editingMonthly = { id: 1, session: {}, version: 0 };\n' + extract('saveMonthlyMileage'), context);
  nodes['m-year'].value = '2026'; nodes['m-month'].value = '8';
  for (const invalid of ['', 'NaN', 'Infinity', '-1']) {
    nodes['m-km'].value = invalid; await context.saveMonthlyMileage();
    assert.equal(writes.length, 0); assert.equal(nodes['monthly-error'].style.display, 'block');
  }
  nodes['m-km'].value = '0'; await context.saveMonthlyMileage();
  assert.equal(writes.length, 1); assert.equal(writes[0].km, 0);
});

test('SPEC-017 monthly add requires explicit distance including zero', async () => {
  const nodes = elements(), writes = [];
  const context = vm.createContext({ document: { getElementById: id => nodes[id] },
    apiPost: async (_, payload) => writes.push(payload), loadData: async () => {}, translateError: v => v,
  });
  vm.runInContext('let monthlySaving = false;\n' + extract('addMonthlyMileage'), context);
  nodes['add-year'].value = '2026'; nodes['add-month'].value = '8';
  await context.addMonthlyMileage(); assert.equal(writes.length, 0);
  nodes['add-km'].value = '0'; await context.addMonthlyMileage();
  assert.equal(writes[0].km, 0);
});

test('SPEC-017 goal cards display server-only run totals, not manual monthly totals', () => {
  const nodes = elements();
  const context = vm.createContext({ document: { getElementById: id => nodes[id] },
    runningGoal: { monthly_km: 125, yearly_km: 1500 },
    monthlyMileages: [{ km: 150, adjustment_km: 100 }], dashboardGoalSummary: () => '月底結算',
  });
  vm.runInContext(extract('renderGoalCards'), context);
  context.renderGoalCards({ active: true, month_km: 50, ytd_km: 50, month_achievement_percent: 40,
    year_achievement_percent: 3.3, year_remaining_km: 1450 }, 2026, 8);
  assert.match(nodes['goal-cards'].innerHTML, /50\.00 \/ 125 km/);
  assert.match(nodes['goal-cards'].innerHTML, /達成 40\.0%/);
  assert.doesNotMatch(nodes['goal-cards'].innerHTML, /120\.0%|150\.00/);
});

test('SPEC-017 stale goal requests cannot replace a newer month or session', async () => {
  const nodes = elements(), requests = [], renders = [];
  let current = true;
  const context = vm.createContext({ document: { getElementById: id => nodes[id] },
    captureAuthSession: () => ({ generation: 1 }), isCurrentAuthSession: () => current,
    localDateISO: () => '2026-10-20', runningGoal: { version: 0 },
    selectedYear: 2026, selectedGoalMonth: 8, esc: v => v,
    apiGet: () => new Promise(resolve => requests.push(resolve)),
    renderGoalCards: data => renders.push(data.month_km),
  });
  vm.runInContext('const goalProgressCache = new Map(); let goalProgressRequestId = 0;\n' + extract('loadGoalProgress'), context);
  const first = context.loadGoalProgress(2026, 8);
  context.selectedGoalMonth = 9;
  const second = context.loadGoalProgress(2026, 9);
  requests[1]({ month_km: 10 }); await second;
  requests[0]({ month_km: 999 }); await first;
  assert.deepEqual(renders, [10]);
  const stale = context.loadGoalProgress(2026, 10); current = false;
  requests[2]({ month_km: 123 }); await stale;
  assert.deepEqual(renders, [10]);
});

test('SPEC-017 cross-day limits advance without resetting drafts, month, or tab', () => {
  const nodes = elements(), listeners = {}, events = {};
  let today = '2026-10-19', renders = 0;
  const context = vm.createContext({ window: { addEventListener: (name, fn) => listeners[name] = fn },
    document: { getElementById: id => nodes[id], addEventListener: (name, fn) => events[name] = fn, visibilityState: 'visible' },
    localDateISO: () => today, authToken: 'synthetic', dashboardAnalyticsCache: new Map(), goalProgressCache: new Map(),
    invalidatePanels() {}, renderActivePanel: () => renders++,
  });
  vm.runInContext(fs.readFileSync('frontend/app-dates.js', 'utf8'), context);
  nodes['run-date'].value = '2026-10-18'; nodes['run-month'].value = '2026-08';
  context.refreshDateLimits(); today = '2026-10-20'; listeners.focus();
  assert.equal(nodes['run-date'].max, today); assert.equal(nodes['edit-run-date'].max, today);
  assert.equal(nodes['strava-end-date'].max, today);
  assert.equal(nodes['run-date'].value, '2026-10-18'); assert.equal(nodes['run-month'].value, '2026-08');
  assert.equal(renders, 1); events.visibilitychange(); assert.equal(renders, 1);
});

test('SPEC-017 deleted shoes remain in annual stacked mileage totals', async () => {
  const nodes = elements(); nodes['stacked-year-select'].value = '2026';
  const context = runContext({ document: { getElementById: id => nodes[id], querySelector: () => ({ dataset: { panel: 'monthly' } }) },
    chartInstances: {}, shoes: [{ id: 2, brand: 'A', model: 'Visible' }], retiredShoes: [],
    yearlyRunsCache: new Map([[2026, { shoes: [{ shoe_id: 1, monthly_km: [10] }, { shoe_id: 2, monthly_km: [20] }] }]]),
    brandColor: () => '#000', getThemeColor: () => '#000', stackedRunsRequestId: 0,
    Chart: function(_, config) { this.config = config; },
  });
  vm.runInContext(extract('renderShoeStackedChart'), context);
  await context.renderShoeStackedChart();
  const data = context.chartInstances.shoeStacked.config.data.datasets;
  assert.equal(data.reduce((sum, row) => sum + row.data.reduce((a, b) => a + b, 0), 0), 30);
  assert.ok(data.some(row => row.label.includes('已刪除 #1')));
});

test('SPEC-017 spending renders server calendar months without UTC Date parsing', () => {
  const nodes = elements();
  const context = vm.createContext({ document: { getElementById: id => nodes[id] },
    Date: function() { throw new Error('Calendar months must not parse as instants'); },
    spendingSummary: { start_month: '2026-03', month_span: 8, total_paid: 800, total_original: 1000,
      savings: 200, average_discount_percent: 80, average_monthly_paid: 100, highest_month: null },
  });
  vm.runInContext(['calendarMonthParts', 'fmtMoney', 'renderSpendingCards'].map(extract).join('\n'), context);
  context.renderSpendingCards();
  assert.match(nodes['spending-cards'].innerHTML, /從 2026\/03 到今月，共 8 個月/);
  assert.match(nodes['spending-cards'].innerHTML, /平均月支出[\s\S]*\$100/);
});

test('SPEC-017 run detail pagination performs one bounded request and exposes more rows', async () => {
  const urls = [];
  const context = vm.createContext({ URLSearchParams,
    apiGet: async url => { urls.push(url); return Array.from({ length: 201 }, (_, id) => ({ id })); },
  });
  vm.runInContext('const RUN_PAGE_SIZE = 200;\n' + extract('fetchRunPage'), context);
  const page = await context.fetchRunPage({ year: 2026, month: 8, offset: 200, day: 5 });
  assert.equal(urls.length, 1); assert.equal(page.rows.length, 200); assert.equal(page.hasMore, true);
  const query = new URLSearchParams(urls[0].split('?')[1]);
  assert.equal(query.get('offset'), '200'); assert.equal(query.get('day'), '5'); assert.equal(query.get('limit'), '201');
});

test('SPEC-017 native lifecycle keeps cleaning after errors and rejects duplicate ownership', async () => {
  const { createLifecycle } = await import('../../frontend/runtime/feature-lifecycle.mjs');
  const calls = [], errors = [], lifecycle = createLifecycle(name => errors.push(name));
  lifecycle.register('runs', () => calls.push('runs'));
  lifecycle.register('fault', () => { throw new Error('synthetic'); });
  const remove = lifecycle.register('reports', () => calls.push('reports'));
  assert.throws(() => lifecycle.register('runs', () => {}), /Duplicate/);
  assert.deepEqual(lifecycle.reset(), ['fault']);
  assert.deepEqual(calls, ['runs', 'reports']); assert.deepEqual(errors, ['fault']);
  remove(); lifecycle.reset(); assert.deepEqual(calls, ['runs', 'reports', 'runs']);
  assert.doesNotMatch(extract('clearAuth'), /shoeModal|report-content|stravaPreview|resetAgentChat/);
});

test('SPEC-017 PWA update notification never refreshes a draft without confirmation', () => {
  const nodes = elements(), handlers = {}; let reloads = 0;
  const context = vm.createContext({ document: { querySelector: () => ({ content: 'test-old' }), getElementById: id => nodes[id], readyState: 'loading' },
    navigator: { serviceWorker: { addEventListener: (name, fn) => handlers[name] = fn } },
    window: { addEventListener() {}, location: { reload: () => reloads++ } }, confirm: () => false,
  });
  nodes['app-update-notice'].hidden = true;
  vm.runInContext(['initializeAppUpdates', 'applyAppUpdate'].map(extract).join('\n'), context);
  context.initializeAppUpdates();
  handlers.message({ data: { type: 'SHELL_VERSION', version: 'test-old' } });
  assert.equal(nodes['app-update-notice'].hidden, true);
  handlers.message({ data: { type: 'SHELL_VERSION', version: 'test-new' } });
  assert.equal(nodes['app-update-notice'].hidden, false); assert.equal(reloads, 0);
  context.applyAppUpdate(); assert.equal(reloads, 0);
  context.confirm = () => true; context.applyAppUpdate(); assert.equal(reloads, 1);
});

test('SPEC-017 paged run cards and calendar use the complete backend summary', () => {
  const nodes = elements(); let calendar;
  const context = runContext({ document: { getElementById: id => nodes[id] },
    selectedRunMonth: () => '2026-08', monthRuns: () => [{ id: 201, shoe_id: 1, date: '2026-08-05', km: 1 }],
    runSummary: { year: 2026, month: 8, total_km: 205, run_count: 205, run_days: 1,
      shoe_usage: [{ shoe_id: 1, km: 205, count: 205 }], calendar: [{ date: '2026-08-05', km: 205, shoes: [] }] },
    runPageOffset: 200, runPageHasMore: false, runDayFilter: null, RUN_PAGE_SIZE: 200,
    runShoe: () => null, brandColor: () => '', esc: v => v,
    renderStravaStatus() {}, renderRunCalendar: data => calendar = data, renderRunShoeChart() {}, loadDashboardAnalytics() {},
  });
  vm.runInContext(extract('renderRunLog'), context); context.renderRunLog();
  assert.match(nodes['run-stats'].innerHTML, /205\.00 km/);
  assert.match(nodes['run-stats'].innerHTML, /205 次跑步/);
  assert.equal(calendar[0].km, 205); assert.equal(nodes['run-next'].disabled, true);
});

test('SPEC-017 spending failures retry locally and late account responses are discarded', async () => {
  const nodes = elements(); let session = {}, finish;
  const context = vm.createContext({ registerFeatureReset() {},
    captureAuthSession: () => session, isCurrentAuthSession: value => value === session,
    document: { getElementById: id => nodes[id], querySelector: () => ({ dataset: { panel: 'runs' } }) },
    spendingSummary: null, monthlySpending: [], esc: v => v,
    apiGet: async () => { throw new Error('offline'); },
  });
  vm.runInContext(fs.readFileSync('frontend/app-spending.js', 'utf8'), context);
  await context.loadSpendingData(); assert.match(nodes['spending-cards'].innerHTML, /offline/);
  context.apiGet = async () => ({ monthly: [], total_paid: 10 });
  await context.loadSpendingData(); assert.equal(context.spendingSummary.total_paid, 10);
  context.apiGet = () => new Promise(resolve => finish = resolve);
  const old = context.loadSpendingData(); session = {}; context.spendingSummary = null;
  finish({ monthly: [], total_paid: 999 }); await old;
  assert.equal(context.spendingSummary, null);
});

test('SPEC-017 old run creation cannot overwrite or unlock a replacement account operation', async () => {
  const nodes = elements(); let session = {}, finish, reject, calls = 0;
  const context = runContext({ document: { getElementById: id => nodes[id] }, refreshDateLimits() {},
    captureAuthSession: () => session, isCurrentAuthSession: value => value === session,
    localDateISO: () => '2026-10-20', loadData: async () => {},
    apiPost: () => { calls++; return new Promise((resolve, fail) => { finish = resolve; reject = fail; }); },
  });
  vm.runInContext(extract('addRun'), context);
  nodes['run-date'].value = '2026-10-20'; nodes['run-km'].value = '5'; nodes['run-shoe'].value = '1';
  const old = context.addRun(), rejectOld = reject;
  session = {}; context.runController.reset();
  const current = context.addRun();
  rejectOld(new Error('old failure')); await old;
  assert.equal(nodes['add-run-btn'].disabled, true); assert.equal(nodes['run-error'].textContent, '');
  finish(); await current;
  assert.equal(calls, 2); assert.equal(nodes['add-run-btn'].disabled, false);
});
