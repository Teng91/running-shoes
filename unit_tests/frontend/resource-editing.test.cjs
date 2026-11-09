const { test, assert, vm, fs, extract, runContext } = require('./helpers.cjs');
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const flush = () => new Promise(resolve => setImmediate(resolve));

test('SPEC-026 new run keeps a removed shoe unselected until explicit replacement', () => {
  function select() { return { value: '', dataset: {}, set innerHTML(html) { this.html = html; this.value = html.match(/value="([^"]*)"/)?.[1] || ''; },
    insertAdjacentHTML(_, html) { this.html = html + this.html; this.value = ''; } }; }
  const elements = { 'run-shoe': select(), 'edit-run-shoe': select() };
  let shoes = [{ id: 1 }, { id: 2 }];
  const context = vm.createContext({ document: { getElementById: id => elements[id] }, esc: String, allRunShoes: () => shoes });
  vm.runInContext(extract('populateRunShoeSelects'), context);
  context.populateRunShoeSelects(); assert.equal(elements['run-shoe'].value, '1');
  shoes = [{ id: 2 }]; context.populateRunShoeSelects(); context.populateRunShoeSelects();
  assert.equal(elements['run-shoe'].value, ''); assert.match(elements['run-shoe'].html, /請重新選擇/);
  shoes = []; context.populateRunShoeSelects(); shoes = [{ id: 2 }]; context.populateRunShoeSelects();
  assert.equal(elements['run-shoe'].value, '');
  elements['run-shoe'].value = '2'; context.populateRunShoeSelects();
  assert.equal(elements['run-shoe'].value, '2'); assert.equal(elements['run-shoe'].dataset.requiresSelection, undefined);
});

test('SPEC-026 inline editors defer table replacement and retain the original version', async () => {
  const handlers = {}, writes = [], table = 'shoe-table';
  const input = { focus() {}, addEventListener: (name, fn) => { handlers[name] = fn; } };
  const el = { querySelector: () => null, closest: () => ({ id: table }), appendChild() {}, innerHTML: '' };
  const context = vm.createContext({ document: { createElement: () => input, getElementById: assert.fail },
    loadData: async () => {}, render() {}, alert: assert.fail,
    apiPut: async (url, payload) => writes.push({ url, ...payload }),
  });
  vm.runInContext([extract('inlineEditRow'), extract('renderTable'), extract('renderRetiredTable')].join('\n'), context);
  await context.inlineEditRow([{ id: 7, mileage: 100, version: 3 }], 0, 'mileage', el);
  input.value = '1';
  assert.equal(context.preserveInlineTable(table), true);
  context.renderTable();
  assert.equal(input.value, '1'); assert.deepEqual(writes, []);
  input.value = '180'; await handlers.blur();
  assert.equal(writes.length, 1); assert.equal(writes[0].expected_version, 3);
  assert.equal(writes[0].mileage, 180); assert.match(writes[0].url, /\/7$/);
  assert.equal(context.preserveInlineTable(table), false);
  await handlers.blur(); assert.equal(writes.length, 1);
});

test('SPEC-026 inline lifecycle cancels blur writes before removing account DOM', async () => {
  let reset, handler; const writes = [];
  const context = vm.createContext({ registerFeatureReset: (_, callback) => { reset = callback; },
    document: { createElement: () => ({ focus() {}, addEventListener: (name, callback) => { if (name === 'blur') handler = callback; } }) },
    apiPut: (...args) => writes.push(args), render() {}, loadData() {},
  });
  vm.runInContext(fs.readFileSync('frontend/app-inline-editors.js', 'utf8') + '\n' + extract('inlineEditRow'), context);
  await context.inlineEditRow([{ id: 1, mileage: 100, version: 1 }], 0, 'mileage', { querySelector: () => null, appendChild() {}, closest: () => ({ id: 'shoe-table' }) });
  reset(); await handler(); assert.deepEqual(writes, []);
});

test('SPEC-026 resource views invalidate only their dependent panels', () => {
  const context = runContext({ renderedPanels: new Map(['shoes', 'monthly', 'runs'].map(name => [name, 'rendered'])) });
  vm.runInContext('let panelRevision = 0;\n' + extract('invalidatePanels'), context);
  context.invalidatePanels('goal');
  assert.deepEqual([...context.renderedPanels.keys()], ['shoes']);
  assert.equal(vm.runInContext('panelRevision', context), 0);
  context.invalidatePanels('shoes'); assert.equal(context.renderedPanels.size, 0);
});

test('SPEC-026 derived reads coalesce and reject invalidated responses', async () => {
  const elements = new Proxy({}, { get: (all, id) => all[id] ||= { innerHTML: '', value: '2026' } });
  const pending = deferred(), calls = [], rendered = [];
  const context = runContext({ document: { getElementById: id => elements[id], querySelector: () => ({ dataset: { panel: 'monthly' } }) },
    authToken: 'synthetic', localDateISO: () => '2026-10-23', selectedYear: 2026,
    runningGoal: { version: 1 }, goalProgressCache: new Map(), selectedRunMonth: () => '2026-10', chartInstances: {}, shoes: [], retiredShoes: [],
    renderedPanels: new Map(), getThemeColor: () => '#000', brandColor: () => '#000', shoeColor: () => '#000',
    Chart: function(_, config) { this.config = config; this.destroy = () => {}; },
    apiGet: url => { calls.push(url); return pending.promise; },
    renderGoalOverview: value => rendered.push(value), renderDashboardInsights: value => rendered.push(value), esc: String,
  });
  vm.runInContext('let goalProgressRequestId = 0;\n' + ['loadGoalProgress', 'loadDashboardAnalytics', 'renderShoeStackedChart'].map(extract).join('\n'), context);
  const requests = [];
  for (let index = 0; index < 5; index++) requests.push(context.loadGoalProgress(2026), context.loadDashboardAnalytics('2026-10'), context.renderShoeStackedChart());
  await flush(); assert.equal(calls.length, 3);
  context.resourceStore.invalidate(['goal-progress', 'dashboard-analytics', 'annual-summary']);
  pending.resolve({ shoes: [] }); await Promise.all(requests); assert.deepEqual(rendered, []);
  context.apiGet = async url => { calls.push(url); return url.startsWith('/running-goal/year') ? { year: 2026, months: [] } : { shoes: [] }; };
  await Promise.all([context.loadGoalProgress(2026), context.loadDashboardAnalytics('2026-10'), context.renderShoeStackedChart()]);
  assert.equal(calls.length, 6); assert.equal(rendered.length, 2);
  context.resourceStore.invalidate(['annual-summary']);
  context.console = { error() {} };
  context.apiGet = async () => ({});
  await context.renderShoeStackedChart();
  assert.match(context.resourceStore.getError('annual-summary').message, /格式錯誤/);
  context.apiGet = async () => ({ shoes: [] });
  await context.renderShoeStackedChart();
  assert.equal(context.resourceStore.getError('annual-summary'), undefined, 'malformed data can be retried');
});

test('SPEC-026 discarded resource dispatch cannot borrow the next account token', async () => {
  const { createResourceStore } = await import('../../frontend/runtime/resource-store.mjs');
  let generation = 1, calls = 0;
  const store = createResourceStore({ session: { capture: () => generation, current: value => value === generation } });
  const old = store.read('dashboard-analytics', { loader: () => { calls++; return 'private'; } });
  generation++;
  assert.equal((await old).status, 'rejected'); assert.equal(calls, 0);
  assert.equal(store.hasErrors(), false);
  const invalidated = store.read('annual-summary', { loader: assert.fail }); store.invalidate(['annual-summary']);
  assert.equal((await invalidated).error.name, 'AbortError');
});

test('SPEC-026 Strava mapping lock follows the current import window', async () => {
  const { createStravaController } = await import('../../frontend/runtime/strava-controller.mjs');
  const pending = deferred(), controls = [{ disabled: false }];
  const elements = { 'strava-file': { files: [{ name: 'a', size: 1, lastModified: 1 }] },
    'strava-start-date': { value: '' }, 'strava-end-date': { value: '' }, 'strava-map-0': { value: '1' },
    'strava-error': { style: {} }, 'strava-import-btn': {} };
  const controller = createStravaController({ session: { capture: () => ({}), current: () => true }, transport: { upload: () => pending.promise } });
  controller.open(); let preview = controller.beginPreview(); controller.acceptPreview(preview, { gear_groups: [{ gear: 'A' }], importable_count: 1 }, 'a|1|1||');
  const context = vm.createContext({ stravaController: controller, document: { getElementById: id => elements[id], querySelectorAll: () => controls },
    closeStravaModal: () => controller.close(), alert() {}, loadData: async () => {} });
  vm.runInContext(['stravaInputKey', 'setStravaMappingDisabled', 'importStrava'].map(extract).join('\n'), context);
  const importing = context.importStrava(); assert.equal(controls[0].disabled, true);
  controller.close(); controller.open(); preview = controller.beginPreview();
  controller.acceptPreview(preview, { gear_groups: [{ gear: 'B' }], importable_count: 1 }, 'new');
  controls[0].disabled = true; pending.resolve({ imported: 1 }); await importing;
  assert.equal(controls[0].disabled, true, 'old completion cannot unlock a replacement window');
});
