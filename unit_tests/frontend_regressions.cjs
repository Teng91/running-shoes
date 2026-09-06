// Run with: node --test unit_tests/frontend_regressions.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/index.html', 'utf8');
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
