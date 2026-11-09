const { test, assert, vm, fs, htmlSource } = require('./helpers.cjs');

test('SPEC-039 the monthly tab has no records table, add form or edit dialog', () => {
  for (const id of ['monthly-table', 'add-km', 'add-monthly-btn', 'monthly-modal', 'monthly-records']) {
    assert.doesNotMatch(htmlSource, new RegExp(`id="${id}"`));
  }
  for (const id of ['goal-overview', 'year-select', 'chart-monthly-year', 'chart-shoe-stacked']) {
    assert.match(htmlSource, new RegExp(`id="${id}"`));
  }
  const assets = JSON.parse(fs.readFileSync('frontend/assets.json', 'utf8'));
  assert.equal(JSON.stringify(assets).includes('app-monthly.js'), false);
  assert.equal(fs.existsSync('frontend/app-monthly.js'), false);
});

function workspaceContext(draft) {
  const elements = new Proxy({}, { get: (rows, id) => rows[id] ||= { value: '', dataset: {}, classList: { add() {} } } });
  const context = vm.createContext({
    document: { getElementById: id => elements[id] }, window: { location: { origin: 'https://app' } },
    authToken: 'token', currentUser: 'runner', registerFeatureReset() {},
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true, newOperationKey: () => 'key',
  });
  vm.runInContext(fs.readFileSync('frontend/app-workspace.js', 'utf8'), context);
  vm.runInContext(`localWorkspace.ready = true;
    localWorkspace.controller = { attach: async () => records };`, Object.assign(context, {
    records: [{ key: ['a', 'drafts', 'forms'], value: draft }],
  }));
  context.renderWorkspaceQueue = async () => {};
  context.syncWorkspace = async () => {};
  return { context, elements };
}

test('SPEC-039 drafts saved by older versions drop monthly editors and forms', async () => {
  const { context, elements } = workspaceContext({
    runDraftId: 'run', forms: { monthly: { 'add-year': '2026', 'add-month': '10', 'add-km': '180' } },
    editors: { 'monthly:5': { kind: 'monthly', base: { id: 5 }, values: { 'm-km': '9' } },
      'shoe:2': { kind: 'shoe', base: { id: 2 }, values: {} } },
  });
  await context.activateLocalWorkspace();
  assert.deepEqual(Object.keys(vm.runInContext('localWorkspace.editors', context)), ['shoe:2']);
  assert.equal(elements['add-km'].value, '', 'an old monthly add-form draft is not written into the page');
  // A stale reference to an old monthly draft key is a no-op instead of opening a removed dialog.
  vm.runInContext("localWorkspace.editors['monthly:5'] = { kind: 'monthly', base: { id: 5 }, values: { 'm-km': '9' } }", context);
  context.closeWorkspaceModal = () => {};
  context.resumeWorkspaceEditor('monthly:5');
  assert.equal(elements['m-km'].value, '');
});
