const { test, assert, vm, extract, source, runContext } = require('./helpers.cjs');
const { observeWorkerUpdate } = require('../../scripts/worker_update.cjs');
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
const flush = () => new Promise(resolve => setImmediate(resolve));
function nodes() { return new Proxy({}, { get: (all, id) => all[id] ||= { value: '', style: {}, hidden: false,
  parentElement: { style: {} }, querySelector: () => ({}), classList: { add() {}, remove() {}, contains: () => true } } }); }

test('SPEC-025 deleted shoe selection remains explicit across redraws', () => {
  function select() { return { value: '', set innerHTML(html) { this.html = html; this.value = html.match(/value="([^"]*)"/)?.[1] || ''; },
    insertAdjacentHTML(_, html) { this.html = html + this.html; this.value = ''; } }; }
  const elements = { 'run-shoe': select(), 'edit-run-shoe': select() };
  const context = vm.createContext({ document: { getElementById: id => elements[id] }, esc: String,
    allRunShoes: () => [{ id: 1, brand: 'Test', model: 'Runner' }] });
  vm.runInContext(extract('populateRunShoeSelects'), context);
  context.populateRunShoeSelects(999); context.populateRunShoeSelects();
  assert.equal(elements['edit-run-shoe'].value, ''); assert.match(elements['edit-run-shoe'].html, /請重新選擇/);
  assert.equal(elements['run-shoe'].value, '1');
  elements['edit-run-shoe'].value = '1'; context.populateRunShoeSelects();
  assert.equal(elements['edit-run-shoe'].value, '1', 'explicit replacement survives another redraw');
});

test('SPEC-025 Strava ownership protects replacement previews and sessions', async () => {
  const { createStravaController } = await import('../../frontend/runtime/strava-controller.mjs');
  let session = { valid: true }; const uploads = [];
  const controller = createStravaController({ session: { capture: () => session, current: value => value.valid },
    transport: { upload: (...args) => uploads.push(args) } });
  controller.open(); const first = controller.beginPreview();
  controller.preview(first, 'first.csv', {}); controller.acceptPreview(first, { run_count: 1 }, 'first');
  const importing = controller.beginImport('first'); assert.ok(importing);
  assert.equal(controller.beginImport('first'), null, 'cannot double-submit');
  controller.import(importing, 'first.csv', {});
  controller.close(); controller.open(); const second = controller.beginPreview();
  controller.acceptPreview(second, { run_count: 2 }, 'second');
  assert.equal(controller.ownsImport(importing), false); assert.equal(controller.sessionCurrent(importing), true);
  assert.equal(controller.acceptPreview(first, {}, 'first'), false); assert.equal(first.controller.signal.aborted, true);
  controller.finishImport(importing); assert.equal(controller.state.key, 'second');
  const next = controller.beginImport('second'); controller.beginPreview();
  assert.equal(controller.ownsImport(next), false); assert.equal(controller.windowCurrent(next), true);
  assert.equal(controller.beginImport('second'), null);
  controller.finishImport(next); controller.finishPreview(second);
  session.valid = false; session = { valid: true };
  assert.equal(controller.sessionCurrent(importing), false); controller.reset();
  assert.equal(controller.state.preview, null); assert.equal(uploads.length, 2);
});

test('SPEC-025 Strava history invalidation rejects older reads', async () => {
  const elements = nodes(), old = deferred(); let calls = 0;
  const context = vm.createContext({ document: { getElementById: id => elements[id] },
    apiGet: () => ++calls === 1 ? old.promise : Promise.resolve([{ end_date: '2026-10-20' }]),
    renderStravaStatus() {}, renderStravaImportHistory() {}, console: { warn: assert.fail } });
  vm.runInContext('let stravaImports = [];\n' + extract('loadStravaHistory'), context);
  const stale = context.loadStravaHistory(); await flush();
  context.resourceStore.invalidate(['strava-history']);
  await Promise.all([context.loadStravaHistory(), context.loadStravaHistory()]);
  old.resolve([]); await stale;
  assert.equal(calls, 2); assert.equal(vm.runInContext('stravaImports[0].end_date', context), '2026-10-20');
});

test('SPEC-025 retirement preserves edits made before the command', async () => {
  const definition = source.slice(source.indexOf('class ShoeModal {'), source.indexOf('// 初始化一次'));
  const elements = nodes(), writes = [], categories = [{ value: 'Daily', checked: true }, { value: 'Race', checked: false }];
  const original = { id: 7, version: 3, nickname: '', brand: 'Test', model: 'Runner', date: '2026-01-01',
    size: '', price: 1000, orig_price: 2000, mileage: 50, expected_mileage: 800, monthly_km: 60,
    is_retired: false, categories: ['Daily'] };
  const context = vm.createContext({ document: { getElementById: id => elements[id], querySelectorAll: () => categories },
    getSelectedCategories: () => categories.filter(item => item.checked).map(item => item.value), shoeCategories: shoe => shoe.categories,
    shoes: [], confirm: () => true, alert: assert.fail, loadData: async () => {},
    apiPut: async (_, payload) => { writes.push(payload); return { ...original, ...writes[0], ...payload, version: 3 + writes.length }; } });
  vm.runInContext(definition + '\nglobalThis.Modal = ShoeModal;', context);
  const modal = new context.Modal(); modal.openForEdit(original, false);
  elements['f-nickname'].value = 'before move'; categories[1].checked = true;
  await modal.move(); assert.ok(modal.context); assert.equal(modal.mode, 'editRetired');
  assert.equal(elements['f-nickname'].value, 'before move'); assert.equal(categories[1].checked, true);
  await modal.submit(); assert.deepEqual(JSON.parse(JSON.stringify(writes[1])), {
    nickname: 'before move', categories: ['Daily', 'Race'], expected_version: 4 });
});

test('SPEC-025 resource completion is delivered before slow peers', async () => {
  const { createResourceStore } = await import('../../frontend/runtime/resource-store.mjs');
  const slow = deferred(), delivered = [];
  const store = createResourceStore({ session: { capture: () => ({}), current: () => true } });
  const loading = store.refresh(null, { shoes: () => [1], monthly: () => slow.promise, runs: () => [], goal: () => { throw Error('goal offline'); } }, {},
    result => delivered.push(...store.accept([result])));
  await flush(); assert.deepEqual(delivered.map(item => item.resource).sort(), ['goal', 'runs', 'shoes']);
  assert.equal(store.hasErrors(), true); slow.resolve([180]); await loading;
  assert.equal(delivered.at(-1).resource, 'monthly');
});

test('SPEC-025 dashboard renders fast resources while a peer remains pending', async () => {
  const elements = nodes(), slow = deferred(); let renders = 0, boots = 0;
  const context = runContext({ document: { getElementById: id => elements[id] }, selectedRunMonth: () => '2026-10',
    goalProgressCache: new Map(), render: () => renders++, hideAppBoot: () => boots++, loadStravaHistory() {},
    apiGet: async url => url === '/running-goal' ? slow.promise : [], fetchRunPage: async () => ({ rows: [{ id: 42 }], hasMore: false }) });
  vm.runInContext(`let shoes=[], retiredShoes=[], monthlyMileages=[], runningGoal={}, selectedYear;
    let spendingSummary, spendingLoadRequestId=0, spendingLoadPending=false, goalProgressRequestId=0;
    ${extract('loadData')}`, context);
  const loading = context.loadData(); await flush();
  assert.equal(context.runController.state.rows[0].id, 42); assert.ok(renders > 0); assert.ok(boots > 0);
  slow.resolve({ monthly_km: 180 }); await loading;
  assert.equal(vm.runInContext('runningGoal.monthly_km', context), 180);
});

test('SPEC-025 worker observer handles an already installing candidate', async () => {
  const worker = new EventTarget(); worker.state = 'installing';
  const registration = new EventTarget(); registration.installing = worker;
  const observing = observeWorkerUpdate({ registration, trigger: false, timeoutMs: 100 });
  worker.state = 'activated'; worker.dispatchEvent(new Event('statechange'));
  assert.equal(await observing, 'activated');
});

test('SPEC-025 worker deadlines include registration and candidate diagnostics', async () => {
  const registration = new EventTarget(); registration.update = () => new Promise(() => {});
  await assert.rejects(observeWorkerUpdate({ registration, timeoutMs: 10 }), /Worker registration timeline:.*observe.*failure/);
  registration.update = async () => { throw Error('network update failed'); };
  await assert.rejects(observeWorkerUpdate({ registration, timeoutMs: 100 }), /network update failed.*\nWorker registration timeline/);
});

test('SPEC-025 worker refuses truncated identity bodies without comparing compressed lengths', async () => {
  const fs = require('node:fs');
  const worker = fs.readFileSync('frontend/service-worker.js', 'utf8');
  for (const [encoding, length, expected] of [[null, '1000', false], [null, '2', true], ['gzip', '1000', true], [null, null, true]]) {
    let skipped = false, deleted = false;
    const response = { ok: true, headers: { get: key => key === 'content-length' ? length : key === 'content-encoding' ? encoding : 'text/javascript' },
      clone: () => ({ arrayBuffer: async () => new Uint8Array(2).buffer }) };
    const context = vm.createContext({ Request: class {}, fetch: async () => response,
      caches: { has: async () => false, open: async () => ({ put: async () => {} }), delete: async () => { deleted = true; } },
      self: { addEventListener() {}, skipWaiting: async () => { skipped = true; } } });
    // Run the actual installer against one synthetic JS asset.
    vm.runInContext(worker.replace(/const APP_SHELL = \[[\s\S]*?\];/, "const APP_SHELL = ['/app.js'];"), context);
    if (expected) await context.installShell(); else await assert.rejects(context.installShell(), /truncated/);
    assert.equal(skipped, expected); assert.equal(deleted, !expected);
  }
});


test('SPEC-025 worker observer waits for the candidate created by a queued update', async () => {
  const old = new EventTarget(), latest = new EventTarget(); old.state = latest.state = 'installing';
  const registration = new EventTarget(); registration.installing = old;
  const update = deferred(); registration.update = () => update.promise;
  let completed = false;
  const observing = observeWorkerUpdate({ registration, timeoutMs: 100 }).then(state => { completed = true; return state; });
  old.state = 'redundant'; old.dispatchEvent(new Event('statechange'));
  registration.installing = latest; registration.dispatchEvent(new Event('updatefound'));
  update.resolve(); await flush(); assert.equal(completed, false);
  latest.state = 'activated'; registration.installing = null; latest.dispatchEvent(new Event('statechange'));
  assert.equal(await observing, 'activated');
});
