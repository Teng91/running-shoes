const { test, assert, vm, extract, runContext } = require('./helpers.cjs');

function draftContext() {
  const nodes = {
    'run-error': {}, 'run-date': { value: '2026-01-05' }, 'run-km': { value: '5' }, 'run-duration': { value: '' },
    'run-shoe': { value: '1' }, 'run-month': { value: '2026-01' }, 'add-run-btn': {},
  };
  let finish;
  const context = runContext({ document: { getElementById: id => nodes[id] },
    localDateISO: () => '2026-10-22', refreshDateLimits() {}, loadData: async () => {},
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true,
    apiPost: () => new Promise(resolve => finish = resolve),
  });
  vm.runInContext(extract('addRun'), context);
  return { context, nodes, finish: () => finish() };
}

test('SPEC-020 successful run creation preserves newly typed distance, date and shoe drafts', async () => {
  for (const [field, value] of [['km', '8'], ['date', '2026-01-06'], ['duration', '32:00'], ['shoe', '2']]) {
    const fixture = draftContext();
    const saving = fixture.context.addRun();
    fixture.nodes['run-' + field].value = value;
    fixture.finish(); await saving;
    assert.equal(fixture.nodes['run-' + field].value, value);
    assert.equal(fixture.nodes['run-km'].value, field === 'km' ? '8' : '5');
    assert.equal(fixture.nodes['add-run-btn'].disabled, false);
  }
});

test('SPEC-020 successful run creation clears unchanged input but preserves a newly selected month', async () => {
  const fixture = draftContext();
  const saving = fixture.context.addRun();
  fixture.nodes['run-month'].value = '2026-02';
  fixture.finish(); await saving;
  assert.equal(fixture.nodes['run-km'].value, '');
  assert.equal(fixture.nodes['run-month'].value, '2026-02');
});

test('SPEC-020 native run controllers isolate state, editor snapshots and reset pending operations', async () => {
  const { createRunController } = await import('../../frontend/runtime/run-controller.mjs');
  let finish, epoch = 1;
  const writes = [];
  const controller = createRunController({
    session: { capture: () => epoch, current: value => value === epoch }, newKey: () => 'synthetic-key',
    transport: { post: () => new Promise(resolve => finish = resolve),
      put: async (...args) => writes.push(args), delete: async (...args) => writes.push(args) },
  });
  const operation = controller.beginCreate({ km: 5 }, {});
  assert.equal(controller.beginCreate({ km: 6 }, {}), null);
  const pending = controller.submitCreate(operation, { km: 5 });
  controller.state.rows.push({ id: 1 });
  controller.state.lastCreateResult = { queued: true };
  const editor = controller.openEditor({ id: 1, version: 2 });
  assert.equal(await controller.saveEditor(editor, { km: 8 }), true);
  assert.equal(await controller.deleteEditor(editor), true);
  assert.equal(writes[1][0], '/runs/1?expected_version=2');
  controller.reset(); epoch++;
  finish(); assert.equal(await pending, false);
  assert.equal(controller.isCurrentCreate(operation), false);
  assert.equal(controller.finishCreate(operation), false);
  assert.equal(controller.isCurrentEditor(editor), false);
  assert.equal(await controller.saveEditor(editor, {}), false);
  assert.equal(await controller.deleteEditor(editor), false);
  assert.equal(controller.editor, null);
  assert.equal(controller.state.rows.length, 0);
  assert.equal(controller.state.lastCreateResult, null);
});
