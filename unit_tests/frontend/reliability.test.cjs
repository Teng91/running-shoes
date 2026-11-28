const nodeVm = require('node:vm');
const { runContext, test, assert, fs, vm, extract, transportContext, readText, scriptSource } = require('./helpers.cjs');

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
    startAuthSession: () => false,
  });
  vm.runInContext(['readStoredValue', 'isLocalStorageEvent', 'signOutWithNotice', 'adoptRenewedToken', 'initializeAuthSync']
    .map(extract).join('\n'), context);
  context.initializeAuthSync();
  listeners.storage({ storageArea: storage, key: 'theme' }); assert.equal(cleared.length, 0);
  for (const key of ['token', 'username', null]) listeners.storage({ storageArea: storage, key });
  assert.equal(cleared.length, 3); assert.ok(cleared.every(options => options.persist === false));
  assert.equal(notices.length, 3);
});

function syntheticJwt(claims) {
  const part = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${part({ alg: 'HS256' })}.${part(claims)}.signature`;
}

// The real app-session.js with app-auth.js's renewal functions and an in-memory localStorage.
function sessionContext(token, extra = {}) {
  const stored = new Map([['token', token], ['username', 'alice']]);
  const listeners = {}, notices = [];
  const storage = { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value),
    removeItem: key => stored.delete(key) };
  const context = nodeVm.createContext({
    localStorage: storage, atob, TextDecoder, Uint8Array, DOMException,
    window: { addEventListener: (name, listener) => { listeners[name] = listener; } },
    document: { visibilityState: 'visible' }, clearAuth() {}, showLoginView() {},
    showAuthError: text => notices.push(text), ...extra,
  });
  nodeVm.runInContext(['readStoredValue', 'writeStoredValue', 'removeStoredValue', 'isLocalStorageEvent']
    .map(extract).join('\n'), context);
  nodeVm.runInContext(readText('frontend/app-session.js'), context, { filename: 'app-session.js' });
  nodeVm.runInContext(['signOutWithNotice', 'adoptRenewedToken', 'initializeAuthSync', 'renewSessionIfDue']
    .map(extract).join('\n') + `
    const SESSION_RENEW_REMAINING_MS = 3.5 * 24 * 60 * 60 * 1000;
    const SESSION_RENEW_INTERVAL_MS = 60 * 60 * 1000;
    let lastSessionRenewal = -Infinity;`, context);
  return { context, stored, storage, listeners, notices };
}

test('SPEC-143 a renewed token of the same account continues the session in this and other tabs', async () => {
  const day = 24 * 60 * 60 * 1000, now = Date.UTC(2026, 10, 28);
  const first = syntheticJwt({ sub: 'alice', aid: 'acct-1', exp: (now + 2 * day) / 1000 });
  const renewed = syntheticJwt({ sub: 'alice', aid: 'acct-1', exp: (now + 7 * day) / 1000 });
  const requests = [];
  const { context, stored, storage, listeners, notices } = sessionContext(first, {
    apiPost: async (url, body) => { requests.push([url, body]); return { access_token: renewed }; },
  });
  const before = context.captureAuthSession();
  assert.equal(before.expiresAt, now + 2 * day);
  assert.equal(await context.renewSessionIfDue(now), true);
  assert.equal(JSON.stringify(requests), '[["/auth/refresh",{}]]');
  assert.equal(stored.get('token'), renewed);
  assert.equal(context.isCurrentAuthSession(before), true, 'work captured before the renewal still owns the screen');
  assert.equal(await context.renewSessionIfDue(now + 1000), false, 'a fresh token is not renewed again');
  assert.equal(requests.length, 1);

  // Another tab renewed the same account: adopt its token without signing out.
  context.initializeAuthSync();
  const later = syntheticJwt({ sub: 'alice', aid: 'acct-1', exp: (now + 8 * day) / 1000 });
  listeners.storage({ storageArea: storage, key: 'token', newValue: later });
  assert.equal(nodeVm.runInContext('authToken', context), later);
  assert.equal(notices.length, 0);
  // Another account under the same name (deleted and registered again) is never adopted.
  listeners.storage({ storageArea: storage, key: 'token',
    newValue: syntheticJwt({ sub: 'alice', aid: 'acct-2', exp: (now + 9 * day) / 1000 }) });
  assert.equal(notices.length, 1);
});

test('SPEC-143 renewal waits until half the token has passed and retries at most hourly', async () => {
  const day = 24 * 60 * 60 * 1000, now = Date.UTC(2026, 10, 28);
  let calls = 0;
  const fresh = syntheticJwt({ sub: 'alice', aid: 'acct-1', exp: (now + 6 * day) / 1000 });
  const { context } = sessionContext(fresh, { apiPost: async () => { calls++; throw new TypeError('offline'); } });
  assert.equal(await context.renewSessionIfDue(now), false);
  assert.equal(calls, 0, 'six days left: no request');
  assert.equal(await context.renewSessionIfDue(now + 3 * day), false);
  assert.equal(calls, 1, 'past half: one attempt, which failed offline');
  assert.equal(await context.renewSessionIfDue(now + 3 * day + 1000), false);
  assert.equal(calls, 1, 'no second attempt within the hour');
  assert.equal(await context.renewSessionIfDue(now + 3 * day + 60 * 60 * 1000), false);
  assert.equal(calls, 2);
  const other = sessionContext(syntheticJwt({ sub: 'bob', aid: 'acct-9', exp: (now + day) / 1000 }), {
    apiPost: async () => ({ access_token: syntheticJwt({ sub: 'bob', aid: 'acct-10', exp: (now + 7 * day) / 1000 }) }),
  });
  assert.equal(await other.context.renewSessionIfDue(now), false, 'a token of another account is refused');
  assert.equal(other.stored.get('token').length > 0, true);
});

test('SPEC-087 a browser that blocks site storage still starts and keeps the login in memory', () => {
  const context = nodeVm.createContext({ document: { getElementById: () => null, querySelectorAll: () => [] }, window: new EventTarget() });
  nodeVm.runInContext(`Object.defineProperty(globalThis, 'localStorage', {
    get() { throw new Error('SecurityError: site data is blocked'); } })`, context);
  for (const file of ['app-lifecycle.js', 'app-state.js', 'app-session.js', 'app-auth.js']) {
    nodeVm.runInContext(readText('frontend/' + file), context, { filename: file });
  }
  context.resetFeatureLifecycles = () => {};
  const state = names => nodeVm.runInContext(`JSON.stringify([${names}])`, context);
  assert.equal(state('authToken, currentUser, themePreference'), '[null,null,"system"]');
  context.setAuth('synthetic-token', 'synthetic-user');
  assert.equal(state('authToken, currentUser'), '["synthetic-token","synthetic-user"]', 'the login lives in memory');
  context.clearAuth();
  assert.equal(nodeVm.runInContext('authToken', context), null);
  for (const line of scriptSource.split('\n')) {
    if (line.includes('localStorage') && !line.trim().startsWith('//')) {
      assert.match(line, /try \{/, `every localStorage access is guarded: ${line.trim()}`);
    }
  }
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
  const nodes = { 'run-date': { value: '2026-01-05' }, 'run-km': { value: '5' }, 'run-duration': { value: '' }, 'run-shoe': { value: '1' },
    'run-activity': { value: 'road' }, 'run-error': {}, 'run-month': {}, 'add-run-btn': {} };
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
  const nodes = { 'year-select': { value: '2026' }, 'chart-shoe-stacked': {} }; const calls = [];
  const context = runContext({ document: { getElementById: id => nodes[id], querySelector: () => ({ dataset: { panel: 'monthly' } }) },
    apiGet: async url => { calls.push(url); return { shoes: [{ shoe_id: 99, monthly_km: [5, ...Array(11).fill(0)] }] }; },
    chartInstances: {}, shoes: [], retiredShoes: [], yearlyRunsCache: new Map(), renderedPanels: new Map(),
    shoeStackedRequestId: 0, getThemeColor: () => '#000', brandColor: () => '#000', shoeColor: () => '#000',
    Chart: function(_, config) { this.config = config; this.destroy = () => {}; },
  });
  vm.runInContext(extract('renderShoeStackedChart'), context);
  await context.renderShoeStackedChart(); await context.renderShoeStackedChart();
  assert.deepEqual(calls, ['/runs/year-summary?year=2026']);
  assert.match(context.chartInstances.shoeStacked.config.data.datasets[0].label, /已刪除/);
});
