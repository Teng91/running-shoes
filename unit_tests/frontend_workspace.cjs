// SPEC-027: real IndexedDB, offline shell and transactional APIs; synthetic accounts only.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const { startArtifacts, saveFailure, closeBrowser, withDeadline } = require('../scripts/browser_artifacts.cjs');
const { waitForAsync } = require('./browser_waits.cjs');
module.exports = async function checkWorkspace(browser, baseUrl) {
  const suffix = `${browser.browserType().name()}-${Date.now()}`;
  const password = 'Synthetic-workspace-91!';
  async function api(token, path, body, method = body === undefined ? 'GET' : 'POST') {
    const response = await fetch(baseUrl + '/api' + path, { method, headers: {
      'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}),
    }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    assert.ok(response.ok, `${method} ${path}: ${response.status}`);
    return response.json();
  }
  async function account(name) {
    const username = `workspace-${name}-${suffix}`;
    await api(null, '/auth/register', { username, password });
    const result = await api(null, '/auth/login', { username, password });
    return { username, token: result.access_token };
  }
  const a = await account('a'), b = await account('b');
  const shoe = await api(a.token, '/shoes', { brand: 'Offline', model: 'Reliable', date: '2026-01-01', mileage: 20 });
  await api(b.token, '/shoes', { brand: 'Other', model: 'Existing', date: '2026-01-01', mileage: 3 });
  // WebKit's native emulation rejects SW navigations internally. As in the PWA
  // harness, disconnect the origin itself and let the installed SW serve the shell.
  let networkDown = false, disconnectedApi = 0, holdPreview = null, failRefreshReads = false, applyRequests = 0;
  const origin = http.createServer(async (request, response) => {
    if (holdPreview && request.url === '/api/account-restore/preview?mode=merge') {
      const held = holdPreview; holdPreview = null; held.started(); await held.gate;
    }
    if (request.method === 'POST' && request.url === '/api/account-restore/apply') applyRequests++;
    if (failRefreshReads && request.url === '/api/shoes/active') {
      response.writeHead(500, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ detail: 'Synthetic refresh failure' })); return;
    }
    if (networkDown) {
      if (request.url.startsWith('/service-worker.js')) { response.writeHead(503); response.end('// offline'); return; }
      if (request.url.startsWith('/api/')) disconnectedApi++;
      request.socket.destroy(); return;
    }
    const upstream = http.request(new URL(request.url, baseUrl), { method: request.method, headers: request.headers }, result => {
      response.writeHead(result.statusCode, result.headers); result.pipe(response);
    });
    upstream.on('error', () => { if (!response.headersSent) response.writeHead(502); response.end(); });
    request.pipe(upstream);
  });
  await new Promise(resolve => origin.listen(0, '127.0.0.1', resolve));
  const browserUrl = 'http://127.0.0.1:' + origin.address().port;
  const context = await browser.newContext({ storageState: { cookies: [], origins: [{ origin: browserUrl, localStorage: [
    { name: 'token', value: a.token }, { name: 'username', value: a.username },
  ] }] } });
  let page;
  try {
    await startArtifacts(context);
    if (browser.browserType().name() === 'webkit') await context.addInitScript(() => {
      Object.defineProperty(navigator, 'onLine', { get: () => localStorage.getItem('__test_network_down') !== '1' });
    });
    page = await context.newPage();
    async function setOffline(offline) {
      networkDown = offline;
      if (browser.browserType().name() === 'chromium') await context.setOffline(offline);
      else await page.evaluate(value => {
        localStorage.setItem('__test_network_down', value ? '1' : '0');
        window.dispatchEvent(new Event(value ? 'offline' : 'online'));
      }, offline);
    }
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.accept());
    async function openWorkspaceSection(id) {
      const summary = page.locator(`#${id}`);
      if (!await summary.evaluate(element => element.parentElement.open)) await summary.click();
    }
    await page.goto(browserUrl, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => localWorkspace.controller?.account && shoes.length === 1);
    await page.evaluate(async () => { await navigator.serviceWorker.ready; });
    await page.waitForFunction(() => navigator.serviceWorker.controller);
    await page.locator('.tab[data-tab="runs"]').click();
    await page.locator('#run-date').fill('2026-01-02');
    await page.locator('#run-shoe').selectOption(String(shoe.id));
    await page.locator('#run-km').fill('5');
    await page.evaluate(() => { switchTab('monthly'); });
    await page.locator('#add-km').fill('180');
    await page.evaluate(() => { shoeModal.openForEdit(shoes[0], false); });
    await page.locator('#f-nickname').fill('Unfinished nickname');
    await page.evaluate(() => { shoeModal.close(); });
    await waitForAsync(page, async () => (await localWorkspace.controller.read('drafts'))[0]?.value.editors['shoe:' + shoes[0].id]?.values['f-nickname'] === 'Unfinished nickname');
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.getElementById('run-km').value === '5' && document.getElementById('add-km').value === '180');
    await page.getByRole('button', { name: '資料與同步', exact: true }).click();
    await page.getByRole('button', { name: '更新雲端資料', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('workspace-sync-status').textContent.includes('沒有待送跑步'));
    await openWorkspaceSection('drafts-title');
    await page.locator('#workspace-drafts').getByRole('button', { name: /繼續編輯 鞋款/ }).click();
    assert.equal(await page.locator('#f-nickname').inputValue(), 'Unfinished nickname');
    await page.evaluate(() => shoeModal.close());
    async function login(user) {
      await page.getByRole('button', { name: '登出', exact: true }).click();
      await page.locator('#login-username').fill(user.username); await page.locator('#login-password').fill(password);
      await page.locator('#login-form').getByRole('button', { name: '登入', exact: true }).click();
      await page.waitForFunction(name => currentUser === name && localWorkspace.controller?.account?.endsWith('|' + name), user.username);
      await page.evaluate(() => localWorkspace.activating);
    }
    await login(b);
    assert.equal(await page.locator('#run-km').inputValue(), '', 'B never sees A draft');
    assert.equal(await page.locator('#add-km').inputValue(), '');
    assert.equal(await page.evaluate(() => Object.keys(localWorkspace.editors).length), 0);
    await login(a);
    await page.waitForFunction(() => document.getElementById('run-km').value === '5');
    await page.locator('.tab[data-tab="runs"]').click();
    await setOffline(true);
    await page.locator('#add-run-btn').click();
    await waitForAsync(page, async () => document.getElementById('run-km').value === '' && (await localWorkspace.controller.read('queue')).length === 1);
    assert.equal((await api(a.token, '/runs')).length, 0, 'offline acceptance does not write server');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await waitForAsync(page, async () => localWorkspace.controller?.account && shoes.length === 1 && (await localWorkspace.controller.read('queue')).length === 1, null, {
      describe: async () => ({ ready: localWorkspace.ready, account: localWorkspace.controller?.account ?? null, error: localWorkspace.error,
        shoes: typeof shoes === 'undefined' ? 'undefined' : shoes.length, user: typeof currentUser === 'undefined' ? 'undefined' : currentUser,
        queue: localWorkspace.controller ? (await localWorkspace.controller.read('queue')).length : 'no-controller',
        onLine: navigator.onLine, sw: Boolean(navigator.serviceWorker?.controller), title: document.title,
        bootText: document.getElementById('boot-status')?.textContent ?? null, body: document.body?.innerText.slice(0, 300) }),
    });
    assert.equal(await page.locator('#run-km').inputValue(), '', 'consumed draft never reappears on offline restart');
    const failedProbe = await page.evaluate(async () => { try { await fetch('/api/runs'); return false; } catch { return true; } });
    assert.equal(failedProbe, true, 'authenticated API is not served from shell cache');
    if (browser.browserType().name() === 'webkit') assert.ok(disconnectedApi > 0);
    await page.getByRole('button', { name: '資料與同步', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('workspace-sync').disabled && document.getElementById('workspace-sync').textContent === '等待網路連線');
    assert.match(await page.locator('#workspace-status').textContent(), /跑步留在這台裝置，等待連線後送到雲端/);
    await page.getByRole('button', { name: '關閉', exact: true }).click();
    failRefreshReads = true;
    await setOffline(false);
    await page.evaluate(() => syncWorkspace());
    assert.match(await page.locator('#workspace-sync-status').textContent(), /紀錄已送出，但畫面更新失敗/);
    failRefreshReads = false;
    await page.evaluate(() => refreshCoreData());
    await waitForAsync(page, async () => (await localWorkspace.controller.read('queue')).length === 0);
    let runs = await api(a.token, '/runs'); assert.equal(runs.length, 1); assert.equal(runs[0].km, 5);
    const deletedRunId = runs[0].id;
    assert.equal((await api(a.token, '/shoes/active'))[0].mileage, 25);
    await page.evaluate(() => { switchTab('runs'); });
    await page.locator('#run-month').fill('2026-01'); await page.locator('#run-month').dispatchEvent('change');
    await page.locator('#run-table tr').filter({ hasText: '5.00 km' }).getByRole('button', { name: '編輯' }).click();
    await page.locator('#run-modal').getByRole('button', { name: '刪除', exact: true }).click();
    await page.locator('#run-modal').waitFor({ state: 'hidden' });
    await waitForAsync(page, async () => !Object.keys((await localWorkspace.controller.read('drafts'))[0]?.value.editors || {}).some(key => key.startsWith('run:')), null);
    await page.getByRole('button', { name: '資料與同步', exact: true }).click();
    await openWorkspaceSection('history-title');
    failRefreshReads = true;
    await page.locator('#workspace-history').getByRole('button', { name: '復原誤刪' }).click();
    await page.locator('#workspace-history').getByRole('button', { name: '重新載入資料' }).waitFor();
    failRefreshReads = false;
    await page.locator('#workspace-history').getByRole('button', { name: '重新載入資料' }).click();
    await page.waitForFunction(() => document.getElementById('workspace-history').textContent.includes('已復原'));
    runs = await api(a.token, '/runs'); assert.equal(runs.length, 1); assert.notEqual(runs[0].id, deletedRunId);
    assert.equal((await api(a.token, '/shoes/active'))[0].mileage, 25);
    await openWorkspaceSection('restore-title');
    const downloaded = page.waitForEvent('download');
    await page.locator('#workspace-export').click();
    const download = await downloaded;
    const backup = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
    assert.equal(backup.username, a.username);
    assert.ok(backup.history.length > 0);
    await page.locator('#workspace-export-history').uncheck();
    const omittedDownload = page.waitForEvent('download');
    await page.locator('#workspace-export').click();
    const omitted = await omittedDownload;
    assert.match(omitted.suggestedFilename(), /_without_history.json$/);
    const withoutHistory = JSON.parse(await fs.readFile(await omitted.path(), 'utf8'));
    assert.deepEqual(withoutHistory.history, []);
    assert.equal(withoutHistory.runs.length, backup.runs.length);
    await page.locator('#workspace-export-history').check();
    await page.waitForFunction(() => document.getElementById('workspace-export-status').textContent.includes('查看下載項目'));
    await page.evaluate(() => closeWorkspaceModal()); await login(b);
    await page.getByRole('button', { name: '資料與同步', exact: true }).click();
    await openWorkspaceSection('restore-title');
    const file = { name: 'synthetic-backup.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(backup)) };
    await page.locator('#restore-file').setInputFiles(file);
    await page.waitForFunction(() => !document.getElementById('restore-apply').disabled);
    assert.match(await page.locator('#restore-preview').textContent(), /新增 1 雙鞋、1 筆跑步/);
    await page.locator('#restore-apply').click(); await page.getByText('合併還原完成，現有內容已保留。', { exact: true }).waitFor();
    assert.equal((await api(b.token, '/runs')).length, 1);
    assert.equal((await api(b.token, '/shoes/active')).length, 2);
    await page.locator('#restore-file').setInputFiles(file);
    await page.waitForFunction(() => !document.getElementById('restore-apply').disabled);
    assert.match(await page.locator('#restore-preview').textContent(), /新增 0 雙鞋、0 筆跑步/);
    await page.locator('#restore-apply').click(); await page.getByText('合併還原完成，現有內容已保留。', { exact: true }).waitFor();
    assert.equal((await api(b.token, '/runs')).length, 1);
    const sourceShoe = (await api(a.token, '/shoes/active'))[0];
    await api(a.token, `/shoes/${sourceShoe.id}`, { nickname: 'Updated cloud nickname', expected_version: sourceShoe.version }, 'PUT');
    const sourceRun = (await api(a.token, '/runs'))[0];
    await api(a.token, `/runs/${sourceRun.id}`, { date: '2026-02-02', km: 8, shoe_id: sourceShoe.id, expected_version: sourceRun.version }, 'PUT');
    const newer = await api(a.token, '/export/account');
    await page.locator('#restore-mode').selectOption('update');
    await page.locator('#restore-file').setInputFiles({ ...file, buffer: Buffer.from(JSON.stringify(newer)) });
    await page.waitForFunction(() => !document.getElementById('restore-apply').disabled);
    assert.match(await page.locator('#restore-preview').textContent(), /將更新 1 雙鞋、1 筆跑步/);
    assert.match(await page.locator('#workspace-owner').textContent(), /目前網站：/);
    failRefreshReads = true;
    await page.locator('#restore-apply').click();
    await page.locator('#restore-refresh').waitFor({ state: 'visible' });
    await page.waitForFunction(() => !accountRestore.state.pending);
    assert.equal(await page.locator('#restore-apply').isDisabled(), true);
    const committedRequests = applyRequests;
    failRefreshReads = false;
    await page.locator('#restore-refresh').click();
    await page.locator('#restore-refresh').waitFor({ state: 'hidden' });
    assert.equal(applyRequests, committedRequests, 'refresh retry never submits import again');
    await page.getByText('資料匯入完成，同來源資料已更新，額外資料已保留。', { exact: true }).waitFor();
    const targetShoes = await api(b.token, '/shoes/active');
    assert.equal(targetShoes.length, 2);
    assert.equal(targetShoes.find(row => row.brand === 'Other').version, 0, 'unrelated shoe keeps its version');
    assert.equal(targetShoes.find(row => row.nickname === 'Updated cloud nickname').mileage, 28);
    const targetRuns = await api(b.token, '/runs');
    assert.equal(targetRuns.length, 1); assert.equal(targetRuns[0].km, 8); assert.equal(targetRuns[0].date, '2026-02-02');
    let releaseOld, oldStarted;
    const oldGate = new Promise(resolve => { releaseOld = resolve; });
    const sawOld = new Promise(resolve => { oldStarted = resolve; });
    // Delay at the origin: WebKit service-worker requests bypass page.route.
    holdPreview = { started: oldStarted, gate: oldGate };
    await page.locator('#restore-mode').selectOption('merge');
    await withDeadline(() => sawOld, 10000, 'old restore preview reaches origin');
    await page.locator('#restore-mode').selectOption('update');
    await page.waitForFunction(() => !document.getElementById('restore-apply').disabled);
    const newestToken = await page.evaluate(() => accountRestore.state.preview.token);
    assert.match(await page.locator('#restore-preview').textContent(), /將更新 0 雙鞋、0 筆跑步/);
    assert.match(await page.locator('#restore-preview').textContent(), /內容相同：1 雙鞋、1 筆跑步/);
    const oldResponse = page.waitForResponse(response => response.url().endsWith('/api/account-restore/preview?mode=merge'));
    const discarded = page.waitForResponse(response => response.request().method() === 'DELETE' && response.url().includes('/account-restore/preview/'));
    releaseOld(); await oldResponse; await discarded;
    assert.equal(await page.evaluate(() => accountRestore.state.preview.token), newestToken);
    await page.locator('#restore-apply').click();
    await page.getByText('資料匯入完成，同來源資料已更新，額外資料已保留。', { exact: true }).waitFor();
    assert.deepEqual((await api(b.token, '/shoes/active')).map(row => [row.id, row.version, row.mileage]), targetShoes.map(row => [row.id, row.version, row.mileage]));
    assert.deepEqual((await api(b.token, '/runs')).map(row => [row.id, row.version]), targetRuns.map(row => [row.id, row.version]));
    // The source recovers its own run before sending the next archive.
    const cloudRun = (await api(a.token, '/runs'))[0];
    await api(a.token, '/runs/' + cloudRun.id + '?expected_version=' + cloudRun.version, undefined, 'DELETE');
    const cloudDeleted = (await api(a.token, '/history')).rows.find(row => row.entity === 'runs' && row.entity_id === cloudRun.id && row.action === 'delete');
    await api(a.token, '/operations', { operation_id: 'portable-recovery-' + suffix, kind: 'history.restore', entity_id: cloudDeleted.id });
    const recoveredArchive = await api(a.token, '/export/account?include_history=false');
    assert.equal(recoveredArchive.version, 3);
    assert.ok(recoveredArchive.runs[0].aliases.includes(cloudRun.id));
    await page.locator('#restore-file').setInputFiles({ ...file, buffer: Buffer.from(JSON.stringify(recoveredArchive)) });
    await page.waitForFunction(() => !document.getElementById('restore-apply').disabled);
    assert.match(await page.locator('#restore-preview').textContent(), /新增 0 雙鞋、0 筆跑步/);
    await page.locator('#restore-apply').click();
    await page.getByText('資料匯入完成，同來源資料已更新，額外資料已保留。', { exact: true }).waitFor();
    assert.equal((await api(b.token, '/runs')).length, 1, 'source recovery keeps the receiver run identity');
    await page.evaluate(() => {
      const original = localWorkspace.controller;
      let release;
      const gate = new Promise(resolve => { release = resolve; });
      const wrapped = { ...original, async clear() {
        await original.clear(); window.__clearStarted = true; await gate;
      } };
      Object.defineProperty(wrapped, 'account', { get: () => original.account });
      localWorkspace.controller = wrapped;
      window.__finishClear = () => { release(); localWorkspace.controller = original; };
    });
    await page.locator('summary').filter({ hasText: '清除此裝置的本機資料' }).click();
    await page.getByRole('button', { name: '清除此帳號的本機資料', exact: true }).click();
    await page.waitForFunction(() => window.__clearStarted);
    await page.getByRole('button', { name: '關閉', exact: true }).click();
    await login(a);
    await page.locator('.tab[data-tab="runs"]').click();
    await page.locator('#run-km').fill('42');
    await page.evaluate(async () => { window.__finishClear(); await new Promise(requestAnimationFrame); });
    assert.equal(await page.locator('#run-km').inputValue(), '42', 'old account clear cannot erase new account input');
    // Real BroadcastChannel between two tabs; only the second tab consumes IDB.
    const otherPage = await context.newPage();
    await otherPage.goto(browserUrl, { waitUntil: 'networkidle' });
    await otherPage.waitForFunction(() => localWorkspace.controller?.account && shoes.length === 1);
    const queuedIdentity = 'cross-tab-' + suffix;
    const date = await page.evaluate(() => localDateISO());
    await page.evaluate(async ({ date, shoeId, identity }) => {
      window.__originalQueueController = localWorkspace.controller;
      const wrapped = { ...localWorkspace.controller, flush: async () => ({ synced: 0 }) };
      Object.defineProperty(wrapped, 'account', { get: () => window.__originalQueueController.account });
      localWorkspace.controller = wrapped;
      await localWorkspace.controller.enqueue({ date, km: 1.23, shoe_id: shoeId }, identity);
    }, { date, shoeId: shoe.id, identity: queuedIdentity });
    await otherPage.evaluate(() => localWorkspace.controller.flush());
    await page.waitForFunction(() => runController.state.rows.some(row => row.km === 1.23));
    assert.equal(await page.locator('#run-km').inputValue(), '42', 'cross-tab refresh preserves unsent input');
    const manualRun = await api(a.token, '/runs', { date, km: 1.24, shoe_id: shoe.id });
    await page.evaluate(() => syncWorkspace({ manual: true }));
    assert.equal(await page.evaluate(id => runController.state.rows.some(row => row.id === id), manualRun.id), true, 'manual empty sync still reloads cloud');
    await page.bringToFront();
    const foregroundRun = await api(a.token, '/runs', { date, km: 1.25, shoe_id: shoe.id });
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await page.waitForFunction(id => runController.state.rows.some(row => row.id === id), foregroundRun.id);
    assert.equal(await page.locator('#run-km').inputValue(), '42');
    await page.evaluate(() => { localWorkspace.controller = window.__originalQueueController; });
    await otherPage.close();
    assert.deepEqual(errors, []);
    console.log(`PASS ${browser.browserType().name()} SPEC-027: durable drafts, account isolation, offline restart/sync, recovery and deduplicated restore`);
  } catch (error) { await saveFailure(context, page, 'workspace', error); throw error; }
  finally { try { await closeBrowser(context); } finally { origin.closeAllConnections(); await new Promise(resolve => origin.close(resolve)); } }
};
