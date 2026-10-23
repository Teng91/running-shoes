const { test, assert, vm, fs, extract, runContext, source } = require('./helpers.cjs');

function nodes() {
  return new Proxy({}, { get: (target, id) => target[id] ||= { dataset: {}, value: '', style: {}, hidden: true,
    insertAdjacentHTML(_, html) { this.innerHTML = html + this.innerHTML; },
    classList: { add() {}, remove() {} } } });
}
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }

function monthlyContext() {
  const elements = nodes(), request = deferred(), reloads = [];
  let session = { current: true };
  const context = vm.createContext({ document: { getElementById: id => elements[id] },
    captureAuthSession: () => session, isCurrentAuthSession: value => value.current,
    apiPost: () => request.promise, loadData: async options => reloads.push(options), translateError: value => value,
  });
  vm.runInContext('let monthlySaving = false;\n' + extract('addMonthlyMileage'), context);
  Object.assign(elements['add-year'], { value: '2026' });
  elements['add-month'].value = '10'; elements['add-km'].value = '100';
  return { context, elements, request, reloads, reset() {
    session.current = false; session = { current: true };
    context.getFormOperations('monthly').reset(); vm.runInContext('monthlySaving = false', context);
  } };
}

test('SPEC-023 monthly save preserves changed month and distance but clears an unchanged draft', async () => {
  for (const changed of [false, true]) {
    const { context, elements, request, reloads } = monthlyContext();
    const saving = context.addMonthlyMileage();
    if (changed) { elements['add-month'].value = '11'; elements['add-km'].value = '180'; }
    request.resolve({}); await saving;
    assert.equal(elements['add-km'].value, changed ? '180' : '');
    assert.equal(elements['add-month'].value, changed ? '11' : '10');
    assert.equal(reloads[0].mutation, 'monthly');
    assert.equal(elements['add-monthly-btn'].disabled, false);
  }
});

test('SPEC-023 stale monthly completions cannot clear errors or unlock a replacement operation', async () => {
  for (const failure of [false, true]) {
    const { context, elements, request, reset, reloads } = monthlyContext();
    const old = context.addMonthlyMileage(); reset();
    const next = deferred(); context.apiPost = () => next.promise;
    elements['add-km'].value = '180';
    const replacement = context.addMonthlyMileage();
    if (failure) request.reject(new Error('old failure')); else request.resolve({});
    await old;
    assert.equal(elements['add-km'].value, '180'); assert.equal(elements['add-monthly-btn'].disabled, true);
    assert.equal(elements['add-error'].style.display, 'none'); assert.equal(reloads.length, 0);
    next.resolve({}); await replacement;
    assert.equal(elements['add-monthly-btn'].disabled, false);
  }
});

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
  const context = vm.createContext({ document: { getElementById: id => elements[id] },
    allRunShoes: () => [{ id: 7, brand: 'Same', model: 'Model', date: '2026-01-01', nickname: '<new>' },
      { id: 8, brand: 'Same', model: 'Model', date: '2026-02-01', nickname: '' },
      { id: 9, brand: 'Same', model: 'Model', date: '2026-01-01', nickname: '' }],
    esc: value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
  });
  vm.runInContext(extract('populateRunShoeSelects'), context); context.populateRunShoeSelects();
  const options = elements['run-shoe'].innerHTML;
  assert.match(options, /&lt;new&gt; · Same Model · 2026-01-01 · #7/);
  assert.match(options, /Same Model · 2026-02-01 · #8/); assert.match(options, /Same Model · 2026-01-01 · #9/); assert.doesNotMatch(options, /<new>/);
});

function refreshContext() {
  const elements = nodes(), calls = [];
  const context = runContext({ document: { getElementById: id => elements[id] }, console: { error: assert.fail },
    selectedRunMonth: () => '2026-10', render() {}, loadStravaHistory: () => calls.push('history'),
    apiGet: async url => { calls.push(url); return url === '/monthly-mileage' ? [{ year: 2026, km: 100 }] : []; },
    fetchRunPage: async () => { calls.push('page'); return { rows: [], hasMore: false }; },
    goalProgressCache: new Map([['retained', 1]]),
  });
  vm.runInContext(`let shoes = [], retiredShoes = [], monthlyMileages = [], runningGoal = {}, selectedYear;
    let spendingSummary = { retained: true }, spendingLoadRequestId = 0, spendingLoadPending = false, goalProgressRequestId = 0;
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
  assert.equal(vm.runInContext('spendingSummary.retained', context), true);
  calls.length = 0; await context.loadData({ mutation: 'shoe' });
  assert.deepEqual(calls, ['/shoes/active', '/shoes/retired']);
  assert.equal(vm.runInContext('spendingSummary', context), null);
  assert.equal(context.resourceStore.peek('goal-progress'), 1); assert.equal(context.resourceStore.peek('annual-summary'), 1);
  calls.length = 0; await context.loadData({ mutation: 'run' });
  assert.equal(calls.includes('/running-goal'), false); assert.equal(calls.includes('history'), false);
  assert.equal(calls.length, 5); assert.equal(context.resourceStore.peek('goal-progress'), undefined); assert.equal(context.resourceStore.peek('annual-summary'), undefined);
});

test('SPEC-023 overlapping full and mutation reloads reject stale resources and retain unrelated results', async () => {
  const { context } = refreshContext(), oldMonthly = deferred(); let count = 0;
  context.apiGet = async url => {
    if (url === '/monthly-mileage') return ++count === 1 ? oldMonthly.promise : [{ year: 2026, km: 180 }];
    return [{ id: 7 }];
  };
  const old = context.loadData(); await Promise.resolve(); await context.loadData({ mutation: 'monthly' });
  // A successful goal write owns the newer value even if the full GET is pending.
  context.invalidateDataResources(['goal']); vm.runInContext('runningGoal = { version: 2 }', context);
  oldMonthly.resolve([{ year: 2026, km: 100 }]); await old;
  assert.equal(vm.runInContext('monthlyMileages[0].km', context), 180);
  assert.equal(vm.runInContext('shoes[0].id', context), 7);
  assert.equal(vm.runInContext('runningGoal.version', context), 2);
  const stale = deferred(); context.apiGet = () => stale.promise;
  const session = { current: true }; context.captureAuthSession = () => session; context.isCurrentAuthSession = value => value.current;
  const pending = context.loadData({ mutation: 'monthly' }); session.current = false;
  stale.resolve([{ year: 2026, km: 999 }]); await pending;
  assert.equal(vm.runInContext('monthlyMileages[0].km', context), 180);
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
