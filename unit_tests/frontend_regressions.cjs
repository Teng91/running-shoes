// Run with: node --test unit_tests/frontend_regressions.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const htmlSource = fs.readFileSync('frontend/index.html', 'utf8');
const scriptPaths = [
  'frontend/app-boot.js',
  'frontend/app-state.js',
  'frontend/app-api.js',
  'frontend/app-auth.js',
  'frontend/app-core.js',
  'frontend/app-agent.js',
  'frontend/app-reports.js',
  'frontend/app-runs.js',
  'frontend/app-strava.js',
  'frontend/app-run-insights.js',
  'frontend/app-shoes.js',
  'frontend/app-dashboard.js',
  'frontend/app-monthly.js',
  'frontend/app-charts.js',
  'frontend/app-spending.js',
  'frontend/app.js',
];
const scriptSource = scriptPaths.map(path => fs.readFileSync(path, 'utf8')).join('\n');
const styleSource = fs.readFileSync('frontend/styles.css', 'utf8');
const source = `${htmlSource}\n${styleSource}\n${scriptSource}`;

function tableHeaders(tbodyId) {
  const beforeBody = htmlSource.slice(0, htmlSource.indexOf(`<tbody id="${tbodyId}"`));
  const header = beforeBody.slice(beforeBody.lastIndexOf('<thead>'));
  return [...header.matchAll(/<th>(.*?)<\/th>/g)].map(match => match[1]);
}

test('shoe purchase columns live only in spending details, with aligned table rows', () => {
  const elements = { 'shoe-table': {}, 'retired-table': {} };
  const shoe = { id: 7, brand: 'Test', model: 'Runner', date: '2026-01-02',
    size: 'UNIQUE-SIZE', price: 2400, orig_price: 4000, mileage: 100,
    expected_mileage: 800, monthly_km: 50, categories: ['Daily'] };
  const context = vm.createContext({
    document: { getElementById: id => elements[id] },
    shoes: [shoe], retiredShoes: [{ ...shoe, id: 8, is_retired: true }],
    brandColor: () => '#123456', progressColor: () => '#123456',
    shoeCategories: s => s.categories,
  });
  vm.runInContext(['esc', 'calc', 'fmtPct', 'fmtCostPerKm', 'fmtDate',
    'renderTable', 'renderRetiredTable'].map(extract).join('\n'), context);
  context.renderTable();
  context.renderRetiredTable();
  for (const [id, count] of [['shoe-table', 12], ['retired-table', 10]]) {
    const headers = tableHeaders(id);
    assert.equal(headers.length, count);
    assert.ok(['尺寸', '買價', '原價', '折數'].every(label => !headers.includes(label)));
    assert.equal((elements[id].innerHTML.match(/<td\b/g) || []).length, count);
    assert.doesNotMatch(elements[id].innerHTML, /UNIQUE-SIZE|\$2,400|\$4,000|60\.00%/);
    assert.match(elements[id].innerHTML, /\$24\.00/); // Cost/km stays on shoes.
    assert.match(elements[id].innerHTML, />分析<\/button>/);
    assert.match(elements[id].innerHTML, />編輯<\/button>/);
  }
  assert.deepEqual(tableHeaders('spending-table'),
    ['日期', '品牌', '鞋款', '尺寸', '買價', '原價', '折數', '類別', '狀態']);
});

test('spending details retain active and retired purchases, escape sizes and handle missing values', () => {
  const tbody = {};
  const shoe = { id: 1, brand: 'Test', model: 'Active', date: '2026-02-02',
    size: '<img src=x onerror=alert(1)>', price: 2400, orig_price: 4000, categories: ['Daily'] };
  const shoes = [shoe];
  const retiredShoes = [{ ...shoe, id: 2, model: 'Retired', date: '2026-01-01',
    size: '', price: 0, orig_price: 0, is_retired: true }];
  const context = vm.createContext({ document: { getElementById: () => tbody },
    shoes, retiredShoes, shoeCategories: s => s.categories,
    byDate: (a, b) => a.date.localeCompare(b.date),
  });
  vm.runInContext(['esc', 'fmtMoney', 'renderSpendingTable'].map(extract).join('\n'), context);
  context.renderSpendingTable();
  const rows = [...tbody.innerHTML.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(match => match[1]);
  assert.equal(rows.length, 2);
  for (const row of rows) assert.equal((row.match(/<td\b/g) || []).length, 9);
  assert.match(rows[0], /Retired[\s\S]*<td>—<\/td>[\s\S]*<td>已退役<\/td>/);
  assert.match(rows[1], /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(rows[1], /\$2,400[\s\S]*\$4,000[\s\S]*60\.0%[\s\S]*使用中/);
  assert.doesNotMatch(tbody.innerHTML, /<img|—%|NaN|Infinity/);
  assert.equal(shoes[0].size, shoe.size, 'rendering must not modify purchase data');
  shoes.length = 0;
  retiredShoes.length = 0;
  context.renderSpendingTable();
  assert.equal(tbody.innerHTML, '');
});

test('PWA metadata, local dependencies and service worker registration are present', () => {
  assert.match(source, /rel="manifest" href="\/manifest\.webmanifest"/);
  assert.match(source, /rel="apple-touch-icon" href="\/icons\/apple-touch-icon\.png"/);
  assert.match(source, /navigator\.serviceWorker\.register\('\/service-worker\.js'\)/);
  assert.match(source, /src="\/vendor\/chart\.umd\.min\.js"/);
  assert.match(source, /src="\/vendor\/marked\.min\.js"/);
  assert.doesNotMatch(source, /cdn\.jsdelivr\.net/);
  const serviceWorker = fs.readFileSync('frontend/service-worker.js', 'utf8');
  const assetVersion = serviceWorker.match(/APP_ASSET_VERSION = '([^']+)'/)?.[1];
  assert.ok(assetVersion, 'service worker declares an application asset version');
  assert.match(serviceWorker, /'\/vendor\/chart\.umd\.min\.js'/);
  assert.match(serviceWorker, /'\/vendor\/marked\.min\.js'/);
  const appAssets = scriptPaths.map(file => `/${path.basename(file)}`).concat('/styles.css');
  for (const asset of appAssets) {
    assert.ok(serviceWorker.includes(`versioned('${asset}')`), `${asset} is precached with a version`);
    const attribute = asset.endsWith('.css') ? 'href' : 'src';
    assert.ok(htmlSource.includes(`${attribute}="${asset}?v=${assetVersion}"`), `${asset} uses the service worker version`);
  }
  assert.match(serviceWorker, /event\.waitUntil\(networkResponse/);
  assert.match(serviceWorker, /caches\.match\('\/'\)\.then\(cached => cached \|\| networkResponse\)/);
  const unversionedHtml = htmlSource.replaceAll(`?v=${assetVersion}`, '');
  assert.match(unversionedHtml, /src="\/app-boot\.js"[\s\S]*src="\/app-state\.js"[\s\S]*src="\/app-api\.js"[\s\S]*src="\/app-auth\.js"[\s\S]*src="\/app-core\.js"[\s\S]*src="\/app-agent\.js"[\s\S]*src="\/app-reports\.js"[\s\S]*src="\/app-runs\.js"[\s\S]*src="\/app-strava\.js"[\s\S]*src="\/app-run-insights\.js"[\s\S]*src="\/app-shoes\.js"[\s\S]*src="\/app\.js"/);
});

test('startup and login show progress until the application is ready', () => {
  assert.match(htmlSource, /id="app-boot"[^>]+role="status"[^>]+aria-live="polite"/);
  assert.match(htmlSource, /id="app-boot-message">正在準備應用程式/);
  assert.match(htmlSource, /id="app-boot-retry"[^>]+hidden>重新載入/);
  assert.ok(htmlSource.indexOf('id="app-boot"') < htmlSource.indexOf('src="/vendor/chart.umd.min.js"'));
  assert.match(htmlSource, /__appBootLegacyPoll/);
  assert.match(htmlSource, /Critical startup UI must not depend[\s\S]+body \{ margin: 0; opacity: 1 !important; \}/);
  assert.match(htmlSource, /id="app-styles" rel="preload" href="\/styles\.css\?v=[^"]+" as="style"/);
  assert.match(htmlSource, /dataset\.ready='true';window\.dispatchEvent\(new Event\('appstylesready'\)\)/);
  assert.match(source, /\.app-boot\.is-hidden \{ opacity: 0; visibility: hidden/);
  assert.match(source, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(source, /body \{[^}]*opacity:\s*0/);

  const initSource = extract('init');
  const loginSource = extract('handleLogin');
  assert.match(initSource, /showAppView\(\{ keepBoot: true \}\)[\s\S]+await loadData\(\);[\s\S]+hideAppBoot\(\)/);
  assert.match(loginSource, /showAppBoot\('正在登入並載入資料…'\)[\s\S]+await loadData\(\);[\s\S]+hideAppBoot\(\)/);
  assert.match(source, /showAppBootError\('載入時間比預期久/);
  assert.match(source, /init\(\)\.catch\(error =>/);
});

test('successful login and logout clear every authentication field', () => {
  const ids = [
    'login-username', 'login-password',
    'reg-username', 'reg-password', 'reg-password2',
    'change-username', 'change-old-password', 'change-new-password', 'change-new-password2',
  ];
  const elements = Object.fromEntries(ids.map(id => [id, { value: 'previous-user-secret' }]));
  const context = vm.createContext({ document: { getElementById: id => elements[id] } });
  vm.runInContext(`const AUTH_INPUT_IDS = ${JSON.stringify(ids)};\n${extract('resetAuthInputs')}`, context);
  context.resetAuthInputs();
  assert.deepEqual(ids.map(id => elements[id].value), ids.map(() => ''));
  assert.match(extract('clearAuth'), /resetAuthInputs\(\)/);
  assert.match(extract('handleLogin'), /setAuth\(data\.access_token, username\);[\s\S]+resetAuthInputs\(\)/);
  assert.match(htmlSource, /id="login-form" autocomplete="off"/);
  assert.match(htmlSource, /id="login-password" type="password" autocomplete="off"/);
});

test('mobile page gutters preserve standalone safe-area insets', () => {
  assert.match(source, /padding:\s*calc\(var\(--page-gutter\) \+ env\(safe-area-inset-top\)\)[\s\S]*max\(var\(--page-gutter\), env\(safe-area-inset-right\)\)[\s\S]*max\(var\(--page-gutter\), env\(safe-area-inset-bottom\)\)[\s\S]*max\(var\(--page-gutter\), env\(safe-area-inset-left\)\)/);
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*?\.container \{ --page-gutter: 16px; \}/);
  assert.match(source, /@media \(max-width: 380px\)[\s\S]*?\.container \{ --page-gutter: 12px; \}/);
  assert.doesNotMatch(source, /@media \(max-width: (?:760|380)px\)[\s\S]*?\.container \{ padding:/);
});

test('monthly reports progressively render markdown with document styling', () => {
  assert.match(source, /class="agent-msg-content report-content"/);
  assert.match(source, /\.report-content h2 \{/);
  assert.match(source, /\.report-content blockquote \{/);
  assert.match(source, /scheduleMarkdownRender\(\)/);
  assert.match(source, /content\.classList\.add\('is-streaming'\)/);
});

test('temporary auth connectivity failures preserve the stored session', () => {
  const initSource = source.slice(source.indexOf('async function init()'), source.indexOf('\ninit();'));
  assert.match(initSource, /authenticatedFetch\(API_BASE \+ '\/auth\/me'/);
  assert.match(extract('authenticatedFetch'), /response\.status === 401/);
  assert.match(initSource, /catch \(error\)[\s\S]+showAppView\(\{ keepBoot: true \}\);[\s\S]+await loadData\(\);/);
  assert.doesNotMatch(initSource.match(/catch \(error\) \{[\s\S]+?\n    \}/)[0], /clearAuth\(\)/);
});

test('monthly shoe share draws values in the doughnut without a separate legend', () => {
  assert.doesNotMatch(source, /id="chart-value-legend"/);
  assert.match(source, /id: 'shoeShareLabels'/);
  assert.match(source, /strokeText\(`\$\{km\} km`/);
  assert.match(source, /percentage\.toFixed\(1\)/);
});

test('run shoe distribution shows monthly percentage, mileage, and wear count', () => {
  const legend = {};
  const context = vm.createContext({
    document: { getElementById: () => legend },
    runShoe: id => ({ brand: 'Test', model: `Shoe ${id}` }),
    brandColor: () => '#123456', esc: value => value,
  });
  vm.runInContext(extract('renderRunShoeChart'), context);
  context.renderRunShoeChart(new Map([
    [1, { km: 15, count: 2 }],
    [2, { km: 5, count: 1 }],
  ]));
  assert.match(legend.innerHTML, /75\.0%<\/span><span class="run-shoe-legend-km">15\.00 km<\/span><span class="run-shoe-legend-count">2 次/);
  assert.match(legend.innerHTML, /25\.0%<\/span><span class="run-shoe-legend-km">5\.00 km<\/span><span class="run-shoe-legend-count">1 次/);
});

test('shoe analytics ignores stale responses after a second open or close', () => {
  const openAnalytics = extract('openShoeAnalytics');
  const closeAnalytics = extract('closeShoeAnalytics');
  assert.match(source, /let shoeAnalyticsRequestId = 0/);
  assert.match(openAnalytics, /const requestId = \+\+shoeAnalyticsRequestId/);
  assert.match(openAnalytics, /requestId !== shoeAnalyticsRequestId/);
  assert.match(closeAnalytics, /shoeAnalyticsRequestId \+= 1/);
});

test('shoe analytics uses the requested six-card order without cost or reconciliation copy', () => {
  const analytics = extract('renderShoeAnalytics');
  const cards = analytics.slice(analytics.indexOf('const cards'), analytics.indexOf('const recentRows'));
  const labels = [...cards.matchAll(/label: '([^']+)'/g)].map(match => match[1]);
  assert.deepEqual(labels, ['總里程', '穿著次數', '近 30／90 天', '最後使用', '壽命進度', '預估退役']);
  assert.doesNotMatch(analytics, /每公里成本|每次穿著|日誌 .*歷史調整/);
  assert.match(analytics, /card\.sub \? `<div class="insight-card-sub">/);
});

test('unclassified shoes stay unclassified when the form is saved', () => {
  const context = vm.createContext({ document: { querySelectorAll: () => [] } });
  vm.runInContext(extract('getSelectedCategories'), context);
  assert.deepEqual(Array.from(context.getSelectedCategories()), []);
});

test('replacement alerts require backup for every purpose and handle unclassified shoes', () => {
  const container = {};
  const context = vm.createContext({
    document: { getElementById: () => container },
    shoes: [{ id: 1, brand: 'A', model: 'Target', categories: ['Daily', 'Tempo'], progress: .95 },
      { id: 2, categories: ['Daily'], progress: .1 }],
    calc: s => ({ lifeProgress: s.progress }), shoeCategories: s => s.categories, esc: s => s,
  });
  vm.runInContext(extract('renderAlerts'), context);
  context.renderAlerts();
  assert.match(container.innerHTML, /Tempo 沒有其他現役鞋/);
  context.shoes[1].categories.push('Tempo');
  context.renderAlerts();
  assert.match(container.innerHTML, /所有用途類別都有其他現役鞋/);
  context.shoes[0].categories = [];
  context.renderAlerts();
  assert.match(container.innerHTML, /尚未設定用途類別/);
});

test('shoe save ignores duplicate submissions and unlocks after errors', async () => {
  const definition = source.slice(source.indexOf('class ShoeModal {'), source.indexOf('// 初始化一次'));
  const context = vm.createContext({ alert() {}, loadData: async () => {} });
  vm.runInContext(definition + '\nglobalThis.Modal = ShoeModal;', context);
  const modal = Object.create(context.Modal.prototype);
  const button = {};
  Object.assign(modal, { mode: 'create', el: { querySelector: () => button },
    _payload: () => ({ brand: 'A', model: 'B', date: '2026-09-06' }), close() {} });
  let resolve, calls = 0;
  context.apiPost = () => { calls++; return new Promise(r => { resolve = r; }); };
  const first = modal.submit();
  await modal.submit();
  assert.equal(calls, 1);
  assert.equal(button.disabled, true);
  resolve();
  await first;
  assert.equal(button.disabled, false);
  context.apiPost = async () => { throw Error('offline'); };
  await modal.submit();
  assert.equal(modal.saving, false);
  assert.equal(button.disabled, false);
});
function extract(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  return source.slice(start, source.indexOf('\n}', start) + 2);
}

test('double submit writes one run and unlocks after completion or failure', async () => {
  let resolve;
  let calls = 0;
  const elements = {
    'run-error': {}, 'run-date': { value: '2026-09-06' },
    'run-km': { value: '10' }, 'run-shoe': { value: '1' },
    'run-month': {}, 'add-run-btn': {},
  };
  const context = vm.createContext({
    document: { getElementById: id => elements[id] },
    apiPost: () => { calls++; return new Promise(r => { resolve = r; }); },
    localDateISO: () => '2026-10-13',
    loadData: async () => {},
  });
  vm.runInContext('let runSaving = false;\n' + extract('addRun'), context);
  const first = context.addRun();
  await context.addRun();
  assert.equal(calls, 1);
  assert.equal(elements['add-run-btn'].disabled, true);
  resolve();
  await first;
  assert.equal(elements['add-run-btn'].disabled, false);
  elements['run-km'].value = '10';
  context.apiPost = async () => { throw new Error('offline'); };
  await context.addRun();
  assert.equal(elements['run-error'].textContent, 'offline');
  assert.equal(elements['add-run-btn'].disabled, false);
});

test('failed reload retains previous data and exposes a retry; recovery hides error', async () => {
  const error = { hidden: true };
  const context = vm.createContext({
    document: { getElementById: () => error }, console: { error() {}, warn() {} },
    apiGet: async () => { throw new Error('offline'); }, render() {},
    selectedRunMonth: () => '2026-10', fetchRunPages: async () => { throw new Error('offline'); },
    yearlyRunsCache: new Map(),
  });
  vm.runInContext(`let dataLoadGeneration = 0, authToken = 'test', selectedYear;
    let shoes = [{id: 1}], retiredShoes = [], monthlyMileages = [],
    monthlySpending = [], runs = [], stravaImports = [];
    ${extract('loadData')}`, context);
  await context.loadData();
  assert.equal(vm.runInContext('shoes[0].id', context), 1);
  assert.equal(error.hidden, false);
  context.apiGet = async () => [];
  context.fetchRunPages = async () => [];
  await context.loadData();
  assert.equal(vm.runInContext('shoes.length', context), 0);
  assert.equal(error.hidden, true);
});

test('long conversations fit the backend aggregate history and content limits', () => {
  const history = Array.from({ length: 30 }, (_, i) => ({
    role: i % 2 ? 'assistant' : 'user', content: 'x'.repeat(15000),
  }));
  const context = vm.createContext({ agentHistory: history });
  vm.runInContext('const AGENT_HISTORY_CHAR_BUDGET = 48000;\n' + extract('agentHistoryForRequest'), context);
  const result = context.agentHistoryForRequest();
  assert.equal(result.length, 4);
  assert.equal(result.reduce((total, turn) => total + turn.content.length, 0), 48000);
  assert.ok(result.every(turn => turn.content.length === 12000));
  assert.equal(history[0].content.length, 15000);
  assert.match(source, /history: agentHistoryForRequest\(\)/);
});

test('run edits send an optimistic concurrency version', () => {
  const save = extract('saveRun');
  assert.match(save, /expected_version: editingRun\.version \|\| 0/);
  assert.match(extract('deleteEditingRun'), /expected_version=' \+ \(run\.version \|\| 0\)/);
});

test('monthly inline edits commit once and include the loaded version', async () => {
  const handlers = {};
  const input = { addEventListener: (event, fn) => { handlers[event] = fn; }, focus() {} };
  const writes = [];
  const context = vm.createContext({
    monthlyMileages: [{ id: 8, km: 50, version: 3 }],
    document: { createElement: () => input },
    apiPut: async (url, payload) => { writes.push({ url, payload }); },
    loadData: async () => {}, render() {}, alert() {},
  });
  vm.runInContext(extract('inlineEditMonthly'), context);
  await context.inlineEditMonthly(0, 'km', { innerHTML: '', appendChild() {} });
  input.value = '60';
  handlers.keydown({ key: 'Enter' });
  await handlers.blur();
  await Promise.resolve();

  assert.equal(writes.length, 1);
  assert.equal(JSON.stringify(writes[0]), JSON.stringify({
    url: '/monthly-mileage/8', payload: { km: 60, expected_version: 3 },
  }));
});

test('monthly, run, and shoe deletes carry optimistic versions', () => {
  assert.match(extract('deleteMonthlyMileage'), /expected_version=' \+ \(m\.version \|\| 0\)/);
  const modal = source.slice(source.indexOf('class ShoeModal {'), source.indexOf('// 初始化一次'));
  assert.match(modal, /expected_version=' \+ \(this\.shoe\.version \|\| 0\)/);
});

test('report history model labels are inserted as text, not HTML', () => {
  const history = extract('loadReportHistory');
  assert.match(history, /select\.replaceChildren\(\)/);
  assert.match(history, /option\.textContent = reportMonthLabel/);
  assert.doesNotMatch(history, /innerHTML/);
});

test('shoe default uses the local calendar date', () => {
  const context = vm.createContext({ Date });
  vm.runInContext(extract('localDateISO'), context);
  const date = new Date(2026, 8, 6, 0, 30);
  assert.equal(context.localDateISO(date), '2026-09-06');
  assert.match(source, /getElementById\('f-date'\)\.value = localDateISO\(\)/);
});

test('the external application script parses', () => {
  scriptPaths.forEach(path => {
    assert.doesNotThrow(() => new vm.Script(fs.readFileSync(path, 'utf8')));
  });
});

test('run history is fetched by month and paginated', async () => {
  const calls = [];
  const pages = [Array.from({ length: 200 }, (_, id) => ({ id })), [{ id: 201 }]];
  const context = vm.createContext({
    URLSearchParams,
    apiGet: async url => { calls.push(url); return pages.shift(); },
  });
  vm.runInContext('const RUN_PAGE_SIZE = 200;\n' + extract('fetchRunPages'), context);
  const rows = await context.fetchRunPages({ year: 2026, month: 8 });
  assert.equal(rows.length, 201);
  assert.match(calls[0], /year=2026/);
  assert.match(calls[0], /month=8/);
  assert.match(calls[0], /limit=200/);
  assert.match(calls[1], /offset=200/);
  assert.doesNotMatch(calls[0], /offset=200/);
});

test('report completion timestamps are localized by the browser', () => {
  const context = vm.createContext({ Date });
  vm.runInContext(extract('formatLocalTimestamp'), context);
  const formatted = context.formatLocalTimestamp('2026-10-15T01:30:00+00:00');
  assert.ok(formatted.length > 0);
  assert.doesNotMatch(extract('generateReport'), /replace\('T', ' '\)\.slice/);
  assert.match(extract('generateReport'), /formatLocalTimestamp\(event\.updated_at\)/);
});

test('inline edits send only the changed field and guard duplicate commits', async () => {
  const handlers = {};
  const input = { addEventListener: (event, fn) => { handlers[event] = fn; }, focus() {} };
  const writes = [];
  const shoe = { id: 1, price: 20, mileage: 100, version: 3 };
  const context = vm.createContext({
    document: { createElement: () => input }, render() {}, alert() {},
    loadData: async () => {},
    apiPut: async (url, payload) => { writes.push({ url, payload }); },
  });
  vm.runInContext(extract('inlineEditRow'), context);
  await context.inlineEditRow([shoe], 0, 'price', { appendChild() {} });
  input.value = '30';
  handlers.keydown({ key: 'Enter' });
  await handlers.blur();
  assert.equal(writes.length, 1);
  assert.equal(JSON.stringify(writes[0].payload), JSON.stringify({ price: 30, expected_version: 3 }));
  assert.equal(shoe.price, 20);
});

test('the report tab wires its panel and only loads data after login', () => {
  assert.match(source, /data-tab="report"/);
  assert.match(source, /data-panel="report"/);
  assert.match(source, /onchange="loadSavedReport\(\)"/);
  const switchTab = extract('switchTab');
  assert.match(switchTab, /name === 'report' && authToken/);
});

test('the report tab talks to the monthly report endpoints', () => {
  assert.match(extract('generateReport'), /authenticatedFetch\(API_BASE \+ '\/reports\/generate'/);
  assert.match(extract('loadReportHistory'), /authenticatedFetch\(API_BASE \+ '\/reports', \{ headers: authHeaders\(\) \}\)/);
  assert.match(extract('loadSavedReport'), /authenticatedFetch\(API_BASE \+ '\/reports\/' \+ parts\[0\] \+ '\/' \+ parts\[1\]/);
});

test('monthly reports have their own selector backed by the daily model list', () => {
  assert.match(source, /<select id="report-model"><\/select>/);
  const loadModels = extract('loadAgentModels');
  const generateReport = extract('generateReport');
  assert.match(loadModels, /\['agent-model', 'report-model'\]/);
  assert.match(loadModels, /'#' \+ \(index \+ 1\) \+ ' ' \+ model\.display/);
  assert.match(generateReport, /getElementById\('report-model'\)\.value/);
  assert.doesNotMatch(generateReport, /getElementById\('agent-model'\)/);
});

test('monthly report requests abort stale loads and lock selectors while streaming', () => {
  const load = extract('loadSavedReport');
  const generate = extract('generateReport');
  assert.match(source, /let reportLoadRequestId = 0/);
  assert.match(source, /let reportLoadController = null/);
  assert.match(load, /const requestId = \+\+reportLoadRequestId/);
  assert.match(load, /reportLoadController\?\.abort\(\)/);
  assert.match(load, /selectedReportMonth\(\) !== requestedMonth/);
  assert.match(generate, /setReportControlsDisabled\(true\)/);
  assert.match(generate, /signal: controller\.signal/);
  assert.match(generate, /setReportControlsDisabled\(false\)/);
});

test('the report month defaults to the last complete month', () => {
  const context = vm.createContext({ Date });
  vm.runInContext(extract('previousMonthValue'), context);
  assert.equal(context.previousMonthValue(new Date(2027, 0, 15)), '2026-12');
  assert.equal(context.previousMonthValue(new Date(2026, 8, 19)), '2026-08');
});

test('shoe purposes use four full-width, non-shrinking options', () => {
  assert.match(source, /\.form-row \.category-field \{ grid-column: 1 \/ -1; \}/);
  assert.match(source, /grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/);
  assert.match(source, /flex: 0 0 14px/);
  assert.doesNotMatch(source, /value="Trail"/);
});

test('report streaming distinguishes saved completion from an interrupted response', () => {
  const generateReport = extract('generateReport');
  assert.match(generateReport, /buffer \+= decoder\.decode\(\)/);
  assert.match(generateReport, /receivedDone = true/);
  assert.match(generateReport, /receivedError = true/);
  assert.match(generateReport, /!receivedDone && !receivedError/);
  assert.match(generateReport, /內容不完整且未儲存/);
});

test('running goals are loaded, editable, and rendered as monthly and yearly progress', () => {
  assert.match(source, /apiGet\('\/running-goal'\)/);
  assert.match(source, /apiPut\('\/running-goal', payload\)/);
  assert.match(source, /id="goal-cards"/);
  assert.match(source, /id="goal-month-select"/);
  assert.doesNotMatch(source, /id="goal-yearly-km"/);
  const renderGoalProgress = extract('renderGoalProgress');
  assert.match(renderGoalProgress, /monthPct/);
  assert.match(renderGoalProgress, /yearPct/);
  assert.match(renderGoalProgress, /runningGoal\.start_year/);
  assert.match(renderGoalProgress, /remainingDays/);
  assert.match(renderGoalProgress, /超前/);
  assert.match(renderGoalProgress, /落後/);
});

test('dashboard monthly goal shows whether current progress is ahead or behind', () => {
  const context = vm.createContext({});
  vm.runInContext(extract('dashboardGoalSummary'), context);
  assert.equal(
    context.dashboardGoalSummary({ active: true, month_state: 'current',
      pace_delta_km: 3, remaining_days: 19, required_daily_km: 3.87 }),
    '超前 3.00 km · 剩 19 天 · 每天需 3.87 km',
  );
  assert.equal(
    context.dashboardGoalSummary({ active: true, month_state: 'current',
      pace_delta_km: -8.25, remaining_days: 12, required_daily_km: 5.5 }),
    '落後 8.25 km · 剩 12 天 · 每天需 5.50 km',
  );
  assert.equal(
    context.dashboardGoalSummary({ active: true, month_state: 'past',
      month_remaining_km: 10 }),
    '月底結算，未達目標 10.00 km',
  );
  const insights = extract('renderDashboardInsights');
  assert.match(insights, /dashboardGoalSummary\(goal\)/);
});

test('dashboard analytics cache expires by local date and goals invalidate it', () => {
  const loader = extract('loadDashboardAnalytics');
  const saveGoal = extract('saveRunningGoal');
  assert.match(loader, /const cachePrefix = `\$\{session\.generation\}\|\$\{localDateISO\(\)\}\|`/);
  assert.match(loader, /const cacheKey = `\$\{cachePrefix\}\$\{month\}`/);
  assert.match(loader, /!key\.startsWith\(cachePrefix\)/);
  assert.match(saveGoal, /expected_version: Number\(runningGoal\.version \|\| 0\)/);
  assert.match(saveGoal, /dashboardAnalyticsCache\.clear\(\)/);
});

function transportContext() {
  const context = vm.createContext({
    window: { location: { origin: 'http://test.local' } },
    DOMException, FormData, Blob,
    clearCalls: 0, loginCalls: 0,
  });
  vm.runInContext(`let authToken = 'A', authGeneration = 1;
    ${extract('captureAuthSession')}
    ${extract('isCurrentAuthSession')}
    ${extract('requireAuthSession')}
    function clearAuth() { authToken = null; authGeneration++; clearCalls++; }
    function showLoginView() { loginCalls++; }
    function switchSession(token) { authToken = token; authGeneration++; }
    function activeToken() { return authToken; }
    ${fs.readFileSync('frontend/app-api.js', 'utf8')}`, context);
  return context;
}

test('every JSON and upload helper ignores a previous session 401', async () => {
  for (const call of [
    ctx => ctx.apiGet('/test'), ctx => ctx.apiPost('/test', {}),
    ctx => ctx.apiPut('/test', {}), ctx => ctx.apiDelete('/test'),
    ctx => ctx.apiUpload('/test', new Blob(['test']), { mapping: '{}' }),
  ]) {
    const context = transportContext();
    let finish;
    context.fetch = () => new Promise(resolve => { finish = resolve; });
    const request = call(context);
    context.switchSession('B');
    finish({ status: 401 });
    await assert.rejects(request, { name: 'AbortError' });
    assert.equal(context.activeToken(), 'B');
    assert.equal(context.clearCalls, 0);
    assert.equal(context.loginCalls, 0);
  }
});

test('late JSON bodies and network errors cannot return old session data', async () => {
  const context = transportContext();
  let finishBody;
  const reading = new Promise(resolve => {
    context.fetch = async () => ({ status: 200, ok: true, json: () => {
      resolve();
      return new Promise(finish => { finishBody = finish; });
    } });
  });
  const request = context.apiGet('/test');
  await reading;
  context.switchSession('B');
  finishBody({ private: 'A' });
  await assert.rejects(request, { name: 'AbortError' });
  let fail;
  context.fetch = () => new Promise((_, reject) => { fail = reject; });
  const failed = context.apiGet('/test');
  context.switchSession('C');
  fail(new TypeError('offline'));
  await assert.rejects(failed, { name: 'AbortError' });
  assert.equal(context.activeToken(), 'C');
});

test('current 401 expires login, but an identical token from a new session is protected', async () => {
  const context = transportContext();
  let finish;
  context.fetch = () => new Promise(resolve => { finish = resolve; });
  const request = context.apiGet('/test');
  context.switchSession('A');
  finish({ status: 401 });
  await assert.rejects(request, { name: 'AbortError' });
  assert.equal(context.activeToken(), 'A');
  context.fetch = async () => ({ status: 401 });
  await assert.rejects(context.apiGet('/test'), /登入已過期/);
  assert.equal(context.activeToken(), null);
  assert.equal(context.clearCalls, 1);
  assert.equal(context.loginCalls, 1);
});

test('selected-month YTD and forecast remain without removed dashboard features', () => {
  const goalProgress = extract('renderGoalProgress');
  const insights = extract('renderDashboardInsights');
  assert.match(goalProgress, /item\.month <= selectedGoalMonth/);
  assert.match(goalProgress, /截至 \$\{selectedGoalMonth\} 月年度進度/);
  assert.match(insights, /較上月同期|comparison\.label/);
  assert.match(insights, /月底預測/);
  assert.doesNotMatch(source, /鞋款輪替建議|年活動熱圖|最近操作與復原|里程資料健康/);
  assert.doesNotMatch(source, /function renderYearHeatmap|function renderOperations|function undoOperation|function repairMileageData/);
  assert.doesNotMatch(source, /apiGet\('\/operations'\)|apiGet\('\/analytics\/reconciliation'\)/);
});
