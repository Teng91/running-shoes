const { test, assert, fs, path, vm, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, reportGenerationSource, panelWiring, transportContext } = require('./helpers.cjs');

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
  assert.doesNotMatch(reportGenerationSource(), /replace\('T', ' '\)\.slice/);
  assert.match(reportGenerationSource(), /formatLocalTimestamp\(event\.updated_at\)/);
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
  await context.inlineEditRow([shoe], 0, 'price', { appendChild() {}, querySelector: () => null, closest: () => ({ id: 'shoe-table' }) });
  input.value = '30';
  handlers.keydown({ key: 'Enter' });
  await handlers.blur();
  assert.equal(writes.length, 1);
  assert.equal(JSON.stringify(writes[0].payload), JSON.stringify({ price: 30, expected_version: 3 }));
  assert.equal(shoe.price, 20);
});

test('the report tab wires its panel and only loads data after login', () => {
  // SPEC-042: chat and report share one AI destination with an in-panel switch.
  assert.doesNotMatch(source, /data-tab="report"/);
  assert.match(source, /data-panel="report"/);
  assert.match(source, /class="ai-switch-btn active" aria-pressed="true" data-click="open-ai-panel" data-ai-panel="report">月報/);
  assert.match(source, /class="ai-switch-btn active" aria-pressed="true" data-click="open-ai-panel" data-ai-panel="agent">對話/);
  assert.match(source, /<span>AI 教練<\/span><\/button>/);
  assert.match(extract('switchTab'), /const destination = name === 'report' \? 'agent' : name;/);
  assert.match(source, /data-change="load-saved-report"/);
  // SPEC-101: opening the report tab runs the hook app-reports.js registers; it loads only after login.
  const calls = [];
  const context = vm.createContext({ authToken: null, document: { querySelectorAll: () => [],
    querySelector: () => ({ setAttribute() {}, textContent: '' }),
    getElementById: () => ({ classList: { toggle() {}, contains: () => false }, textContent: '' }) },
    setMobileMenu() {}, requestAnimationFrame() {}, window: { matchMedia: () => ({ matches: false }) },
    loadReportHistory: () => calls.push('history'), loadSavedReport: () => calls.push('saved'), prepareGoalForm() {} });
  vm.runInContext(panelWiring() + extract('switchTab'), context);
  context.switchTab('report');
  assert.deepEqual(calls, []);
  context.authToken = 'synthetic';
  context.switchTab('report');
  assert.deepEqual(calls, ['history', 'saved']);
  context.switchTab('agent');
  assert.equal(calls.length, 2);
});

test('the report tab talks to the monthly report endpoints', () => {
  assert.match(reportGenerationSource(), /authenticatedFetch\(API_BASE \+ '\/reports\/generate'/);
  assert.match(extract('loadReportHistory'), /authenticatedFetch\(API_BASE \+ '\/reports', \{ headers: authHeaders\(\) \}\)/);
  assert.match(extract('loadSavedReport'), /authenticatedFetch\(API_BASE \+ '\/reports\/' \+ parts\[0\] \+ '\/' \+ parts\[1\]/);
});

test('monthly reports have their own selector backed by the daily model list', () => {
  assert.match(source, /<select id="report-model"><\/select>/);
  const loadModels = extract('loadAgentModels');
  const generateReport = reportGenerationSource();
  assert.match(loadModels, /\['agent-model', 'report-model'\]/);
  assert.match(loadModels, /'#' \+ \(index \+ 1\) \+ ' ' \+ model\.display/);
  assert.match(generateReport, /getElementById\('report-model'\)\.value/);
  assert.doesNotMatch(generateReport, /getElementById\('agent-model'\)/);
});

test('monthly report requests abort stale loads and lock selectors while streaming', () => {
  const load = extract('loadSavedReport');
  const generate = reportGenerationSource();
  assert.match(source, /let reportLoadRequestId = 0/);
  assert.match(source, /let reportLoadController = null/);
  assert.match(load, /const requestId = \+\+reportLoadRequestId/);
  assert.match(load, /reportLoadController\?\.abort\(\)/);
  assert.match(load, /selectedReportMonth\(\) !== requestedMonth/);
  assert.match(generate, /setReportControlsDisabled\(true\)/);
  assert.match(generate, /signal: controller\.signal/);
  assert.match(generate, /setReportControlsDisabled\(false\)/);
});

test('SPEC-132 opening the report tab during a generation leaves the streaming report alone', async () => {
  let fetches = 0;
  const content = { textContent: '串流中的報告' };
  const context = vm.createContext({ document: { getElementById: id => id === 'report-content' ? content : { value: '2026-10', textContent: '' } },
    authenticatedFetch: async () => { fetches++; return { status: 404 }; }, API_BASE: '/api', authHeaders: () => ({}),
    AbortController, reportLoadRequestId: 0, reportLoadController: null, reportGenerationController: {},
    reportMonthParts: () => ['2026', '10'], selectedReportMonth: () => '2026-10', reportMonthLabel: value => value, setReportStatus() {} });
  vm.runInContext(extract('loadSavedReport'), context);
  await context.loadSavedReport();
  assert.equal(fetches, 0);
  assert.equal(content.textContent, '串流中的報告');
  context.reportGenerationController = null;
  await context.loadSavedReport();
  assert.equal(fetches, 1);
  assert.match(content.textContent, /此月份尚無報告/);
});

test('the report month defaults to the last complete month', () => {
  const context = vm.createContext({ Date });
  vm.runInContext(extract('previousMonthValue'), context);
  assert.equal(context.previousMonthValue(new Date(2027, 0, 15)), '2026-12');
  assert.equal(context.previousMonthValue(new Date(2026, 8, 19)), '2026-08');
  // SPEC-093: 2026-12-01 00:30 in Tokyo is still 2026-11-30 in Taiwan, the service's calendar.
  assert.equal(context.previousMonthValue(new Date(Date.UTC(2026, 10, 30, 15, 30))), '2026-10');
});

test('SPEC-093 today is the service calendar day, not the device time zone', () => {
  const context = vm.createContext({ Date });
  vm.runInContext(extract('localDateISO'), context);
  // 23:30 in Taiwan is already 00:30 the next day in Tokyo; the backend still calls it the 21st.
  assert.equal(context.localDateISO(new Date(Date.UTC(2026, 10, 21, 15, 30))), '2026-11-21');
  // 16:00 UTC is midnight in Taiwan: the new day starts there, wherever the device is.
  assert.equal(context.localDateISO(new Date(Date.UTC(2026, 10, 21, 16, 0))), '2026-11-22');
  assert.equal(context.localDateISO(new Date(Date.UTC(2026, 11, 31, 16, 0))), '2027-01-01');
});

test('shoe purposes use four full-width, non-shrinking options', () => {
  assert.match(source, /\.form-row \.category-field \{ grid-column: 1 \/ -1; \}/);
  assert.match(source, /grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/);
  assert.match(source, /flex: 0 0 14px/);
  assert.doesNotMatch(source, /value="Trail"/);
});
