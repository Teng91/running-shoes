// SPEC-094: core account data has one writer, driven by DOM-independent rules.
const nodeVm = require('node:vm');
const { test, assert, readText } = require('./helpers.cjs');

let rules;
require('node:test').before(async () => {
  rules = await import('../../frontend/runtime/core-data.mjs');
});

// The real app-lifecycle.js, app-state.js and app-resources.js, with the native rules loaded.
function bridgeContext() {
  const context = nodeVm.createContext({ document: { getElementById: () => null, querySelectorAll: () => [] },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} }, console });
  for (const file of ['app-lifecycle.js', 'app-state.js', 'app-resources.js']) {
    nodeVm.runInContext(readText('frontend/' + file), context, { filename: file });
  }
  context.coreDataRules = rules;
  nodeVm.runInContext('coreDataRules = globalThis.coreDataRules', context);
  return context;
}
const read = (context, expression) => JSON.parse(nodeVm.runInContext(`JSON.stringify(${expression})`, context));

test('SPEC-094 shoes arrive as sorted copies and monthly history keeps or picks the shown year', () => {
  const active = [{ id: 2, date: '2026-03-01' }, { id: 1, date: '2025-01-09' }];
  const patch = rules.coreDataPatch('shoes', [active, [{ id: 9, date: '2024-05-05' }]], { currentYear: 2026 });
  assert.deepEqual(Object.keys(patch), ['shoes', 'retiredShoes']);
  assert.deepEqual(patch.shoes.map(shoe => shoe.id), [1, 2]);
  assert.deepEqual(active.map(shoe => shoe.id), [2, 1], 'the loaded payload is not reordered in place');

  const months = [{ year: 2024, month: 1 }, { year: 2025, month: 3 }];
  assert.equal(rules.coreDataPatch('monthly', months, { selectedYear: 2024, currentYear: 2026 }).selectedYear, 2024);
  assert.equal(rules.coreDataPatch('monthly', months, { selectedYear: 2019, currentYear: 2026 }).selectedYear, 2025);
  assert.equal(rules.coreDataPatch('monthly', [], { selectedYear: null, currentYear: 2026 }).selectedYear, 2026);
});

test('SPEC-094 each resource owns its fields and malformed payloads are refused', () => {
  const goal = { version: 3, start_year: 2026, monthly_km: 150, yearly_km: 1800 };
  assert.deepEqual(rules.coreDataPatch('goal', goal), { runningGoal: goal });
  assert.deepEqual(rules.coreDataPatch('strava-history', [{ id: 1 }]), { stravaImports: [{ id: 1 }] });
  assert.deepEqual(rules.coreDataPatch('spending', null), { spendingSummary: null });
  const summary = { monthly: [{ month: '2026-01', paid: 3000 }] };
  assert.deepEqual(rules.coreDataPatch('spending', summary), { spendingSummary: summary, monthlySpending: summary.monthly });
  assert.throws(() => rules.coreDataPatch('spending', { monthly: 'oops' }), /支出資料格式不正確/);
  assert.throws(() => rules.coreDataPatch('shoes', [[], null]), /資料格式不正確/);
  assert.throws(() => rules.coreDataPatch('strava-history', {}), /資料格式不正確/);
  assert.throws(() => rules.coreDataPatch('goal', null), /目標資料格式不正確/);
  assert.throws(() => rules.coreDataPatch('runs', []), /Unknown core data resource/);
});

test('SPEC-094 the bridge writes only the patched globals and resets to the module defaults', () => {
  const context = bridgeContext();
  assert.deepEqual(read(context, '[shoes, retiredShoes, monthlyMileages, runningGoal, stravaImports, spendingSummary, monthlySpending]'),
    rules.CORE_DATA_FIELDS.map(field => rules.coreDataDefaults()[field]), 'app-state.js starts from coreDataDefaults()');

  context.appCalendarDate = () => ({ year: 2026, month: 11, day: 21 });
  context.applyCoreResource('shoes', [[{ id: 4, date: '2026-02-02' }, { id: 3, date: '2025-02-02' }], []]);
  context.applyCoreResource('monthly', [{ year: 2025, month: 4, km: 80 }]);
  context.applyCoreResource('goal', { version: 1, start_year: 2026, monthly_km: 100, yearly_km: 1200 });
  assert.deepEqual(read(context, 'shoes.map(shoe => shoe.id)'), [3, 4]);
  assert.equal(read(context, 'selectedYear'), 2025);
  assert.equal(read(context, 'runningGoal.monthly_km'), 100);
  assert.equal(read(context, 'monthlyMileages.length'), 1, 'a goal write leaves monthly history alone');

  nodeVm.runInContext("selectedSpendingYear = 2025; featureResetters.get('dashboard-data')(); featureResetters.get('dashboard-selection')()", context);
  assert.deepEqual(read(context, '[shoes, runningGoal, selectedYear, selectedSpendingYear]'),
    [[], rules.coreDataDefaults().runningGoal, null, null]);
});
