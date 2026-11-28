// SPEC-094/095: core account data has one writer and lives in a DOM-independent store.
const nodeVm = require('node:vm');
const { test, assert, readText } = require('./helpers.cjs');

let rules;
require('node:test').before(async () => {
  rules = await import('../../frontend/runtime/core-data.mjs');
});

// The real app-lifecycle.js, app-state.js and app-resources.js, with the native store installed.
function bridgeContext() {
  const context = nodeVm.createContext({ document: { getElementById: () => null, querySelectorAll: () => [] },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} }, console, window: new EventTarget() });
  for (const file of ['app-lifecycle.js', 'app-state.js', 'app-resources.js']) {
    nodeVm.runInContext(readText('frontend/' + file), context, { filename: file });
  }
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

test('SPEC-095 scripts read core data through the store view, which only the bridge changes', () => {
  const context = bridgeContext();
  const fields = () => read(context, `[${rules.CORE_DATA_FIELDS.map(field => 'coreData.' + field).join(', ')}]`);
  assert.deepEqual(fields(), rules.CORE_DATA_FIELDS.map(field => rules.coreDataDefaults()[field]),
    'the placeholder in app-state.js equals coreDataDefaults()');
  for (const field of rules.CORE_DATA_FIELDS) {
    assert.equal(nodeVm.runInContext(`typeof ${field}`, context), 'undefined', `no global named ${field} remains`);
  }

  context.appCalendarDate = () => ({ year: 2026, month: 11, day: 21 });
  context.useCoreDataStore(rules.createCoreDataStore());
  context.applyCoreResource('shoes', [[{ id: 4, date: '2026-02-02' }, { id: 3, date: '2025-02-02' }], []]);
  context.applyCoreResource('monthly', [{ year: 2025, month: 4, km: 80 }]);
  context.applyCoreResource('goal', { version: 1, start_year: 2026, monthly_km: 100, yearly_km: 1200 });
  assert.deepEqual(read(context, 'coreData.shoes.map(shoe => shoe.id)'), [3, 4]);
  assert.equal(read(context, 'selectedYear'), 2025);
  assert.equal(read(context, 'coreData.runningGoal.monthly_km'), 100);
  assert.equal(read(context, 'coreData.monthlyMileages.length'), 1, 'a goal write leaves monthly history alone');

  nodeVm.runInContext("selectedSpendingYear = 2025; featureResetters.get('dashboard-data')(); featureResetters.get('dashboard-selection')()", context);
  assert.deepEqual(read(context, '[coreData.shoes, coreData.runningGoal, selectedYear, selectedSpendingYear]'),
    [[], rules.coreDataDefaults().runningGoal, null, null]);
});

test('SPEC-095 the store view is read-only and its shared arrays cannot change in place', () => {
  const store = rules.createCoreDataStore({ shoes: [{ id: 2, date: '2026-01-01' }, { id: 1, date: '2025-01-01' }] });
  const { view } = store;
  assert.throws(() => { 'use strict'; view.shoes = []; }, TypeError);
  assert.throws(() => view.shoes.push({ id: 3 }), TypeError);
  assert.throws(() => view.shoes.sort((a, b) => a.id - b.id), TypeError);
  assert.deepEqual(view.shoes.map(shoe => shoe.id), [2, 1]);
  assert.throws(() => rules.createCoreDataStore({ runs: [] }), /Unknown core data fields: runs/);

  const before = view.shoes;
  store.apply('goal', { version: 5, start_year: 2026, monthly_km: 90, yearly_km: 1080 });
  assert.equal(view.shoes, before, 'applying the goal keeps the shoe array');
  assert.equal(view.runningGoal.version, 5);
  const summary = { monthly: [{ year: 2026, paid: 10 }] };
  store.apply('spending', summary);
  assert.throws(() => view.monthlySpending.push({}), TypeError);
  assert.equal(Object.isFrozen(summary.monthly), false, "the caller's response is not frozen");
  store.reset();
  assert.deepEqual(JSON.parse(JSON.stringify(view)), rules.coreDataDefaults());
});
