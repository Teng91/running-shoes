// Run with: node --test unit_tests/frontend_regressions.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/index.html', 'utf8');

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
