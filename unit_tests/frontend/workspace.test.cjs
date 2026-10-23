const { test, assert, transportContext, vm, fs } = require('./helpers.cjs');
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
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
  vm.runInContext("accountRestore.preview = { token: 'first' }; accountRestore.operationId = 'restore-operation-first';", context);
  const pending = context.applyAccountRestore();
  await context.previewAccountRestore();
  assert.equal(vm.runInContext('accountRestore.revision', context), 0, 'pending apply owns its preview');
  context.resetAccountRestore();
  vm.runInContext("accountRestore.preview = { token: 'second' };", context);
  elements['restore-preview'].textContent = 'new preview';
  gate.resolve({ ok: true }); await pending;
  assert.equal(elements['restore-preview'].textContent, 'new preview');
  assert.equal(vm.runInContext('accountRestore.preview.token', context), 'second');
  assert.equal(vm.runInContext('accountRestore.pending', context), false);
  assert.equal(loads, 1, 'committed old operation still refreshes server data');
});
