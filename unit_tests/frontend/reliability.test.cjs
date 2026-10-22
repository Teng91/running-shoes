const { runContext, test, assert, fs, vm, extract, transportContext } = require('./helpers.cjs');

test('SPEC-019 run retry clears only its own error and keeps aggregate failures visible', async () => {
  const nodes = { 'run-load-error': { hidden: true }, 'data-load-error': { hidden: false } };
  let fail = true;
  const context = runContext({ document: { getElementById: id => nodes[id] }, console: { error() {} },
    selectedRunMonth: () => '2026-10', renderedPanels: new Map(), renderActivePanel() {},
    fetchRunPage: async () => { if (fail) throw new Error('synthetic'); return { rows: [], hasMore: false }; },
    apiGet: async () => ({ total_km: 0 }),
  });
  vm.runInContext('let runListRequestId = 0, runLoadRetryOptions;\n' + extract('loadRunsForSelectedMonth'), context);
  await context.loadRunsForSelectedMonth(); assert.equal(nodes['run-load-error'].hidden, false);
  fail = false; await context.loadRunsForSelectedMonth();
  assert.equal(nodes['run-load-error'].hidden, true); assert.equal(nodes['data-load-error'].hidden, false);
});

test('SPEC-019 storage invalidation never deletes the replacement tab credentials', () => {
  const listeners = {}, storage = { getItem: key => key === 'token' ? 'A' : 'alice' };
  const cleared = [], notices = [];
  const context = vm.createContext({ window: { addEventListener: (name, listener) => listeners[name] = listener },
    localStorage: storage, authToken: 'A', currentUser: 'alice',
    clearAuth: options => cleared.push(options), showLoginView() {}, showAuthError: text => notices.push(text),
  });
  vm.runInContext(extract('initializeAuthSync'), context); context.initializeAuthSync();
  listeners.storage({ storageArea: storage, key: 'theme' }); assert.equal(cleared.length, 0);
  for (const key of ['token', 'username', null]) listeners.storage({ storageArea: storage, key });
  assert.equal(cleared.length, 3); assert.ok(cleared.every(options => options.persist === false));
  assert.equal(notices.length, 3);
});

test('SPEC-019 JSON deadline bounds both stalled headers and stalled response bodies', async () => {
  for (const phase of ['headers', 'body']) {
    const context = transportContext(); let calls = 0;
    context.fetch = async () => { calls++; return phase === 'headers' ? new Promise(() => {}) : {
      ok: true, status: 200, json: () => new Promise(() => {}),
    }; };
    await assert.rejects(context.apiGet('/test', { timeoutMs: 5 }), { name: 'TimeoutError' });
    assert.equal(calls, 2, 'GET makes at most one retry');
    assert.equal(vm.runInContext('activeHttpRequests.size', context), 0);
  }
});

test('SPEC-019 transient GETs retry once but writes and 401 never retry', async () => {
  const context = transportContext(); let calls = 0;
  context.fetch = async () => {
    calls++; return calls === 1 ? { ok: false, status: 503, json: async () => ({}) }
      : { ok: true, status: 200, json: async () => ({ recovered: true }) };
  };
  assert.equal((await context.apiGet('/test')).recovered, true); assert.equal(calls, 2);
  calls = 0;
  context.fetch = async () => { calls++; throw new TypeError('synthetic offline'); };
  await assert.rejects(context.apiPost('/runs', {}, { idempotencyKey: 'operation-0000001' }), /offline/);
  assert.equal(calls, 1);
  calls = 0; context.fetch = async () => { calls++; return { status: 401 }; };
  await assert.rejects(context.apiGet('/test'), /登入已過期/); assert.equal(calls, 1);
});

test('SPEC-019 request cancellation does not retry and SSE remains outside the JSON deadline', async () => {
  const context = transportContext(); const controller = new AbortController(); let calls = 0;
  context.fetch = async () => { calls++; return new Promise(() => {}); };
  const pending = context.apiGet('/test', { signal: controller.signal }); controller.abort();
  await assert.rejects(pending, { name: 'AbortError' }); assert.equal(calls, 1);
  context.fetch = async () => ({ ok: true, status: 200 });
  await context.authenticatedFetch('/agent/chat/stream');
  assert.equal(vm.runInContext('activeHttpRequests.size', context), 0);
});

test('SPEC-019 creation retries retain a key, but changed input or success starts a new operation', async () => {
  const nodes = { 'run-date': { value: '2026-01-05' }, 'run-km': { value: '5' }, 'run-shoe': { value: '1' },
    'run-error': {}, 'run-month': {}, 'add-run-btn': {} };
  const keys = []; let fail = true;
  const context = runContext({ document: { getElementById: id => nodes[id] },
    localDateISO: () => '2026-10-22', refreshDateLimits() {},
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true, loadData: async () => {},
    apiPost: async (_, body, options) => { keys.push(options.idempotencyKey); if (fail) throw new Error('lost response'); },
  });
  vm.runInContext(extract('addRun'), context);
  await context.addRun(); await context.addRun(); assert.equal(keys[0], keys[1]);
  nodes['run-km'].value = '6'; await context.addRun(); assert.notEqual(keys[1], keys[2]);
  fail = false; await context.addRun(); assert.equal(keys[2], keys[3]);
  nodes['run-km'].value = '6'; await context.addRun(); assert.notEqual(keys[3], keys[4]);
});

test('SPEC-019 annual charts use one summary request rather than downloading individual runs', async () => {
  const nodes = { 'stacked-year-select': { value: '2026' }, 'chart-shoe-stacked': {} }; const calls = [];
  const context = runContext({ document: { getElementById: id => nodes[id], querySelector: () => ({ dataset: { panel: 'monthly' } }) },
    apiGet: async url => { calls.push(url); return { shoes: [{ shoe_id: 99, monthly_km: [5, ...Array(11).fill(0)] }] }; },
    chartInstances: {}, shoes: [], retiredShoes: [], yearlyRunsCache: new Map(), renderedPanels: new Map(),
    stackedRunsRequestId: 0, getThemeColor: () => '#000', brandColor: () => '#000',
    Chart: function(_, config) { this.config = config; this.destroy = () => {}; },
  });
  vm.runInContext(extract('renderShoeStackedChart'), context);
  await context.renderShoeStackedChart(); await context.renderShoeStackedChart();
  assert.deepEqual(calls, ['/runs/year-summary?year=2026']);
  assert.match(context.chartInstances.shoeStacked.config.data.datasets[0].label, /已刪除/);
});
