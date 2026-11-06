const { test, assert, fs, path, vm, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, transportContext } = require('./helpers.cjs');

test('login locks duplicates and ignores a late body or failure after a new account starts', async () => {
  const { context, elements, controls, state } = authOperationContext();
  elements['login-username'].value = 'A'; elements['login-password'].value = 'pass';
  let finishBody, calls = 0;
  context.fetch = async () => { calls++; return { ok: true, json: () => new Promise(resolve => { finishBody = resolve; }) }; };
  const old = context.handleLogin(); await Promise.resolve();
  await context.handleLogin();
  assert.equal(calls, 1); assert.equal(controls[0].disabled, true);
  context.clearAuth(); elements['login-username'].value = 'B';
  context.fetch = async () => ({ ok: true, json: async () => ({ access_token: 'mock' }) });
  await context.handleLogin();
  const hides = state.hides;
  finishBody({ access_token: 'old-mock' }); await old;
  assert.equal(state.account, 'B'); assert.equal(state.hides, hides);

  let fail;
  context.fetch = () => new Promise((_, reject) => { fail = reject; });
  const failed = context.handleLogin(); const rejectOld = fail;
  context.cancelAuthOperation();
  const pending = context.handleLogin();
  const rejectCurrent = fail;
  // An invalidated operation cannot unlock a newer pending form.
  rejectOld(new Error('stale failure')); await failed;
  assert.equal(controls[0].disabled, true);
  assert.equal(state.writes.length, 0);
  rejectCurrent(new Error('current failure')); await pending;
  assert.equal(controls[0].disabled, false); assert.deepEqual(state.writes, ['current failure']);
});

test('register and password-change callbacks cannot mutate a replacement session', async () => {
  for (const action of ['handleRegister', 'handleChangePassword']) {
    const { context, elements, state } = authOperationContext();
    for (const id of ['reg-username', 'change-username']) elements[id].value = 'A';
    for (const id of ['reg-password', 'reg-password2', 'change-old-password', 'change-new-password', 'change-new-password2']) elements[id].value = 'password';
    let finish, calls = 0;
    context.fetch = () => { calls++; return new Promise(resolve => { finish = resolve; }); };
    const request = context[action](); await context[action]();
    assert.equal(calls, 1);
    context.setAuth('mock-B', 'B');
    finish({ ok: true, json: async () => ({ access_token: 'mock-A' }) });
    await request;
    assert.equal(state.account, 'B'); assert.equal(calls, 1); assert.equal(state.writes.length, 0);
  }
});

test('all shoe mutations lock their snapshot and leave replacement drafts and sessions untouched', async () => {
  const definition = source.slice(source.indexOf('class ShoeModal {'), source.indexOf('// 初始化一次'));
  for (const action of ['submit', 'delete', 'move']) {
    for (const failure of [false, true]) {
      for (const switchSession of [false, true]) {
      let session = { current: true }, finish, writes = 0, alerts = 0;
      const context = vm.createContext({ captureAuthSession: () => session,
        isCurrentAuthSession: value => value.current, alert: () => alerts++, confirm: () => true,
        loadData: async () => {}, shoes: [],
      });
      vm.runInContext(definition + '\nglobalThis.Modal = ShoeModal;', context);
      const button = {}, modal = Object.create(context.Modal.prototype);
      Object.assign(modal, { formIds: {}, btnDelete: {}, btnMove: {}, el: { querySelector: () => button,
        classList: { add() {}, remove() {} } }, _fillForm() {}, _updateUI() {},
        _payload: () => ({ brand: 'A', model: 'draft', date: '2026-01-01' }),
      });
      const write = () => { writes++; return new Promise((resolve, reject) => { finish = failure ? reject : resolve; }); };
      context.apiPut = write; context.apiDelete = write;
      modal.openForEdit({ id: 1, version: 3 }, false);
      const old = modal[action](); await modal[action]();
      assert.equal(writes, 1); assert.equal(button.disabled, true);
      modal.close();
      if (switchSession) { session.current = false; session = { current: true }; }
      modal.openForEdit({ id: 2, version: 7 }, false);
      const replacement = modal.context;
      finish(failure ? new Error('old failure') : {}); await old;
      assert.equal(modal.context, replacement); assert.equal(modal.shoe.id, 2);
      assert.equal(button.disabled, false); assert.equal(alerts, 0);
      }
    }
  }
});

test('report status separates saved confirmations from errors and clears stale error styles', () => {
  const classes = new Set();
  const status = { textContent: '', classList: { toggle(name, on) { if (on) classes.add(name); else classes.delete(name); } } };
  const context = vm.createContext({ document: { getElementById: () => status } });
  vm.runInContext(extract('setReportStatus'), context);
  context.setReportStatus('讀取失敗'); assert.equal(classes.has('is-error'), true);
  context.setReportStatus('報告已儲存', 'success'); assert.equal(classes.has('is-error'), false);
  assert.equal(status.textContent, '報告已儲存');
  context.setReportStatus('未儲存'); context.setReportStatus('');
  assert.equal(status.textContent, ''); assert.equal(classes.size, 0);
  assert.match(extract('renderReport'), /formatLocalTimestamp\(report\.updated_at\), 'success'/);
  assert.match(extract('generateReport'), /formatLocalTimestamp\(event\.updated_at\), 'success'/);
});

test('saved and streamed report timestamps share local formatting', () => {
  const elements = new Proxy({}, { get: (target, id) => target[id] ||= { options: [], textContent: '', classList: { toggle() {} } } });
  const context = vm.createContext({ document: { getElementById: id => elements[id] }, renderMarkdown: value => value });
  vm.runInContext(['formatLocalTimestamp', 'reportMonthLabel', 'setReportStatus', 'renderReport'].map(extract).join('\n'), context);
  const timestamp = '2026-10-20T00:30:00+00:00';
  context.renderReport({ year: 2026, month: 9, updated_at: timestamp, model: 'mock', content_md: 'mock' });
  assert.ok(elements['report-status'].textContent.endsWith(context.formatLocalTimestamp(timestamp)));
  assert.ok(extract('generateReport').includes('formatLocalTimestamp(event.updated_at)'));
});

test('exports, goals and chart modules retain single responsibilities and startup order', () => {
  assert.match(fs.readFileSync('frontend/app-exports.js', 'utf8'), /function exportAccountData\(/);
  assert.match(fs.readFileSync('frontend/app-goals.js', 'utf8'), /function saveRunningGoal\(/);
  assert.match(fs.readFileSync('frontend/app-shoe-charts.js', 'utf8'), /function renderCharts\(/);
  assert.match(fs.readFileSync('frontend/app-monthly-charts.js', 'utf8'), /function renderMonthlyYearChart\(/);
  const common = fs.readFileSync('frontend/app-charts.js', 'utf8');
  assert.doesNotMatch(common, /new Chart\(/);
  assert.ok(htmlSource.indexOf('/app-charts.js?') < htmlSource.indexOf('/app-shoe-charts.js?'));
  assert.ok(htmlSource.indexOf('/app-monthly-charts.js?') < htmlSource.indexOf('/app.js?'));
});

test('shared SSE reader handles byte boundaries, UTF-8, CRLF, comments and multiline data', async () => {
  const context = streamContext();
  const encoded = new TextEncoder().encode(': heartbeat\r\ndata: {"type":"token",\r\ndata: "text":"跑步🏃"}\r\n\r\ndata: {"type":"done"}');
  const response = context.bind(new Response(new ReadableStream({ start(controller) {
    for (const byte of encoded) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } }));
  const events = [];
  const result = await context.readJsonEventStream(response, { onEvent: event => events.push(event) });
  assert.equal(events[0].text, '跑步🏃');
  assert.equal(result.completed, true);
  assert.equal(events.length, 2);
});

test('shared SSE reader distinguishes EOF, application errors, malformed data and HTTP failures', async () => {
  const context = streamContext();
  const response = body => context.bind(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }));
  const incomplete = await context.readJsonEventStream(response('data: {"type":"token","text":"half"}\n\n'), { onEvent() {} });
  assert.equal(incomplete.completed, false);
  const failed = await context.readJsonEventStream(response('data: {"type":"error","text":"failure"}\n\ndata: {"type":"done"}\n\n'), { onEvent() {} });
  assert.equal(failed.receivedError, true);
  assert.equal(failed.completed, false);
  await assert.rejects(context.readJsonEventStream(response('data: broken\n\n'), { onEvent() {} }), /格式錯誤/);
  await assert.rejects(context.readJsonEventStream(context.bind(new Response('{"detail":"unavailable"}', { status: 503 })), { onEvent() {} }), /unavailable/);
  await assert.rejects(context.readJsonEventStream(context.bind(new Response('{}')), { onEvent() {} }), /非預期格式/);
});

test('shared SSE reader cancels pending reads and ignores stale sessions', async () => {
  const context = streamContext();
  const abort = new AbortController();
  let cancelled = false;
  const response = context.bind(new Response(new ReadableStream({ cancel() { cancelled = true; } }), {
    headers: { 'Content-Type': 'text/event-stream' },
  }));
  const reading = context.readJsonEventStream(response, { signal: abort.signal, onEvent() { assert.fail('aborted event'); } });
  abort.abort();
  await assert.rejects(reading, { name: 'AbortError' });
  assert.equal(cancelled, true);
  const stale = context.bind(new Response('data: {"type":"done"}\n\n', { headers: { 'Content-Type': 'text/event-stream' } }));
  context.authenticatedResponses.get(stale).current = false;
  await assert.rejects(context.readJsonEventStream(stale, { onEvent() { assert.fail('stale event'); } }), { name: 'AbortError' });
});

test('run modal keeps its original version and does not close a newer modal after saving', async () => {
  const { context, elements } = editContext();
  context.runController.state.rows = [{ id: 1, shoe_id: 3, km: 5, version: 6, date: '2026-01-01' }];
  context.openRunModal(1);
  elements['edit-run-shoe'].value = '3';
  context.runController.state.rows = [{ ...context.runController.state.rows[0], km: 10, version: 7 }, { ...context.runController.state.rows[0], id: 2 }];
  let finish, calls = 0;
  context.apiPut = (url, payload) => {
    calls++; assert.equal(url, '/runs/1'); assert.equal(payload.expected_version, 6);
    return new Promise(resolve => { finish = resolve; });
  };
  const save = context.saveRun();
  await context.saveRun();
  assert.equal(calls, 1);
  context.closeRunModal(); context.openRunModal(2);
  finish(); await save;
  assert.equal(context.runController.editor.id, 2);
  assert.equal(context.runController.state.rows[0].km, 10);
  context.apiPut = async () => { throw new Error('409 conflict'); };
  await context.saveRun();
  assert.equal(elements['edit-run-error'].textContent, '409 conflict');
});
