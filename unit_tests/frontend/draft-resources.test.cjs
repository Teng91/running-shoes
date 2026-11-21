const { test, assert, vm, extract, source, runContext } = require('./helpers.cjs');
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function nodes() {
  const primary = {};
  return new Proxy({}, { get: (all, id) => all[id] ||= { value: '', style: {}, hidden: false,
    setAttribute() {}, contains: () => false, focus() {},
    parentElement: { style: {} }, querySelector: () => primary,
    classList: { add() {}, remove() {} } } });
}

test('SPEC-024 shoe transitions preserve only new edits and retain the server state', async () => {
  const definition = source.slice(source.indexOf('class ShoeModal {'), source.indexOf('// 初始化一次'));
  for (const retired of [false, true]) for (const editMileage of [false, true]) {
    const elements = nodes(), pending = deferred(), writes = [];
    const categories = [{ value: 'Daily', checked: true }, { value: 'Race', checked: false }];
    const context = vm.createContext({ document: { getElementById: id => elements[id], querySelectorAll: () => categories },
      getSelectedCategories: () => categories.filter(item => item.checked).map(item => item.value),
      shoeCategories: shoe => shoe.categories, captureAuthSession: () => ({}), isCurrentAuthSession: () => true,
      shoes: [], confirm: () => true, alert: assert.fail, loadData: async () => {},
    });
    vm.runInContext(definition + '\nglobalThis.Modal = ShoeModal;', context);
    const original = { id: 7, version: 3, nickname: '', brand: 'Test', model: 'Runner', date: '2026-01-01',
      size: '', price: 1000, orig_price: 2000, mileage: 50, expected_mileage: 800,
      monthly_km: retired ? 0 : 60, is_retired: retired, categories: ['Daily'] };
    context.apiPut = (_, payload) => {
      writes.push(payload);
      return writes.length === 1 ? pending.promise : Promise.resolve({ ...original, ...writes[0], ...payload, version: 5 });
    };
    const modal = new context.Modal(); modal.openForEdit(original, retired);
    const moving = modal.move(); elements['f-nickname'].value = 'new nickname';
    if (editMileage) {
      elements['f-mileage'].value = '80';
      categories[0].checked = false; categories[1].checked = true;
    }
    pending.resolve({ ...original, ...writes[0], version: 4 }); await moving;
    assert.equal(modal.mode, retired ? 'editActive' : 'editRetired');
    assert.equal(modal.context.shoe.version, 4); assert.equal(elements['f-nickname'].value, 'new nickname');
    assert.equal(Number(elements['f-monthly'].value), writes[0].monthly_km);
    await modal.submit();
    assert.deepEqual(JSON.parse(JSON.stringify(writes[1])), {
      nickname: 'new nickname', ...(editMileage ? { mileage: 80, categories: ['Race'] } : {}), expected_version: 4,
    });
  }
});

test('SPEC-024 goal drafts survive redraw and save acknowledgements', async () => {
  const elements = nodes(), pending = deferred(), writes = [];
  const context = vm.createContext({ document: { getElementById: id => elements[id] },
    runningGoal: { version: 1, start_year: 2026, monthly_km: 125 }, selectedYear: 2026,
    monthlyMileages: [], goalProgressCache: new Map(), loadGoalProgress() {}, invalidatePanels() {},
    apiPut: (_, payload) => { writes.push(payload); return writes.length === 1 ? pending.promise : Promise.resolve({ ...payload, version: 3 }); },
  });
  vm.runInContext('let goalSaveOperation = null, goalProgressRequestId = 0;\n' +
    [extract('renderGoalProgress'), extract('saveRunningGoal')].join('\n'), context);
  context.renderActivePanel = () => context.renderGoalProgress();
  context.renderGoalProgress(); elements['goal-monthly-km'].value = '180';
  elements['goal-settings'].hidden = true; // collapsed as in the template
  context.renderGoalProgress(); assert.equal(elements['goal-monthly-km'].value, '180');
  assert.equal(elements['goal-settings'].hidden, false, 'SPEC-044 an unsaved goal draft reopens the editor');
  const saving = context.saveRunningGoal();
  elements['goal-monthly-km'].value = '200'; elements['goal-start-year'].value = '2027';
  pending.resolve({ version: 2, start_year: 2026, monthly_km: 180 }); await saving;
  assert.equal(elements['goal-monthly-km'].value, '200'); assert.equal(elements['goal-start-year'].value, '2027');
  assert.match(elements['goal-settings-status'].textContent, /尚未儲存/);
  assert.equal(elements['goal-settings'].hidden, false, 'newer input keeps the editor open');
  await context.saveRunningGoal();
  assert.equal(writes[1].expected_version, 2); assert.equal(writes[1].monthly_km, 200);
  assert.equal(elements['goal-settings'].hidden, true, 'SPEC-044 a clean save collapses the editor');
  context.seedCoreData({ runningGoal: { version: 4, start_year: 2027, monthly_km: 220 } }); context.renderGoalProgress();
  assert.equal(elements['goal-monthly-km'].value, '220', 'clean form follows new server values');
  context.getFormDraft('goal').reset(); context.seedCoreData({ runningGoal: { version: 0, start_year: 2026, monthly_km: 100 } });
  elements['goal-monthly-km'].value = '999'; context.renderGoalProgress();
  assert.equal(elements['goal-monthly-km'].value, '100', 'reset cannot retain another account draft');
});

test('SPEC-024 resources coalesce reads and reject superseded sessions and keys', async () => {
  const { createResourceStore } = await import('../../frontend/runtime/resource-store.mjs');
  let session = { valid: true }, calls = 0;
  const store = createResourceStore({ session: { capture: () => session, current: value => value.valid } });
  const first = deferred();
  const a = store.read('runs', { key: '2026-01', loader: () => { calls++; return first.promise; } });
  const b = store.read('runs', { key: '2026-01', loader: assert.fail });
  assert.equal(a, b); await Promise.resolve(); assert.equal(calls, 1);
  first.resolve(100); const result = await a;
  assert.equal(store.accept([result]).length, 1); assert.equal(store.accept([result]).length, 0);
  const cached = await store.read('runs', { key: '2026-01', loader: assert.fail, refresh: false });
  assert.equal(cached.value, 100);
  const stale = deferred(); const old = store.read('runs', { key: '2026-01', loader: () => stale.promise });
  const next = await store.read('runs', { key: '2026-02', loader: () => 180 });
  stale.resolve(99); assert.equal(store.accept([await old]).length, 0); assert.equal(store.accept([next]).length, 1);
  await store.read('goal', { loader: () => { throw Error('private old error'); } });
  session.valid = false;
  assert.equal(store.getError('goal'), undefined); assert.equal(store.hasErrors(), false);
  session = { valid: true };
  const late = deferred(); const oldSession = store.read('monthly', { loader: () => late.promise });
  session.valid = false; session = { valid: true }; store.reset(); late.resolve(999);
  assert.equal(store.accept([await oldSession]).length, 0);
  const latest = await store.refresh('monthly', { monthly: () => 200 });
  assert.equal(store.accept(latest, 'monthly')[0].value, 200);
});

test('SPEC-024 independent resource failures preserve successful data and relevant caches', async () => {
  const { createResourceStore } = await import('../../frontend/runtime/resource-store.mjs');
  const store = createResourceStore({ session: { capture: () => ({}), current: () => true } });
  const invalidated = [];
  for (const cache of ['goal', 'dashboard', 'annual', 'spending']) store.registerCache(cache, () => invalidated.push(cache));
  const results = await store.refresh(null, { shoes: () => [7], monthly: () => { throw Error('monthly offline'); }, runs: () => [], goal: () => ({ version: 1 }) });
  const accepted = store.accept(results);
  assert.equal(accepted.filter(result => result.status === 'fulfilled').length, 3);
  assert.equal(store.hasErrors(), true); assert.match(store.getError('monthly').message, /offline/);
  invalidated.length = 0;
  store.accept(await store.refresh('shoe', { shoes: () => [8] }), 'shoe');
  assert.equal(store.hasErrors(), true); assert.deepEqual(invalidated.sort(), ['dashboard', 'spending']);
  store.accept(await store.refresh('monthly', { monthly: () => [180] }), 'monthly');
  assert.equal(store.hasErrors(), false);
  const delayed = deferred(); const old = store.read('monthly', { loader: () => delayed.promise });
  const changed = await store.refresh('monthly', { monthly: () => [200] });
  delayed.resolve([100]); assert.equal(store.accept([await old]).length, 0);
  assert.deepEqual(store.accept(changed, 'monthly')[0].value, [200]);
});

test('SPEC-024 coalesced dashboard loads apply run rows once despite partial failures', async () => {
  const elements = nodes(), calls = [];
  const context = runContext({ document: { getElementById: id => elements[id] },
    goalProgressCache: new Map(), selectedRunMonth: () => '2026-10', render() {}, loadStravaHistory() {}, console: { error() {} },
    apiGet: async url => { calls.push(url); if (url === '/running-goal') throw Error('goal offline'); return url === '/monthly-mileage' ? [{ year: 2026 }] : []; },
    fetchRunPage: async () => { calls.push('page'); return { rows: [{ id: 42 }], hasMore: false }; },
  });
  vm.runInContext(`let selectedYear;
    let spendingLoadRequestId=0, spendingLoadPending=false, goalProgressRequestId=0;
    ${extract('loadData')}`, context);
  await Promise.all([context.loadData(), context.loadData()]);
  assert.equal(calls.length, 6); assert.equal(calls.filter(name => name === 'page').length, 1);
  assert.equal(context.runController.state.rows[0].id, 42);
  assert.equal(context.coreData.monthlyMileages[0].year, 2026);
  assert.equal(elements['data-load-error'].hidden, false);
  context.invalidateDataResources(['goal']);
  assert.equal(elements['data-load-error'].hidden, true, 'acknowledged goal write clears its recovered read error');
});
