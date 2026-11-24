const { test, assert, transportContext, vm, fs, path, featureRegistrations } = require('./helpers.cjs');
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
async function bindRestoreController(context) {
  const { createAccountRestoreController } = await import('../../frontend/runtime/account-restore-controller.mjs');
  context.resourceStore ||= { hasErrors: () => false };
  context.injectedRestore = createAccountRestoreController({
    session: { capture: context.captureAuthSession, current: context.isCurrentAuthSession },
    newKey: context.newOperationKey || (() => 'synthetic-restore-operation'),
    transport: { preview: (raw, mode) => context.jsonRequest('/account-restore/preview?mode=' + mode, { body: raw }),
      apply: (token, operationId) => context.apiPost('/account-restore/apply', { token }, { idempotencyKey: operationId }),
      refresh: () => context.refreshAccountRestoreData(),
      discard: token => context.apiDelete?.('/account-restore/preview/' + token) || Promise.resolve() },
  });
  vm.runInContext('accountRestore = injectedRestore;', context);
  return context.injectedRestore;
}
function memoryStore() {
  const rows = new Map(); let tail = Promise.resolve(), fail = false;
  function write(fn) {
    const next = tail.then(() => { if (fail) throw Error('quota'); return fn(); });
    tail = next.catch(() => {}); return next;
  }
  const serial = key => JSON.stringify(key);
  return {
    rows, setFailure: value => { fail = value; },
    async list(account, kind) { await tail; return structuredClone([...rows.values()].filter(row => row.key[0] === account && (!kind || row.key[1] === kind))); },
    update(key, change) { return write(() => { const value = change(structuredClone(rows.get(serial(key)))); if (value) rows.set(serial(key), structuredClone(value)); else rows.delete(serial(key)); return structuredClone(value); }); },
    enqueue(key, change, draftId) { return write(() => {
      const value = change(structuredClone(rows.get(serial(key))));
      const draftKey = serial([key[0], 'drafts', 'forms']), draft = structuredClone(rows.get(draftKey));
      if (draftId) {
        const record = draft || { key: [key[0], 'drafts', 'forms'], value: { forms: {} } };
        record.value.consumedRunDraftId = draftId;
        if (record.value.runDraftId === draftId) delete record.value.forms.run;
        rows.set(draftKey, record);
      }
      rows.set(serial(key), structuredClone(value)); return structuredClone(value);
    }); },
    move(key, change) { return write(() => { const value = change(structuredClone(rows.get(serial(key)))); rows.set(serial(value.key), structuredClone(value)); rows.delete(serial(key)); return value; }); },
    clear(account, validate) { return write(() => { const own = [...rows.values()].filter(row => row.key[0] === account); validate?.(own); own.forEach(row => rows.delete(serial(row.key))); }); },
  };
}
async function setup(storage = memoryStore(), send = async () => {}) {
  const { createWorkspaceController } = await import('../../frontend/runtime/workspace-controller.mjs');
  let session = { valid: true }, now = 1000, next = 0;
  return { storage, setTime: value => { now = value; }, session: () => session,
    switch: () => { session.valid = false; session = { valid: true }; },
    create: () => createWorkspaceController({ storage, send, session: { capture: () => session, current: value => value.valid },
      clock: () => now, newKey: () => 'operation-synthetic-' + (++next) }),
  };
}

test('SPEC-027 drafts and cached resources stay within their account', async () => {
  const fixture = await setup(), controller = fixture.create();
  await controller.attach('A');
  await controller.save('drafts', 'forms', { forms: { run: { km: '180' } }, editors: { 'run:1': { base: { id: 1, version: 3 } } } });
  await controller.save('resource', 'shoes', [{ id: 7 }]);
  controller.detach(); fixture.switch(); await controller.attach('B');
  assert.deepEqual(await controller.read('drafts'), []);
  await controller.save('drafts', 'forms', { km: '5' });
  controller.detach(); fixture.switch();
  const reopened = fixture.create(); const saved = await reopened.attach('A');
  assert.equal(saved.find(row => row.key[1] === 'drafts').value.editors['run:1'].base.version, 3);
  assert.equal(saved.find(row => row.key[1] === 'resource').value[0].id, 7);
  assert.doesNotMatch(JSON.stringify([...fixture.storage.rows.values()]), /token|session/);
});

test('SPEC-027 durable queue survives lost responses and competing consumers', async () => {
  const committed = new Set(); let calls = 0, lose = true;
  const fixture = await setup(undefined, async operation => {
    calls++; committed.add(operation.operation_id);
    if (lose) { lose = false; throw Error('lost response'); }
  });
  const first = fixture.create(); await first.attach('A');
  await first.enqueue({ date: '2026-01-01', km: 5, shoe_id: 1 }, 'durable-operation-0001');
  await first.flush(); assert.equal((await first.read('queue')).length, 1);
  first.detach();
  const reopened = fixture.create(), otherTab = fixture.create();
  await reopened.attach('A'); await otherTab.attach('A');
  await Promise.all([reopened.flush(), otherTab.flush()]);
  assert.equal(calls, 2); assert.equal(committed.size, 1); assert.deepEqual(await reopened.read('queue'), []);
});

test('SPEC-027 leases prevent parallel consumers and recover after a crash', async () => {
  const gate = deferred(); let sends = 0;
  const fixture = await setup(undefined, async () => { sends++; await gate.promise; });
  const first = fixture.create(), second = fixture.create(); await first.attach('A'); await second.attach('A');
  await first.enqueue({ km: 5, shoe_id: 1 }, 'durable-operation-0001');
  const syncing = first.flush(); await new Promise(resolve => setImmediate(resolve));
  await second.flush(); assert.equal(sends, 1);
  await assert.rejects(second.remove('durable-operation-0001'), /正在同步/);
  await assert.rejects(second.clear(), /正在同步/);
  gate.resolve(); await syncing;
  await first.enqueue({ km: 8, shoe_id: 1 }, 'durable-operation-0002');
  await fixture.storage.update(['A', 'queue', 'durable-operation-0002'], row => ({ ...row, lease: 'dead-tab', leaseUntil: 121000 }));
  await second.flush(); assert.equal(sends, 1);
  fixture.setTime(121001); await second.flush(); assert.equal(sends, 2);
});

test('SPEC-027 missing shoes block until explicit reassignment with a fresh identity', async () => {
  const sent = []; let missing = true;
  const fixture = await setup(undefined, async operation => { sent.push(operation); if (missing) throw Object.assign(Error('Shoe deleted'), { status: 404 }); });
  const controller = fixture.create(); await controller.attach('A');
  await controller.enqueue({ date: '2026-01-01', km: 5, shoe_id: 1 }, 'durable-operation-0001');
  await controller.flush(); await controller.flush(); assert.equal(sent.length, 1);
  assert.equal((await controller.read('queue'))[0].status, 'blocked');
  await controller.resolve('durable-operation-0001', 2); missing = false;
  await controller.flush(); assert.equal(sent[1].payload.shoe_id, 2); assert.equal(sent[1].payload.km, 5);
  assert.notEqual(sent[0].operation_id, sent[1].operation_id);
});

test('SPEC-027 expired auth pauses without dropping or crossing account queues', async () => {
  const sent = [];
  const fixture = await setup(undefined, async operation => { sent.push(operation); throw Object.assign(Error('expired'), { status: 401 }); });
  const controller = fixture.create(); await controller.attach('A'); await controller.enqueue({ km: 5 }, 'durable-operation-0001');
  await controller.flush(); assert.equal((await controller.read('queue'))[0].status, 'pending');
  fixture.switch(); controller.detach(); await controller.attach('B'); await controller.flush();
  assert.equal(sent.length, 1); assert.deepEqual(await controller.read('queue'), []);
  fixture.switch(); controller.detach(); await controller.attach('A'); assert.equal((await controller.read('queue')).length, 1);
});

test('SPEC-027 failed persistence cannot acknowledge an offline submission', async () => {
  const fixture = await setup(), controller = fixture.create(); await controller.attach('A');
  fixture.storage.setFailure(true);
  await assert.rejects(controller.enqueue({ km: 5 }), /quota/);
  await assert.rejects(controller.save('drafts', 'forms', { km: '180' }), /quota/);
  fixture.storage.setFailure(false); assert.deepEqual(await controller.read('queue'), []);
});

test('SPEC-027 a stale queued read cannot dispatch under the next account', async () => {
  let calls = 0; const fixture = await setup(undefined, async () => { calls++; });
  const controller = fixture.create(); await controller.attach('A'); await controller.enqueue({ km: 5 });
  const syncing = controller.flush(); fixture.switch(); controller.detach(); await controller.attach('B'); await syncing;
  assert.equal(calls, 0); assert.equal((await fixture.storage.list('A', 'queue')).length, 1);
});

test('SPEC-027 explicit operation keys keep identical intentional runs distinct', async () => {
  const sent = [];
  const fixture = await setup(undefined, async value => sent.push(value));
  const controller = fixture.create(); await controller.attach('A');
  await controller.enqueue({ km: 5 }, 'durable-operation-0001'); await controller.enqueue({ km: 5 }, 'durable-operation-0002');
  await controller.flush(); assert.equal(sent.length, 2); assert.notEqual(sent[0].operation_id, sent[1].operation_id);
});

module.exports = { memoryStore };

test('SPEC-027 transport preserves distinct supplied identities after an ambiguous response', async () => {
  const context = transportContext(), keys = []; let fail = true;
  context.fetch = async (_, options) => {
    keys.push(options.headers['Idempotency-Key']);
    if (fail) throw Error('lost response');
    return { ok: true, json: async () => ({ ok: true }) };
  };
  await assert.rejects(context.apiPost('/runs', { km: 5 }, { idempotencyKey: 'operation-distinct-1' }));
  fail = false;
  await context.apiPost('/runs', { km: 5 }, { idempotencyKey: 'operation-distinct-2' });
  await context.apiPost('/runs', { km: 5 }, { idempotencyKey: 'operation-distinct-1' });
  assert.deepEqual(keys, ['operation-distinct-1', 'operation-distinct-2', 'operation-distinct-1']);
});


test('SPEC-027 queue acceptance consumes only its draft atomically before a crash', async () => {
  const fixture = await setup(), controller = fixture.create(); await controller.attach('A');
  await controller.save('drafts', 'forms', { runDraftId: 'draft-1', forms: { run: { km: '5' }, monthly: { km: '180' } } });
  await controller.enqueue({ km: 5 }, 'durable-operation-0001', 'draft-1');
  await controller.save('drafts', 'forms', { runDraftId: 'draft-1', forms: { run: { km: '5' }, monthly: { km: '180' } } }); // late pagehide snapshot
  const reopened = fixture.create(), records = await reopened.attach('A');
  assert.equal(records.find(row => row.key[1] === 'drafts').value.forms.run, undefined);
  assert.equal(records.find(row => row.key[1] === 'drafts').value.forms.monthly.km, '180');
  await controller.save('drafts', 'forms', { runDraftId: 'draft-2', forms: { run: { km: '5' } } });
  await controller.enqueue({ km: 5 }, 'durable-operation-0001', 'draft-1');
  assert.equal((await controller.read('drafts'))[0].value.forms.run.km, '5', 'new identical input is a new draft');
});


test('SPEC-027 restore windows reject repreview during apply and stale completion', async () => {
  const gate = deferred(); let loads = 0;
  const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= { disabled: false, value: '', textContent: '' } });
  const context = vm.createContext({ document: { getElementById: id => elements[id] },
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true,
    registerFeatureReset() {}, apiPost: () => gate.promise,
    loadData: async () => { loads++; }, loadWorkspaceHistory() {},
  });
  vm.runInContext(fs.readFileSync('frontend/app-account-restore.js', 'utf8'), context);
  await bindRestoreController(context);
  vm.runInContext("accountRestore.state.preview = { token: 'first' }; accountRestore.state.operationId = 'restore-operation-first';", context);
  const pending = context.applyAccountRestore();
  await context.previewAccountRestore();
  assert.equal(vm.runInContext('accountRestore.state.revision', context), 0, 'pending apply owns its preview');
  context.resetAccountRestore();
  vm.runInContext("accountRestore.state.preview = { token: 'second' };", context);
  elements['restore-preview'].textContent = 'new preview';
  gate.resolve({ ok: true }); await pending;
  assert.equal(elements['restore-preview'].textContent, 'new preview');
  assert.equal(vm.runInContext('accountRestore.state.preview.token', context), 'second');
  assert.equal(vm.runInContext('accountRestore.state.pending', context), false);
  assert.equal(loads, 1, 'committed old operation still refreshes server data');
});

function workspaceSyncContext() {
  let session = {}, reset, flushes = 0, loads = 0;
  const makeElement = () => ({ disabled: false, textContent: '', children: [], classList: { remove() {} },
    append(child) { this.children.push(child); }, replaceChildren() { this.children = []; }, setAttribute() {} });
  const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= makeElement() });
  const controller = { account: 'synthetic-A', flush: async () => { flushes++; return { synced: 0 }; }, read: async () => [] };
  const context = vm.createContext({ document: { getElementById: id => elements[id], createElement: makeElement }, navigator: { onLine: true },
    authToken: 'synthetic', captureAuthSession: () => session, isCurrentAuthSession: value => value === session,
    registerFeatureReset: (_, callback) => { reset = callback; }, loadData: async () => { loads++; },
    allRunShoes: () => [], esc: value => value, shoeLabel: value => value,
  });
  vm.runInContext(fs.readFileSync('frontend/app-workspace.js', 'utf8'), context);
  context.controller = controller;
  vm.runInContext('localWorkspace.controller = controller;', context);
  return { context, elements, controller, flushes: () => flushes, loads: () => loads,
    switchAccount() {
      controller.detach = () => {}; controller.account = null; context.authToken = null; session = {}; reset();
      context.authToken = 'synthetic'; controller.account = 'synthetic-B';
    },
  };
}

test('SPEC-028 manual sync explains empty offline and unavailable states', async () => {
  const fixture = workspaceSyncContext(), { context, elements, controller } = fixture;
  const feedback = elements['workspace-sync-status'];
  await context.syncWorkspace({ manual: true });
  assert.match(feedback.textContent, /沒有待送跑步/);
  assert.equal(fixture.flushes(), 1);
  context.navigator.onLine = false;
  await context.syncWorkspace({ manual: true });
  assert.match(feedback.textContent, /目前離線/);
  assert.equal(fixture.flushes(), 1);
  context.navigator.onLine = true; controller.account = null;
  await context.syncWorkspace({ manual: true });
  assert.match(feedback.textContent, /尚未就緒/);
  vm.runInContext("localWorkspace.error = '本機儲存不可用';", context);
  await context.syncWorkspace({ manual: true });
  assert.match(feedback.textContent, /本機儲存不可用/);
  context.authToken = null;
  await context.syncWorkspace({ manual: true });
  assert.match(feedback.textContent, /請先登入/);
  assert.equal(fixture.flushes(), 1);
});

test('SPEC-028 sync shares pending work and reports uploaded runs', async () => {
  const fixture = workspaceSyncContext(), { context, elements, controller } = fixture;
  const gate = deferred(); let calls = 0;
  controller.flush = () => { calls++; return gate.promise; };
  const automatic = context.syncWorkspace();
  const manual = context.syncWorkspace({ manual: true });
  assert.equal(elements['workspace-sync'].disabled, true);
  assert.match(elements['workspace-sync-status'].textContent, /正在處理待送跑步並更新雲端資料/);
  assert.equal(calls, 1);
  gate.resolve({ synced: 2 });
  await Promise.all([automatic, manual]);
  assert.match(elements['workspace-sync-status'].textContent, /已同步 2 筆.*沒有待送跑步/);
  assert.equal(elements['workspace-sync'].disabled, false);
  assert.equal(fixture.loads(), 1);
});

test('SPEC-028 sync reports blocked pending and storage failures', async () => {
  const { context, elements, controller } = workspaceSyncContext();
  controller.flush = async () => ({ synced: 1 });
  controller.read = async () => [
    { status: 'blocked', operation: { operation_id: 'blocked-id', payload: { date: '2026-10-20', km: 1 } } },
    { status: 'pending', operation: { operation_id: 'pending-id', payload: { date: '2026-10-21', km: 2 } } },
  ];
  await context.syncWorkspace({ manual: true });
  assert.match(elements['workspace-sync-status'].textContent, /已同步 1 筆.*仍有 2 筆.*1 筆需要處理.*等待重試/);
  context.loadData = async () => { throw Error('refresh failed'); };
  await context.syncWorkspace({ manual: true });
  assert.match(elements['workspace-sync-status'].textContent, /紀錄已送出，但畫面更新失敗/);
  controller.flush = async () => { throw Error('storage unavailable'); };
  await context.syncWorkspace({ manual: true });
  assert.match(elements['workspace-sync-status'].textContent, /同步未完成.*storage unavailable/);
  assert.equal(elements['workspace-sync'].disabled, false);
  controller.flush = async () => ({ synced: 0 });
  controller.read = async () => { throw Error('read failed'); };
  await context.syncWorkspace({ manual: true });
  assert.match(elements['workspace-sync-status'].textContent, /同步未完成.*read failed/);
});

test('SPEC-028 stale sync cannot change the next account feedback', async () => {
  for (const reject of [false, true]) {
    const fixture = workspaceSyncContext(), { context, elements, controller } = fixture;
    const finishes = [];
    controller.flush = () => new Promise((resolve, fail) => {
      finishes.push({ resolve, reject: fail });
    });
    const pending = context.syncWorkspace({ manual: true });
    fixture.switchAccount();
    const newAccount = context.syncWorkspace({ manual: true });
    elements['workspace-sync-status'].textContent = 'new account syncing';
    if (reject) finishes[0].reject(Error('old failure'));
    else finishes[0].resolve({ synced: 1 });
    await pending;
    assert.equal(elements['workspace-sync-status'].textContent, 'new account syncing');
    assert.equal(elements['workspace-sync'].disabled, true);
    assert.equal(fixture.loads(), 0);
    finishes[1].resolve({ synced: 0 }); await newAccount;
    assert.match(elements['workspace-sync-status'].textContent, /沒有待送跑步/);
    assert.equal(elements['workspace-sync'].disabled, false);
  }
});

test('SPEC-028 workspace guidance distinguishes server backup and local data', () => {
  const modal = fs.readFileSync('frontend/templates/workspace-modal.html', 'utf8');
  assert.match(modal, /data-click="sync-workspace"/);
  assert.match(modal, /id="workspace-sync-status" role="status" aria-live="polite"/);
  assert.match(modal, /不會覆寫整個資料庫/);
  assert.match(modal, /不含密碼、本機草稿或待同步跑步/);
  assert.match(modal, /尚未同步的跑步會遺失/);
  assert.match(fs.readFileSync('README.md', 'utf8'), /\]\(docs\/user-guide.md\)/);
  const guide = fs.readFileSync('docs/user-guide.md', 'utf8');
  assert.match(guide, /確認每個有離線紀錄的裝置都已完成同步/);
  assert.match(guide, /已合併後又刪除的跑步/);
});

test('SPEC-035 sync controls name the action for the current connection and queue state', async () => {
  const fixture = workspaceSyncContext(), { context, elements, controller } = fixture;
  await context.renderWorkspaceQueue();
  assert.equal(elements['workspace-sync'].textContent, '更新雲端資料');
  assert.equal(elements['workspace-sync'].disabled, false);
  assert.match(elements['workspace-queue'].children[0].textContent, /新增成功的紀錄會直接存到雲端/);
  controller.read = async () => [{ operation: { payload: { date: '2026-10-25', km: 5 } }, status: 'pending' }];
  await context.renderWorkspaceQueue();
  assert.equal(elements['workspace-sync'].textContent, '同步待送跑步（1）');
  assert.match(elements['workspace-status'].textContent, /只存在這台裝置，尚未送到雲端/);
  context.navigator.onLine = false;
  await context.renderWorkspaceQueue();
  assert.equal(elements['workspace-sync'].textContent, '等待網路連線');
  assert.equal(elements['workspace-sync'].disabled, true);
  assert.match(elements['workspace-status'].textContent, /跑步留在這台裝置，等待連線後送到雲端/);
});

test('SPEC-035 workspace hides detailed offline caveats behind a disclosure', () => {
  const modal = fs.readFileSync('frontend/templates/workspace-modal.html', 'utf8');
  assert.match(modal, /<summary>離線時如何記錄<\/summary>/);
  assert.match(modal, /id="workspace-sync"[^>]*>更新雲端資料<\/button>/);
  assert.match(modal, /沒有待送出的跑步時|清單為空時可用它重新載入雲端資料/);
  assert.equal((modal.match(/<details class="workspace-section">/g) || []).length, 7, 'SPEC-075 account deletion, SPEC-080 password change and SPEC-088 logging out everywhere');
  assert.doesNotMatch(modal, /<details class="workspace-section" open/);
  for (const label of ['未完成的編輯草稿', '備份／匯入帳號資料', '異動紀錄與誤刪復原', '清除此裝置的本機資料', '登出所有裝置', '刪除帳號']) {
    assert.match(modal, new RegExp(label));
  }
});

test('SPEC-029 import modes own their previews and confirmation', async () => {
  const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= { disabled: false, value: '', textContent: '', files: [] } });
  let accepted = false, posts = 0, requested, resolvePreview;
  const context = vm.createContext({ document: { getElementById: id => elements[id] },
    window: { location: { origin: 'http://localhost:8000' } }, currentUser: 'local-user',
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true, registerFeatureReset() {},
    authHeaders: () => ({}), newOperationKey: () => 'synthetic-import-operation',
    jsonRequest: (url) => { requested = url; return new Promise(resolve => { resolvePreview = resolve; }); },
    apiPost: async () => { posts++; }, loadData: async () => {}, loadWorkspaceHistory() {},
    confirm: message => { assert.match(message, /localhost:8000.*local-user/); return accepted; },
  });
  vm.runInContext(fs.readFileSync('frontend/app-account-restore.js', 'utf8'), context);
  await bindRestoreController(context);
  elements['restore-mode'].value = 'update';
  elements['restore-file'].files = [{ size: 4, text: async () => '{}' }];
  const reading = context.previewAccountRestore();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(requested, /\?mode=update$/);
  resolvePreview({ token: 'synthetic', summary: { mode: 'update', source_username: 'cloud-user', exported_at: '2026-10-24',
    new_shoes: 0, new_runs: 0, updated_shoes: 1, updated_runs: 2, updated_months: 1, updated_reports: 1, updated_goal: true,
    policy: '更新', monthly_records: 1, reports: 1, history_records: 0, new_import_summaries: 0, skipped_import_summaries: 0 } });
  await reading;
  assert.match(elements['restore-preview'].textContent, /cloud-user.*localhost:8000.*local-user.*更新 1 雙鞋、2 筆跑步/);
  await context.applyAccountRestore(); assert.equal(posts, 0, 'cancel leaves data unchanged');
  accepted = true; await context.applyAccountRestore();
  assert.equal(posts, 1);
  assert.match(elements['restore-preview'].textContent, /同來源資料已更新/);
  assert.equal(elements['restore-mode'].disabled, false);
  const stale = context.previewAccountRestore(); await new Promise(resolve => setImmediate(resolve));
  context.resetAccountRestore(); resolvePreview({ token: 'old', summary: {} }); await stale;
  assert.equal(elements['restore-mode'].value, 'merge');
  assert.equal(elements['restore-apply'].disabled, true);
});

test('SPEC-029 workspace download reports results and ignores a replaced session', async () => {
  const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= { disabled: false, textContent: '' } });
  let session = {}, resets, downloads = 0;
  const context = vm.createContext({ document: { getElementById: id => elements[id], body: { appendChild() {} },
    createElement: () => ({ click() { downloads++; }, remove() {} }) },
    window: { URL: { createObjectURL: () => 'blob:synthetic', revokeObjectURL() {} } },
    API_BASE: '/api', authHeaders: () => ({}), localDateISO: () => '2026-10-24',
    captureAuthSession: () => session, isCurrentAuthSession: value => value === session,
    registerFeatureReset: (_, reset) => { resets = reset; },
    authenticatedFetch: async () => ({ ok: true, headers: { get: () => null } }), readAuthenticatedBody: async () => ({}),
  });
  vm.runInContext(fs.readFileSync('frontend/app-exports.js', 'utf8'), context);
  await context.exportAccountData(true);
  assert.equal(downloads, 1); assert.match(elements['workspace-export-status'].textContent, /查看下載項目/);
  context.authenticatedFetch = async () => { throw Error('offline'); };
  await context.exportAccountData(true);
  assert.match(elements['workspace-export-status'].textContent, /offline/);
  const gate = deferred(); context.authenticatedFetch = () => gate.promise;
  const stale = context.exportAccountData(true);
  assert.equal(elements['workspace-export'].disabled, true);
  session = {}; resets(); elements['workspace-export-status'].textContent = 'next account';
  gate.resolve({ ok: true, headers: { get: () => null } }); await stale;
  assert.equal(downloads, 1); assert.equal(elements['workspace-export-status'].textContent, 'next account');
  assert.equal(elements['workspace-export'].disabled, false);
});

test('SPEC-030 local clearing preserves replacement sessions and newer input', async () => {
  for (const switched of [false, true]) for (const failed of [false, true]) {
    let session = {}, complete, reject, persisted = 0, errors = 0, clears = 0;
    const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= { value: '', textContent: '' } });
    const controller = { clear: () => { clears++; return new Promise((resolve, fail) => { complete = resolve; reject = fail; }); } };
    const context = vm.createContext({ document: { getElementById: id => elements[id] },
      captureAuthSession: () => session, isCurrentAuthSession: value => value === session,
      registerFeatureReset() {}, confirm: () => true, controller,
    });
    vm.runInContext(fs.readFileSync('frontend/app-workspace.js', 'utf8'), context);
    vm.runInContext("localWorkspace.controller = controller; localWorkspace.editors = { old: { value: 'A' } };", context);
    context.prepareGoalForm = () => {};
    context.persistWorkspaceDrafts = () => { persisted++; };
    context.renderWorkspaceQueue = async () => {};
    context.workspaceStorageError = () => { errors++; };
    elements['run-km'].value = '5';
    const pending = context.clearLocalWorkspace();
    await context.clearLocalWorkspace(); assert.equal(clears, 1, 'duplicate clear stays locked');
    if (switched) session = {};
    elements['run-km'].value = switched ? '42' : '6';
    vm.runInContext("localWorkspace.editors.new = { value: 'new input' };", context);
    if (failed) reject(Error('old storage failure')); else complete();
    await pending;
    assert.equal(elements['run-km'].value, switched ? '42' : '6');
    assert.equal(vm.runInContext('localWorkspace.editors.new.value', context), 'new input');
    assert.equal(errors, failed && !switched ? 1 : 0);
    assert.equal(persisted, !failed && !switched ? 1 : 0);
  }
});

test('SPEC-030 restore controller isolates windows and releases stale previews', async () => {
  const { createAccountRestoreController } = await import('../../frontend/runtime/account-restore-controller.mjs');
  let session = {}, key = 0;
  const previews = [], applies = [], discarded = [];
  const controller = createAccountRestoreController({ session: { capture: () => session, current: value => value === session },
    newKey: () => 'restore-key-' + (++key), transport: {
      preview: () => { const gate = deferred(); previews.push(gate); return gate.promise; },
      apply: (token, operationId) => { const gate = deferred(); applies.push({ ...gate, token, operationId }); return gate.promise; },
      discard: async token => { discarded.push(token); },
    } });
  const old = controller.beginPreview(), oldRead = controller.preview(old, '{}', 'merge');
  const fresh = controller.beginPreview(), freshRead = controller.preview(fresh, '{}', 'update');
  previews[1].resolve({ token: 'fresh' }); await freshRead;
  previews[0].resolve({ token: 'old' }); assert.equal(await oldRead, null);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(discarded, ['old']); assert.equal(controller.state.preview.token, 'fresh');
  const applying = controller.beginApply(), applied = controller.apply(applying);
  assert.equal(controller.beginPreview(), null);
  controller.reset();
  const next = controller.beginPreview(), nextRead = controller.preview(next, '{}', 'merge');
  previews[2].resolve({ token: 'next' }); await nextRead;
  const nextApply = controller.beginApply(), nextApplied = controller.apply(nextApply);
  applies[0].resolve({ ok: true }); assert.equal(await applied, true);
  assert.equal(controller.finishApply(applying), false);
  assert.equal(controller.state.pending, true); assert.equal(controller.state.preview.token, 'next');
  assert.deepEqual(discarded, ['old'], 'closing does not delete a pending apply token');
  applies[1].resolve({ ok: true }); await nextApplied; controller.finishApply(nextApply);
  const stale = controller.beginPreview(), staleRead = controller.preview(stale, '{}', 'merge');
  session = {}; controller.reset(); previews[3].resolve({ token: 'account-A' }); await staleRead;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(controller.state.preview, null); assert.deepEqual(discarded, ['old']);
});


test('SPEC-032 committed import refresh retries only reads and isolates replaced windows', async () => {
  const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= { disabled: false, hidden: true, value: '', textContent: '' } });
  let posts = 0, reads = 0, failRead = true, failWrite = false;
  const keys = [];
  const session = {};
  const context = vm.createContext({ document: { getElementById: id => elements[id] }, registerFeatureReset() {},
    captureAuthSession: () => session, isCurrentAuthSession: value => value === session,
    jsonRequest: async () => ({ token: 'synthetic-preview', summary: { mode: 'merge' } }),
    apiPost: async (_, body, options) => { posts++; keys.push(options.idempotencyKey); if (failWrite) throw Error('lost response'); },
    loadData: async () => { reads++; }, loadWorkspaceHistory() {},
  });
  context.resourceStore = { ...context.resourceStore, getError: resource => failRead && resource === 'shoes' ? Error('read failed') : undefined };
  vm.runInContext(fs.readFileSync('frontend/app-account-restore.js', 'utf8'), context);
  const controller = await bindRestoreController(context);
  await controller.preview(controller.beginPreview(), '{}', 'merge');
  await context.applyAccountRestore();
  assert.equal(posts, 1); assert.equal(reads, 1);
  assert.match(elements['restore-preview'].textContent, /匯入已完成.*重新載入資料/);
  assert.equal(elements['restore-apply'].disabled, true);
  assert.equal(elements['restore-refresh'].hidden, false);
  assert.equal(controller.state.preview, null);
  await context.applyAccountRestore(); assert.equal(posts, 1, 'committed import cannot be resent');
  failRead = false; await context.refreshAccountRestoreView();
  assert.equal(posts, 1); assert.equal(reads, 2);
  assert.equal(elements['restore-refresh'].hidden, true);
  assert.match(elements['restore-preview'].textContent, /合併還原完成/);
  await context.refreshAccountRestoreView(); assert.equal(reads, 2);
  await controller.preview(controller.beginPreview(), '{}', 'merge');
  failWrite = true; await context.applyAccountRestore();
  assert.equal(elements['restore-apply'].disabled, false);
  assert.equal(reads, 2, 'failed submission does not refresh');
  failWrite = false; await context.applyAccountRestore();
  assert.equal(posts, 3); assert.equal(reads, 3);
  assert.equal(keys[1], keys[2], 'uncertain submission keeps the same retry identity');
});


test('SPEC-032 late refresh cannot change a replacement preview or account', async () => {
  for (const changeAccount of [false, true]) for (const fails of [false, true]) {
    let session = {}, settle;
    const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= { disabled: false, hidden: true, value: '', textContent: '' } });
    const context = vm.createContext({ document: { getElementById: id => elements[id] }, registerFeatureReset() {},
      captureAuthSession: () => session, isCurrentAuthSession: value => value === session,
      jsonRequest: async () => ({ token: 'first', summary: { mode: 'merge' } }), apiPost: async () => {},
      loadData: () => new Promise((resolve, reject) => { settle = () => fails ? reject(Error('old read failed')) : resolve(); }),
      loadWorkspaceHistory() { throw Error('stale refresh cannot reload history'); },
    });
    vm.runInContext(fs.readFileSync('frontend/app-account-restore.js', 'utf8'), context);
    const controller = await bindRestoreController(context);
    await controller.preview(controller.beginPreview(), '{}', 'merge');
    const pending = context.applyAccountRestore();
    await new Promise(resolve => setImmediate(resolve));
    if (changeAccount) session = {};
    context.resetAccountRestore();
    await controller.preview(controller.beginPreview(), '{}', 'merge');
    elements['restore-preview'].textContent = 'replacement preview';
    elements['restore-apply'].disabled = false;
    settle(); await pending;
    assert.equal(elements['restore-preview'].textContent, 'replacement preview');
    assert.equal(elements['restore-refresh'].hidden, true);
    assert.equal(elements['restore-apply'].disabled, false);
    assert.equal(controller.state.pending, false);
  }
});


test('SPEC-032 downloads explicitly omit history and show capacity errors', async () => {
  const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= { disabled: false, checked: true, textContent: '' } });
  let url, downloads = 0, ok = true, created;
  const context = vm.createContext({ document: { getElementById: id => elements[id], body: { appendChild() {} },
    createElement: () => created = { click() { downloads++; }, remove() {} } },
    window: { URL: { createObjectURL: () => 'blob:synthetic', revokeObjectURL() {} } },
    API_BASE: '/api', authHeaders: () => ({}), localDateISO: () => '2026-10-24',
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true, registerFeatureReset() {},
    authenticatedFetch: async path => { url = path; return { ok, status: 400, headers: { get: () => 'attachment; filename="synthetic_without_history.json"' } }; },
    readAuthenticatedBody: async () => ({}), readAuthenticatedError: async () => ({ detail: '異動歷史超過 50,000 筆，請取消包含異動歷史後再下載。' }),
  });
  vm.runInContext(fs.readFileSync('frontend/app-exports.js', 'utf8'), context);
  elements['workspace-export-history'].checked = false;
  await context.exportAccountData(true);
  assert.equal(url, '/api/export/account?include_history=false');
  assert.match(created.download, /without_history/);
  assert.match(elements['workspace-export-status'].textContent, /不含異動歷史/);
  assert.equal(downloads, 1);
  elements['workspace-export-history'].checked = true; ok = false;
  await context.exportAccountData(true);
  assert.equal(url, '/api/export/account?include_history=true');
  assert.match(elements['workspace-export-status'].textContent, /50,000.*取消包含異動歷史/);
  assert.equal(downloads, 1, 'rejected archives do not create downloads');
  assert.equal(elements['workspace-export'].disabled, false);
});

test('SPEC-033 expired send cannot release a replacement lease after reattach', async () => {
  const first = deferred(), second = deferred(); let sends = 0;
  const fixture = await setup(undefined, async () => {
    if (++sends === 1) { await first.promise; throw Object.assign(Error('old failure'), { status: 404 }); }
    await second.promise;
  });
  const controller = fixture.create(); await controller.attach('A');
  await controller.enqueue({ km: 5 }, 'lease-recovery-operation');
  const oldSend = controller.flush(); await new Promise(resolve => setImmediate(resolve));
  controller.detach(); fixture.switch(); await controller.attach('A'); fixture.setTime(121001);
  const newSend = controller.flush(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(sends, 2);
  const lease = (await controller.read('queue'))[0].lease;
  first.resolve(); await oldSend;
  const current = (await controller.read('queue'))[0];
  assert.equal(current.status, 'pending'); assert.equal(current.lease, lease);
  await assert.rejects(controller.remove('lease-recovery-operation'), /正在同步/);
  second.resolve(); await newSend; assert.deepEqual(await controller.read('queue'), []);
});

test('SPEC-033 sync reports committed writes when core refresh fails', async () => {
  const fixture = workspaceSyncContext(), { context, controller, elements } = fixture;
  controller.flush = async () => ({ synced: 1 });
  context.resourceStore = { ...context.resourceStore, getError: resource => resource === 'shoes' ? Error('offline') : null };
  await context.syncWorkspace({ manual: true });
  assert.match(elements['workspace-sync-status'].textContent, /紀錄已送出，但畫面更新失敗/);
  context.resourceStore = { ...context.resourceStore, getError: resource => ['goal', 'dashboard-analytics'].includes(resource) ? Error('not requested') : null };
  await context.syncWorkspace({ manual: true });
  assert.doesNotMatch(elements['workspace-sync-status'].textContent, /畫面更新失敗/);
});

test('SPEC-033 deletion recovery retries reads after a committed write', async () => {
  const makeElement = () => ({ children: [], textContent: '', disabled: false,
    append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; this.textContent = ''; } });
  const elements = { 'workspace-history': makeElement(), 'history-more': makeElement() };
  let posts = 0, reads = 0, fail = true;
  const context = vm.createContext({
    document: { getElementById: id => elements[id], createElement: makeElement },
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true, registerFeatureReset() {},
    formatLocalTimestamp: value => value, newOperationKey: () => 'recover-operation',
    apiPost: async () => { posts++; },
    apiGet: async () => ({ rows: posts ? [] : [{ id: 1, entity: 'runs', entity_id: 2, action: 'delete', can_restore: true }], next_cursor: null }),
    loadData: async () => { reads++; if (fail) throw Error('network'); },
  });
  vm.runInContext(fs.readFileSync('frontend/app-history.js', 'utf8'), context);
  await context.loadWorkspaceHistory();
  const button = elements['workspace-history'].children[0].children[1];
  await button.onclick();
  assert.equal(posts, 1); assert.equal(button.disabled, false); assert.equal(button.textContent, '重新載入資料');
  fail = false; await button.onclick();
  assert.equal(posts, 1); assert.equal(reads, 2);
});

test('SPEC-034 manual empty sync refreshes cloud and rejects foreign notifications', async () => {
  const fixture = workspaceSyncContext(), { context, elements } = fixture;
  await context.syncWorkspace({ manual: true });
  assert.equal(fixture.loads(), 1); assert.match(elements['workspace-sync-status'].textContent, /已重新載入雲端/);
  context.receiveWorkspaceCommit({ type: 'run-committed', account: 'synthetic-B' });
  context.receiveWorkspaceCommit({ type: 'unknown', account: 'synthetic-A' });
  await new Promise(resolve => setImmediate(resolve)); assert.equal(fixture.loads(), 1);
  context.receiveWorkspaceCommit({ type: 'run-committed', account: 'synthetic-A' });
  await new Promise(resolve => setImmediate(resolve)); assert.equal(fixture.loads(), 2);
  context.loadData = async () => { throw Error('offline read'); };
  await context.syncWorkspace({ manual: true });
  assert.match(elements['workspace-sync-status'].textContent, /雲端資料載入失敗.*更新雲端資料」重試/);
});

test('SPEC-034 commit notification failure never requeues a confirmed write', async () => {
  const { createWorkspaceController } = await import('../../frontend/runtime/workspace-controller.mjs');
  const storage = memoryStore(), notifications = [], session = {};
  const controller = createWorkspaceController({ storage, clock: () => 1, newKey: () => 'notification-lease-key',
    session: { capture: () => session, current: value => value === session }, send: async () => {},
    committed: account => { notifications.push(account); throw Error('channel closed'); } });
  await controller.attach('A'); await controller.enqueue({ km: 5 }, 'notification-operation');
  assert.deepEqual(await controller.flush(), { synced: 1 });
  assert.deepEqual(await controller.read('queue'), []); assert.deepEqual(notifications, ['A']);
});

test('SPEC-034 manual refresh joins an automatic empty queue check', async () => {
  const fixture = workspaceSyncContext(), { context, controller } = fixture;
  const gate = deferred(); controller.flush = () => gate.promise;
  const automatic = context.syncWorkspace(); const manual = context.syncWorkspace({ manual: true });
  gate.resolve({ synced: 0 }); await Promise.all([automatic, manual]);
  assert.equal(fixture.loads(), 1);
});

test('SPEC-034 a commit during cloud refresh schedules a fresh trailing read', async () => {
  const fixture = workspaceSyncContext(), { context } = fixture;
  const gate = deferred(); let reads = 0;
  context.loadData = async () => { if (++reads === 1) await gate.promise; };
  const pending = context.syncWorkspace({ manual: true });
  await new Promise(resolve => setImmediate(resolve));
  context.receiveWorkspaceCommit({ type: 'run-committed', account: 'synthetic-A' });
  gate.resolve(); await pending;
  assert.equal(reads, 2, 'a read begun before another commit cannot acknowledge that commit');
});

function fakeIndexedDB() {
  // Minimal IndexedDB for app-local-store.js; a closed connection throws like WebKit's.
  const rows = new Map(), connections = []; let opens = 0;
  function connect() {
    const connection = { closing: false, onclose: null, onversionchange: null,
      close() { this.closing = true; },
      createObjectStore: () => ({ createIndex() {} }),
      transaction() {
        if (this.closing) { const error = Error('The database connection is closing.'); error.name = 'InvalidStateError'; throw error; }
        let pending = 0;
        const tx = { aborted: false, error: null, abort() { this.aborted = true; queueMicrotask(() => tx.onabort?.()); } };
        const request = run => {
          const handle = {}; pending++;
          queueMicrotask(() => {
            handle.result = run(); handle.onsuccess?.();
            if (--pending === 0 && !tx.aborted) queueMicrotask(() => tx.oncomplete?.());
          });
          return handle;
        };
        tx.objectStore = () => ({
          index: () => ({ getAll: account => request(() => [...rows.values()].filter(row => row.account === account).map(row => structuredClone(row))) }),
          get: key => request(() => structuredClone(rows.get(JSON.stringify(key)))),
          put: value => { rows.set(JSON.stringify(value.key), structuredClone(value)); },
          delete: key => { rows.delete(JSON.stringify(key)); },
        });
        return tx;
      } };
    connections.push(connection);
    return connection;
  }
  const indexedDB = { open() {
    const request = {}, first = ++opens === 1;
    setTimeout(() => { request.result = connect(); if (first) request.onupgradeneeded?.(); request.onsuccess?.(); });
    return request;
  } };
  return { indexedDB, connections, opens: () => opens };
}

test('local workspace store reopens a connection the browser closed', async () => {
  const fake = fakeIndexedDB();
  const context = require('node:vm').createContext({ indexedDB: fake.indexedDB, setTimeout, clearTimeout, queueMicrotask, structuredClone });
  require('node:vm').runInContext(fs.readFileSync(path.join(__dirname, '../../frontend/app-local-store.js'), 'utf8'), context);
  const store = await context.openLocalWorkspaceStore();
  await store.update(['synthetic-A', 'queue', 'op-1'], () => ({ status: 'pending' }));
  // WebKit (iOS Safari) may close a live connection with no versionchange and a late close event.
  fake.connections[0].close();
  assert.equal((await store.list('synthetic-A', 'queue')).length, 1, 'queued run stays readable after a silent close');
  assert.equal(fake.opens(), 2);
  // With a close event the store reopens up front, and writes still commit.
  fake.connections[1].close(); fake.connections[1].onclose();
  await store.update(['synthetic-A', 'queue', 'op-1'], () => null);
  assert.equal((await store.list('synthetic-A', 'queue')).length, 0);
  assert.equal(fake.opens(), 3);
  // Application validation failures are never retried as connection loss.
  await assert.rejects(store.update(['synthetic-A', 'queue', 'op-2'], () => { throw Error('操作識別碼與內容不符'); }), /操作識別碼與內容不符/);
  assert.equal(fake.opens(), 3);
});

test('SPEC-107 the goal form, shoe editor and account view register their workspace drafts', async () => {
  const calls = [];
  const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= { value: '', textContent: '', dataset: {},
    classList: { contains: () => id === 'modal', add() {}, remove() {} } } });
  const context = vm.createContext({ document: { getElementById: id => elements[id], querySelectorAll: () => [] },
    window: { location: { origin: 'https://example.test' } }, currentUser: 'demo',
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true, registerFeatureReset() {}, newOperationKey: () => 'key',
    readForm: ids => Object.fromEntries(ids.map(id => [id, elements[id].value])),
    formSnapshotMatches: (a, b) => JSON.stringify(a) === JSON.stringify(b), coreData: { runningGoal: { start_year: 2026, monthly_km: 100 } },
    goalFormValues: goal => ({ 'goal-start-year': String(goal.start_year), 'goal-monthly-km': String(goal.monthly_km) }),
    getSelectedCategories: () => ['Daily'],
    shoeModal: { context: { shoe: { id: 7 } }, mode: 'edit', formIds: { model: 'f-model' },
      openForEdit: shoe => calls.push(`edit ${shoe.id}`), openForCreate: () => calls.push('create') },
    renderEmailSection: async () => { calls.push('email'); }, loadWorkspaceHistory: async () => {},
    inlineEditors: new Map(), structuredClone,
  });
  // The shared feature context installs the real goal helpers; observe these instead.
  Object.assign(context, { prepareGoalForm: () => calls.push('prepare'), setGoalField: (id, value) => calls.push(`${id}=${value}`),
    getFormDraft: () => ({ reset: () => calls.push('reset') }) });
  vm.runInContext(fs.readFileSync('frontend/app-workspace.js', 'utf8'), context);
  vm.runInContext(featureRegistrations(/^(?:registerWorkspaceForm|registerWorkspaceEditor|onWorkspaceModalOpen)\(/gm), context);
  assert.deepEqual([...vm.runInContext('Object.keys(workspaceForms)', context)], ['run', 'goal']);
  const saved = [];
  vm.runInContext("localWorkspace.controller = { account: 'a', save: async (...args) => { saves.push(args); } };", Object.assign(context, { saves: saved }));
  elements['goal-start-year'].value = '2026'; elements['goal-monthly-km'].value = '100'; elements['f-model'].value = 'Rider';
  context.persistWorkspaceDrafts();
  let snapshot = saved.at(-1)[2];
  assert.equal(snapshot.forms.goal, undefined, 'a goal form equal to the saved goal is not a draft');
  assert.deepEqual(snapshot.editors['shoe:7'], { kind: 'shoe', base: { id: 7 }, mode: 'edit', values: { 'f-model': 'Rider' }, categories: ['Daily'] });
  elements['goal-monthly-km'].value = '150';
  context.persistWorkspaceDrafts();
  snapshot = saved.at(-1)[2];
  assert.equal(snapshot.forms.goal['goal-monthly-km'], '150');
  vm.runInContext("workspaceFormAdapters.goal.restore('goal-monthly-km', '150'); workspaceFormAdapters.goal.reset();", context);
  context.closeWorkspaceModal = () => {}; context.renderWorkspaceQueue = async () => {};
  context.resumeWorkspaceEditor('shoe:7');
  context.openWorkspaceModal();
  assert.deepEqual(calls, ['prepare', 'goal-monthly-km=150', 'reset', 'prepare', 'edit 7', 'email']);
  assert.equal(elements['f-model'].value, 'Rider', 'the draft values return after the editor reopens');
  const source = fs.readFileSync('frontend/app-workspace.js', 'utf8');
  assert.doesNotMatch(source, /shoeModal|goalFormValues|prepareGoalForm|setGoalField|renderEmailSection|getSelectedCategories/);
});
