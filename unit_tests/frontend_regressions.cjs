// Run with: node --test unit_tests/frontend_regressions.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/index.html', 'utf8');

test('PWA metadata, local dependencies and service worker registration are present', () => {
  assert.match(source, /rel="manifest" href="\/manifest\.webmanifest"/);
  assert.match(source, /rel="apple-touch-icon" href="\/icons\/apple-touch-icon\.png"/);
  assert.match(source, /navigator\.serviceWorker\.register\('\/service-worker\.js'\)/);
  assert.match(source, /src="\/vendor\/chart\.umd\.min\.js"/);
  assert.match(source, /src="\/vendor\/marked\.min\.js"/);
  assert.doesNotMatch(source, /cdn\.jsdelivr\.net/);
  const serviceWorker = fs.readFileSync('frontend/service-worker.js', 'utf8');
  assert.match(serviceWorker, /'\/vendor\/chart\.umd\.min\.js'/);
  assert.match(serviceWorker, /'\/vendor\/marked\.min\.js'/);
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
  assert.match(initSource, /response\.status === 401/);
  assert.match(initSource, /catch \(error\)[\s\S]+showAppView\(\);[\s\S]+loadData\(\);/);
  assert.doesNotMatch(initSource.match(/catch \(error\) \{[\s\S]+?\n    \}/)[0], /clearAuth\(\)/);
});

test('monthly shoe share draws values in the doughnut without a separate legend', () => {
  assert.doesNotMatch(source, /id="chart-value-legend"/);
  assert.match(source, /id: 'shoeShareLabels'/);
  assert.match(source, /strokeText\(`\$\{km\} km`/);
  assert.match(source, /percentage\.toFixed\(1\)/);
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
  });
  vm.runInContext(`let dataLoadGeneration = 0, authToken = 'test', selectedYear;
    let shoes = [{id: 1}], retiredShoes = [], monthlyMileages = [],
    monthlySpending = [], runs = [], stravaImports = [];
    ${extract('loadData')}`, context);
  await context.loadData();
  assert.equal(vm.runInContext('shoes[0].id', context), 1);
  assert.equal(error.hidden, false);
  context.apiGet = async () => [];
  await context.loadData();
  assert.equal(vm.runInContext('shoes.length', context), 0);
  assert.equal(error.hidden, true);
});

test('long conversations fit the backend history and content limits', () => {
  const expression = source.match(/history: (agentHistory[^\n]+),/)[1];
  const history = Array.from({ length: 30 }, (_, i) => ({
    role: i % 2 ? 'assistant' : 'user', content: 'x'.repeat(15000),
  }));
  const result = vm.runInNewContext(expression, { agentHistory: history });
  assert.equal(result.length, 20);
  assert.equal(result[0].role, 'user');
  assert.ok(result.every(turn => turn.content.length === 12000));
  assert.equal(history[0].content.length, 15000);
});

test('shoe default uses the local calendar date', () => {
  const context = vm.createContext({ Date });
  vm.runInContext(extract('localDateISO'), context);
  const date = new Date(2026, 8, 6, 0, 30);
  assert.equal(context.localDateISO(date), '2026-09-06');
  assert.match(source, /getElementById\('f-date'\)\.value = localDateISO\(\)/);
});

test('the entire inline application script parses', () => {
  const script = source.slice(source.indexOf('<script>') + 8, source.lastIndexOf('</script>'));
  assert.doesNotThrow(() => new vm.Script(script));
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
  assert.match(source, /fetch\(API_BASE \+ '\/reports\/generate'/);
  assert.match(source, /fetch\(API_BASE \+ '\/reports', \{ headers: authHeaders\(\) \}\)/);
  assert.match(source, /fetch\(API_BASE \+ '\/reports\/' \+ parts\[0\] \+ '\/' \+ parts\[1\]/);
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
