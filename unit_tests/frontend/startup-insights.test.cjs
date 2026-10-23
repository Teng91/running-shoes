const { runContext, test, assert, fs, path, vm, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, transportContext } = require('./helpers.cjs');

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
  const context = vm.createContext({ alert() {}, loadData: async () => {}, isCurrentAuthSession: session => session.current });
  vm.runInContext(definition + '\nglobalThis.Modal = ShoeModal;', context);
  const modal = Object.create(context.Modal.prototype);
  const button = {};
  Object.assign(modal, { formIds: {}, mode: 'create', context: { mode: 'create', session: { current: true } },
    btnDelete: {}, btnMove: {}, el: { querySelector: () => button },
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

test('double submit writes one run and unlocks after completion or failure', async () => {
  let resolve;
  let calls = 0;
  const elements = {
    'run-error': {}, 'run-date': { value: '2026-09-06' },
    'run-km': { value: '10' }, 'run-shoe': { value: '1' },
    'run-month': {}, 'add-run-btn': {},
  };
  const context = runContext({
    document: { getElementById: id => elements[id] },
    apiPost: () => { calls++; return new Promise(r => { resolve = r; }); },
    localDateISO: () => '2026-10-13',
    refreshDateLimits() {}, loadData: async () => {},
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true,
  });
  vm.runInContext(extract('addRun'), context);
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
  const context = runContext({
    document: { getElementById: () => error }, console: { error() {}, warn() {} },
    apiGet: async () => { throw new Error('offline'); }, render() {},
    selectedRunMonth: () => '2026-10', fetchRunPage: async () => { throw new Error('offline'); },
    goalProgressCache: new Map(), loadStravaHistory() {},
    yearlyRunsCache: new Map(),
  });
  vm.runInContext(`let authToken = 'test', selectedYear;
    let shoes = [{id: 1}], retiredShoes = [], monthlyMileages = [],
    monthlySpending = [], runs = [], stravaImports = [], spendingSummary, spendingLoadRequestId = 0,
    spendingLoadPending = false, goalProgressRequestId = 0, runSummary, runPageOffset, runPageHasMore, runDayFilter, runListRequestId = 0;
    ${extract('loadData')}`, context);
  await context.loadData();
  assert.equal(vm.runInContext('shoes[0].id', context), 1);
  assert.equal(error.hidden, false);
  context.apiGet = async () => [];
  context.fetchRunPage = async () => ({ rows: [], hasMore: false });
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
  assert.match(extract('sendAgentMessage'), /history: agentHistoryForRequest\(requestHistory\)/);
});

test('run edits send an optimistic concurrency version', () => {
  const save = extract('saveRun');
  assert.match(save, /expected_version: snapshot\.version \|\| 0/);
  assert.match(fs.readFileSync('frontend/runtime/run-controller.mjs', 'utf8'), /expected_version=' \+ \(snapshot\.version \|\| 0\)/);
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
  await context.inlineEditMonthly(0, 'km', { innerHTML: '', appendChild() {}, querySelector: () => null });
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
  assert.match(modal, /expected_version=' \+ \(shoe\.version \|\| 0\)/);
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
