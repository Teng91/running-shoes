// Real browser flow against FastAPI. The database always lives in a fresh OS temp directory.
const { chromium, webkit } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn, execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { startArtifacts, saveFailure, closeBrowser, withDeadline } = require('../scripts/browser_artifacts.cjs');
const checkSessionIsolation = require('./frontend_sessions.cjs');
const checkFrontendSafety = require('./frontend_safety.cjs');
const checkConsistency = require('./frontend_consistency.cjs');
const checkReliability = require('./frontend_reliability.cjs');
const checkDrafts = require('./frontend_drafts.cjs');
const checkStravaOwnership = require('./frontend_strava_ownership.cjs');
const checkWorkspace = require('./frontend_workspace.cjs');
const checkResourceEditing = require('./frontend_resource_editing.cjs');

const projectRoot = path.resolve(__dirname, '..');

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

async function waitForServer(url, processHandle, logs) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (processHandle.exitCode !== null) {
      throw new Error(`FastAPI exited before startup (${processHandle.exitCode})\n${logs.join('')}`);
    }
    try {
      const response = await fetch(`${url}/health/ready`);
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error(`FastAPI startup timed out\n${logs.join('')}`);
}

async function stopProcess(processHandle) {
  if (processHandle.exitCode !== null) return;
  processHandle.kill('SIGTERM');
  await Promise.race([
    new Promise(resolve => processHandle.once('exit', resolve)),
    new Promise(resolve => setTimeout(resolve, 5_000)),
  ]);
  if (processHandle.exitCode === null) processHandle.kill('SIGKILL');
}

async function assertPurchaseDetails(page, status) {
  await page.locator('.tab[data-tab="spending"]').click();
  const row = page.locator('#spending-table tr').filter({ hasText: 'Browser Runner v2' });
  await row.getByText('US 9.5/27.5cm', { exact: true }).waitFor();
  await row.getByText(status, { exact: true }).waitFor();
  assert.equal(await row.locator('td').count(), 9);
  assert.equal(await row.locator('td').nth(4).textContent(), '$2,800');
  assert.equal(await row.locator('td').nth(5).textContent(), '$5,000');
  assert.equal(await row.locator('td').nth(6).textContent(), '56.0%');
  assert.equal(await row.locator('td').nth(8).textContent(), status);
}

async function run() {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'running-shoes-e2e-'));
  const databasePath = path.join(tempRoot, 'shoes.db');
  const python = process.env.PROJECT_PYTHON || (process.platform === 'win32'
    ? path.join(projectRoot, 'venv', 'Scripts', 'python.exe')
    : path.join(projectRoot, 'venv', 'bin', 'python'));
  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const logs = [];
  const server = spawn(python, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: projectRoot,
    env: {
      ...process.env,
      DB_DIR: tempRoot,
      SEED_DATA: 'false',
      ENVIRONMENT: 'test',
      SECRET_KEY: 'browser-e2e-only-secret-not-for-production',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.stdout.on('data', chunk => logs.push(chunk.toString()));
  server.stderr.on('data', chunk => logs.push(chunk.toString()));
  let browser, page;
  try {
    assert.equal(path.dirname(databasePath), tempRoot, 'E2E database must be inside its temp directory');
    await waitForServer(baseUrl, server, logs);
    browser = await chromium.launch({ headless: true, timeout: 30000 });
    page = await browser.newPage({ locale: 'zh-TW' });
    await startArtifacts(page.context());
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    page.on('dialog', dialog => dialog.accept());

    await withDeadline(async () => {
      const suffix = `${Date.now()}-${process.pid}`;
      const username = `e2e-${suffix}`;
      const password = 'e2e-pass-1234';
      await page.goto(baseUrl);
      const today = await page.evaluate(() => localDateISO());

      await page.getByRole('link', { name: '註冊', exact: true }).click();
      await page.locator('#reg-username').fill(username);
      await page.locator('#reg-password').fill(password);
      await page.locator('#reg-password2').fill(password);
      await page.locator('#register-form').getByRole('button', { name: '註冊' }).click();
      await page.locator('#app-view').waitFor({ state: 'visible' });
      await assert.doesNotReject(() => page.locator('#user-label').waitFor({ state: 'visible' }));
      assert.equal(await page.locator('#user-label').textContent(), username);

      await page.locator('.tab[data-tab="shoes"]').click();
      await page.getByRole('button', { name: '+ 新增跑鞋' }).click();
      await page.locator('#f-nickname').fill('Morning pair');
      await page.locator('#f-brand').fill('E2E Brand');
      await page.locator('#f-model').fill('Browser Runner');
      await page.locator('#f-date').fill(today);
      await page.locator('#f-size').fill('US 9');
      await page.locator('#f-price').fill('2500');
      await page.locator('#f-orig').fill('4000');
      await page.locator('#f-mileage').fill('40');
      await page.locator('#f-expected').fill('800');
      await page.locator('#modal').getByRole('button', { name: '儲存' }).click();
      await page.locator('#modal').waitFor({ state: 'hidden' });
      await page.locator('#shoe-table').getByText('Browser Runner', { exact: true }).waitFor();

      const shoeRow = page.locator('#shoe-table tr').filter({ hasText: 'Browser Runner' });
      await shoeRow.getByRole('button', { name: '編輯' }).click();
      await page.locator('#f-model').fill('Browser Runner v2');
      await page.locator('#f-size').fill('US 9.5/27.5cm');
      await page.locator('#f-price').fill('2800');
      await page.locator('#f-orig').fill('5000');
      await page.locator('#modal').getByRole('button', { name: '儲存' }).click();
      await page.locator('#shoe-table').getByText('Browser Runner v2', { exact: true }).waitFor();
      assert.equal(await page.locator('#shoe-table tr').first().locator('td').count(), 12);
      assert.equal(await page.locator('#shoe-table tr').first().locator('td').nth(3).textContent(), '40', 'editing purchase details preserves existing mileage');
      assert.equal(await page.locator('#shoe-table').getByText('US 9.5/27.5cm', { exact: true }).count(), 0);
      await assertPurchaseDetails(page, '使用中');

      await page.locator('.tab[data-tab="runs"]').click();
      await page.locator('#run-date').fill(today);
      await page.locator('#run-km').fill('5.5');
      const shoeOption = page.locator('#run-shoe option').filter({ hasText: 'Morning pair' });
      assert.equal(await shoeOption.textContent(), `Morning pair · E2E Brand Browser Runner v2 · ${today}`);
      await page.locator('#run-shoe').selectOption(await shoeOption.getAttribute('value'));
      await page.locator('#add-run-btn').click();
      await page.locator('#run-table').getByText('5.50 km', { exact: true }).waitFor();

      const runRow = page.locator('#run-table tr').filter({ hasText: '5.50 km' });
      await runRow.getByRole('button', { name: '編輯' }).click();
      await page.locator('#edit-run-km').fill('7.25');
      await page.evaluate(async () => {
        const run = runController.state.rows.find(item => item.id === runController.editor.id);
        await apiPut('/runs/' + run.id, { km: 6.25, expected_version: run.version });
        await loadData();
      });
      await page.locator('#run-modal').getByRole('button', { name: '儲存' }).click();
      await page.getByText('跑步紀錄已被更新，請重新載入後再編輯', { exact: true }).waitFor();
      assert.equal(await page.locator('#edit-run-km').inputValue(), '7.25', 'conflict preserves the draft');
      assert.equal(await page.evaluate(async () => (await apiGet('/runs'))[0].km), 6.25, 'stale form did not overwrite newer data');
      await page.evaluate(() => closeRunModal());
      await page.locator('#run-table tr').filter({ hasText: '6.25 km' }).getByRole('button', { name: '編輯' }).click();
      await page.locator('#edit-run-km').fill('7.25');
      await page.locator('#run-modal').getByRole('button', { name: '儲存' }).click();
      await page.locator('#run-table').getByText('7.25 km', { exact: true }).waitFor();

      await page.getByRole('button', { name: '登出' }).click();
      await page.locator('#login-form').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#login-username').inputValue(), '', 'logout clears the previous username');
      assert.equal(await page.locator('#login-password').inputValue(), '', 'logout clears the previous password');
      await page.locator('#login-username').fill(username);
      await page.locator('#login-password').fill(password);
      await page.locator('#login-form').getByRole('button', { name: '登入' }).click();
      await page.locator('#run-table').getByText('7.25 km', { exact: true }).waitFor();
      await assertPurchaseDetails(page, '使用中');
      await page.locator('.tab[data-tab="runs"]').click();

      await page.locator('#run-table tr').filter({ hasText: '7.25 km' }).getByRole('button', { name: '編輯' }).click();
      await page.locator('#run-modal').getByRole('button', { name: '刪除' }).click();
      await page.locator('#run-table').getByText('7.25 km', { exact: true }).waitFor({ state: 'detached' });

      await page.locator('.tab[data-tab="shoes"]').click();
      const updatedShoeRow = page.locator('#shoe-table tr').filter({ hasText: 'Browser Runner v2' });
      await updatedShoeRow.getByRole('button', { name: '編輯' }).click();
      await page.locator('#btn-move').click();
      await page.locator('#retired-table').getByText('Browser Runner v2', { exact: true }).waitFor();
      assert.equal(await page.locator('#retired-table tr').first().locator('td').count(), 10);
      await assertPurchaseDetails(page, '已退役');
      await page.locator('.tab[data-tab="shoes"]').click();
      await page.locator('#retired-table tr').filter({ hasText: 'Browser Runner v2' }).getByRole('button', { name: '編輯' }).click();
      await page.locator('#modal').getByRole('button', { name: '刪除' }).click();
      await page.locator('#retired-table').getByText('Browser Runner v2', { exact: true }).waitFor({ state: 'detached' });
      await page.locator('.tab[data-tab="spending"]').click();
      await page.locator('#spending-table').getByText('Browser Runner v2', { exact: true }).waitFor({ state: 'detached' });

      assert.deepEqual(pageErrors, [], 'browser JavaScript errors');
      assert.ok(fs.existsSync(databasePath), 'FastAPI used the isolated temporary database');
      console.log('PASS Chromium: registration, login, shoe CRUD, run CRUD, and persistence');
    }, 90000, 'Chromium real CRUD');
    await withDeadline(() => checkSessionIsolation(browser, baseUrl), 60000, 'browser checkSessionIsolation');
    await withDeadline(() => checkFrontendSafety(browser, baseUrl), 60000, 'browser checkFrontendSafety');
    await withDeadline(() => checkConsistency(browser, baseUrl), 60000, 'browser checkConsistency');
    await withDeadline(() => checkReliability(browser, baseUrl), 60000, 'browser checkReliability');
    await withDeadline(() => checkDrafts(browser, baseUrl), 60000, 'browser checkDrafts');
    await withDeadline(() => checkStravaOwnership(browser, baseUrl), 60000, 'browser checkStravaOwnership');
    await withDeadline(() => checkResourceEditing(browser, baseUrl), 60000, 'browser checkResourceEditing');
    await withDeadline(() => checkWorkspace(browser, baseUrl), 120000, 'Chromium recoverable workspace');
    const safari = await webkit.launch({ headless: true, timeout: 30000 });
    try {
      await withDeadline(() => checkSessionIsolation(safari, baseUrl), 60000, 'safari checkSessionIsolation');
      await withDeadline(() => checkFrontendSafety(safari, baseUrl), 60000, 'safari checkFrontendSafety');
      await withDeadline(() => checkConsistency(safari, baseUrl), 60000, 'safari checkConsistency');
      await withDeadline(() => checkReliability(safari, baseUrl), 60000, 'safari checkReliability');
      await withDeadline(() => checkDrafts(safari, baseUrl), 60000, 'safari checkDrafts');
      await withDeadline(() => checkStravaOwnership(safari, baseUrl), 60000, 'safari checkStravaOwnership');
      await withDeadline(() => checkResourceEditing(safari, baseUrl), 60000, 'safari checkResourceEditing');
      await withDeadline(() => checkWorkspace(safari, baseUrl), 120000, 'WebKit recoverable workspace');
    } finally {
      await closeBrowser(null, safari);
    }
    // The same fail-closed command used after deployment runs against this real
    // FastAPI/CORS server first, with an isolated DB and anonymous browsers.
    // Keep the event loop draining Uvicorn's log pipes while the gate fetches
    // the full shell; a synchronous child can deadlock a small OS pipe buffer.
    const releaseResult = await promisify(execFile)(python, ['scripts/task.py', 'release-check', '--base-url', baseUrl], {
      cwd: projectRoot, env: process.env, timeout: 280_000, maxBuffer: 4 * 1024 * 1024,
    });
    process.stdout.write(releaseResult.stdout);
    process.stderr.write(releaseResult.stderr);
  } catch (error) {
    await saveFailure(page?.context(), page, 'crud', error);
    error.message += `\nFastAPI log:\n${logs.join('')}`;
    throw error;
  } finally {
    try { if (browser) await closeBrowser(null, browser); } finally {
      await stopProcess(server);
      fs.rmSync(tempRoot, { recursive: true, force: true });
    }
  }
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
