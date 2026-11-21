const { test, assert, vm, fs, extract, runContext, source, htmlSource } = require('./helpers.cjs');

function nodes() {
  return new Proxy({}, { get: (target, id) => target[id] ||= { dataset: {}, value: '', style: {}, hidden: true,
    insertAdjacentHTML(_, html) { this.innerHTML = html + this.innerHTML; },
    classList: { add() {}, remove() {} } } });
}
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }

test('SPEC-023 operation owners preserve identity after reset and isolate independent features', async () => {
  const { createFormOperations, matchesSnapshot } = await import('../../frontend/runtime/form-operations.mjs');
  let session = { current: true };
  const dependencies = { capture: () => session, current: value => value.current };
  const monthly = createFormOperations(dependencies), shoes = createFormOperations(dependencies);
  const form = { km: '100', categories: ['Daily'] }, old = monthly.begin('create', form);
  form.categories.push('Race'); assert.equal(old.form.categories.length, 1);
  assert.equal(monthly.begin('create'), null); assert.equal(shoes.begin('create') !== null, true);
  monthly.reset(); const next = monthly.begin('create', { km: '180' });
  assert.equal(monthly.owns('create', old), false); assert.equal(monthly.finish('create', old), false);
  assert.equal(monthly.owns('create', next), true); assert.equal(matchesSnapshot(old.form, form), false);
  session.current = false; session = { current: true };
  assert.equal(monthly.owns('create', next), false);
});

test('SPEC-023 shoe save preserves an edited draft and rebases its optimistic version', async () => {
  const elements = nodes(), pending = deferred(); let closed = 0;
  const context = vm.createContext({ document: { getElementById: id => elements[id] },
    loadData: async () => {}, apiPut: () => pending.promise, alert: assert.fail,
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true,
  });
  const definition = source.slice(source.indexOf('class ShoeModal {'), source.indexOf('// 初始化一次'));
  vm.runInContext(definition + '\nglobalThis.Modal = ShoeModal;', context);
  const button = {}, modal = Object.create(context.Modal.prototype);
  const original = { id: 7, version: 3, brand: 'Same', model: 'Model', date: '2026-01-01' };
  Object.assign(modal, { formIds: { model: 'f-model' }, mode: 'editActive',
    context: { mode: 'editActive', shoe: original, session: {} }, btnDelete: {}, btnMove: {},
    el: { querySelector: () => button }, close() { closed++; }, _payload: () => original,
    _fillForm(saved) { elements['f-model'].value = saved.model; }, _updateUI() {},
  });
  elements['f-model'].value = 'submitted'; const saving = modal.submit();
  elements['f-model'].value = 'new draft'; pending.resolve({ ...original, version: 4 }); await saving;
  assert.equal(closed, 0); assert.equal(elements['f-model'].value, 'new draft');
  assert.equal(modal.context.shoe.version, 4); assert.equal(button.disabled, false);
});

test('SPEC-023 shoe selectors distinguish duplicate models and escape nicknames', () => {
  const elements = nodes();
  const context = vm.createContext({ document: { getElementById: id => elements[id] }, updateRunDateWarning() {},
    allRunShoes: () => [{ id: 7, brand: 'Same', model: 'Model', date: '2026-01-01', nickname: '<new>' },
      { id: 8, brand: 'Same', model: 'Model', date: '2026-02-01', nickname: '' },
      { id: 9, brand: 'Same', model: 'Model', date: '2026-01-01', nickname: '' }],
    esc: value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
  });
  vm.runInContext(extract('populateRunShoeSelects'), context); context.populateRunShoeSelects();
  const options = elements['run-shoe'].innerHTML;
  assert.match(options, /value="7">&lt;new&gt; · Same Model · 2026-01-01</);
  assert.match(options, /value="8">Same Model · 2026-02-01</);
  assert.match(options, /value="9">Same Model · 2026-01-01</);
  assert.doesNotMatch(options, /#(?:7|8|9)|<new>/);
});

function refreshContext() {
  const elements = nodes(), calls = [];
  const context = runContext({ document: { getElementById: id => elements[id] }, console: { error: assert.fail },
    selectedRunMonth: () => '2026-10', render() {}, loadStravaHistory: () => calls.push('history'),
    apiGet: async url => { calls.push(url); return url === '/monthly-mileage' ? [{ year: 2026, km: 100 }] : []; },
    fetchRunPage: async () => { calls.push('page'); return { rows: [], hasMore: false }; },
    goalProgressCache: new Map([['retained', 1]]),
  });
  context.seedCoreData({ runningGoal: {}, spendingSummary: { retained: true } });
  vm.runInContext(`let selectedYear;
    let spendingLoadRequestId = 0, spendingLoadPending = false, goalProgressRequestId = 0;
    ${extract('loadData')}`, context);
  return { context, calls };
}

test('SPEC-023 mutation refresh limits requests and preserves unrelated caches', async () => {
  const { context, calls } = refreshContext();
  await context.resourceStore.read('annual-summary', { loader: () => 1 });
  await context.resourceStore.read('goal-progress', { loader: () => 1 });
  await context.loadData({ mutation: 'monthly' });
  assert.deepEqual(calls, ['/monthly-mileage']);
  assert.equal(context.resourceStore.peek('goal-progress'), 1); assert.equal(context.resourceStore.peek('annual-summary'), 1);
  assert.equal(context.coreData.spendingSummary.retained, true);
  calls.length = 0; await context.loadData({ mutation: 'shoe' });
  assert.deepEqual(calls, ['/shoes/active', '/shoes/retired']);
  assert.equal(context.coreData.spendingSummary, null);
  assert.equal(context.resourceStore.peek('goal-progress'), 1); assert.equal(context.resourceStore.peek('annual-summary'), 1);
  calls.length = 0; await context.loadData({ mutation: 'run' });
  assert.equal(calls.includes('/running-goal'), false); assert.equal(calls.includes('history'), false);
  assert.equal(calls.length, 5); assert.equal(context.resourceStore.peek('goal-progress'), undefined); assert.equal(context.resourceStore.peek('annual-summary'), undefined);
});

test('SPEC-038 run changes refresh training trends and the rotation timeline; shoe edits refresh the timeline', async () => {
  const { context } = refreshContext();
  const prime = async () => {
    await context.resourceStore.read('training-trends', { key: '2026', loader: () => 1 });
    await context.resourceStore.read('shoe-timeline', { loader: () => 1 });
  };
  await prime(); await context.loadData({ mutation: 'monthly' });
  assert.equal(context.resourceStore.peek('training-trends', '2026'), 1, 'monthly adjustments do not change daily runs');
  assert.equal(context.resourceStore.peek('shoe-timeline'), 1);
  await context.loadData({ mutation: 'run' });
  assert.equal(context.resourceStore.peek('training-trends', '2026'), undefined);
  assert.equal(context.resourceStore.peek('shoe-timeline'), undefined);
  await prime(); await context.loadData({ mutation: 'shoe' });
  assert.equal(context.resourceStore.peek('shoe-timeline'), undefined);
});

test('SPEC-023 overlapping full and mutation reloads reject stale resources and retain unrelated results', async () => {
  const { context } = refreshContext(), oldMonthly = deferred(); let count = 0;
  context.apiGet = async url => {
    if (url === '/monthly-mileage') return ++count === 1 ? oldMonthly.promise : [{ year: 2026, km: 180 }];
    return [{ id: 7 }];
  };
  const old = context.loadData(); await Promise.resolve(); await context.loadData({ mutation: 'monthly' });
  // A successful goal write owns the newer value even if the full GET is pending.
  context.invalidateDataResources(['goal']); context.applyCoreResource('goal', { version: 2 });
  oldMonthly.resolve([{ year: 2026, km: 100 }]); await old;
  assert.equal(context.coreData.monthlyMileages[0].km, 180);
  assert.equal(context.coreData.shoes[0].id, 7);
  assert.equal(context.coreData.runningGoal.version, 2);
  const stale = deferred(); context.apiGet = () => stale.promise;
  const session = { current: true }; context.captureAuthSession = () => session; context.isCurrentAuthSession = value => value.current;
  const pending = context.loadData({ mutation: 'monthly' }); session.current = false;
  stale.resolve([{ year: 2026, km: 999 }]); await pending;
  assert.equal(context.coreData.monthlyMileages[0].km, 180);
  const failed = refreshContext().context;
  failed.console.error = () => {};
  failed.apiGet = async url => { if (url === '/monthly-mileage') throw new Error('offline'); return []; };
  await failed.loadData({ mutation: 'monthly' });
  assert.equal(failed.document.getElementById('data-load-error').hidden, false);
  await failed.loadData({ mutation: 'shoe' });
  assert.equal(failed.document.getElementById('data-load-error').hidden, false, 'unrelated success cannot hide monthly failure');
  failed.apiGet = async () => [];
  await failed.loadData({ mutation: 'monthly' });
  assert.equal(failed.document.getElementById('data-load-error').hidden, true);
});

test('SPEC-046 runs dated before the shoe purchase show a non-blocking reminder', () => {
  const elements = new Proxy({}, { get: (all, id) => all[id] ||= { value: '', textContent: '', hidden: true } });
  const shoe = { id: 2, brand: 'Mizuno', model: 'Wave Rider 29', date: '2025-12-12' };
  const context = vm.createContext({ document: { getElementById: id => elements[id] }, runShoe: id => (id === 2 ? shoe : undefined) });
  vm.runInContext(['prePurchaseWarning', 'updateRunDateWarning'].map(extract).join('\n'), context);
  assert.equal(context.prePurchaseWarning('2025-11-05', shoe), '這天早於這雙鞋的購買日（2025/12/12），確定是穿這雙嗎？仍可儲存。');
  assert.equal(context.prePurchaseWarning('2025-12-12', shoe), '', 'the purchase day itself is fine');
  assert.equal(context.prePurchaseWarning('', shoe), '');
  assert.equal(context.prePurchaseWarning('2025-11-05', undefined), '');
  elements['edit-run-date'].value = '2025-11-05'; elements['edit-run-shoe'].value = '2';
  context.updateRunDateWarning('edit-run');
  assert.equal(elements['edit-run-date-warning'].hidden, false);
  assert.match(elements['edit-run-date-warning'].textContent, /2025\/12\/12/);
  elements['edit-run-date'].value = '2026-01-02'; context.updateRunDateWarning('edit-run');
  assert.equal(elements['edit-run-date-warning'].hidden, true);
  assert.doesNotMatch(extract('addRun') + extract('saveRun'), /prePurchaseWarning/, 'the reminder never blocks saving');
  for (const id of ['run-date-warning', 'edit-run-date-warning']) assert.match(htmlSource, new RegExp(`id="${id}" role="status" hidden`));
});

test('SPEC-046 Strava mapping flags gear whose first activity predates the chosen shoe', () => {
  const elements = new Proxy({}, { get: (all, id) => all[id] ||= { value: '', textContent: '', hidden: true } });
  const shoes = { 6: { id: 6, date: '2026-06-25' }, 1: { id: 1, date: '2025-07-15' } };
  const context = vm.createContext({ document: { getElementById: id => elements[id] }, runShoe: id => shoes[id],
    stravaController: { state: { preview: { gear_groups: [{ gear: 'Nitro', first_date: '2025-11-24' }] } } } });
  vm.runInContext(extract('updateStravaDateWarning'), context);
  elements['strava-map-0'].value = '6'; context.updateStravaDateWarning(0);
  assert.equal(elements['strava-warn-0'].textContent, '最早一筆 2025/11/24 早於這雙鞋的購買日 2026/06/25，請確認配對。');
  assert.equal(elements['strava-warn-0'].hidden, false);
  elements['strava-map-0'].value = '1'; context.updateStravaDateWarning(0);
  assert.equal(elements['strava-warn-0'].hidden, true);
  elements['strava-map-0'].value = ''; context.updateStravaDateWarning(0);
  assert.equal(elements['strava-warn-0'].hidden, true, 'skipped gear has no reminder');
});

test('SPEC-047 Strava preview explains UTC date corrections and allows a correction-only import', () => {
  const context = vm.createContext({});
  vm.runInContext(extract('stravaDateCorrectionText') + extract('stravaHasChanges'), context);
  const preview = { importable_count: 0, date_correction_count: 2,
    date_correction_samples: [{ from_date: '2026-10-31', to_date: '2026-11-01', km: 10 }] };
  assert.equal(context.stravaDateCorrectionText(preview), '另有 2 筆既有紀錄的日期會依台灣時間修正（例如 2026/10/31 → 2026/11/01）。');
  assert.equal(context.stravaHasChanges(preview), true, 'corrections alone enable the import button');
  assert.equal(context.stravaDateCorrectionText({ date_correction_count: 0 }), '');
  assert.equal(context.stravaHasChanges({ importable_count: 0, date_correction_count: 0 }), false);
  assert.equal(context.stravaHasChanges({ importable_count: 3 }), true, 'older servers omit the correction count');
});
