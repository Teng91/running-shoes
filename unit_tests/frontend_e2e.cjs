// Real browser flow against FastAPI. The database always lives in a fresh OS temp directory.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

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
  let browser;
  try {
    assert.equal(path.dirname(databasePath), tempRoot, 'E2E database must be inside its temp directory');
    await waitForServer(baseUrl, server, logs);
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ locale: 'zh-TW' });
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    page.on('dialog', dialog => dialog.accept());

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
    await page.locator('#f-brand').fill('E2E Brand');
    await page.locator('#f-model').fill('Browser Runner');
    await page.locator('#f-date').fill(today);
    await page.locator('#f-size').fill('US 9');
    await page.locator('#f-price').fill('2500');
    await page.locator('#f-orig').fill('4000');
    await page.locator('#f-expected').fill('800');
    await page.locator('#modal').getByRole('button', { name: '儲存' }).click();
    await page.locator('#modal').waitFor({ state: 'hidden' });
    await page.locator('#shoe-table').getByText('Browser Runner', { exact: true }).waitFor();

    const shoeRow = page.locator('#shoe-table tr').filter({ hasText: 'Browser Runner' });
    await shoeRow.getByRole('button', { name: '編輯' }).click();
    await page.locator('#f-model').fill('Browser Runner v2');
    await page.locator('#modal').getByRole('button', { name: '儲存' }).click();
    await page.locator('#shoe-table').getByText('Browser Runner v2', { exact: true }).waitFor();

    await page.locator('.tab[data-tab="runs"]').click();
    await page.locator('#run-date').fill(today);
    await page.locator('#run-km').fill('5.5');
    await page.locator('#run-shoe').selectOption({ label: 'E2E Brand Browser Runner v2' });
    await page.locator('#add-run-btn').click();
    await page.locator('#run-table').getByText('5.50 km', { exact: true }).waitFor();

    const runRow = page.locator('#run-table tr').filter({ hasText: '5.50 km' });
    await runRow.getByRole('button', { name: '編輯' }).click();
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

    await page.locator('#run-table tr').filter({ hasText: '7.25 km' }).getByRole('button', { name: '編輯' }).click();
    await page.locator('#run-modal').getByRole('button', { name: '刪除' }).click();
    await page.locator('#run-table').getByText('7.25 km', { exact: true }).waitFor({ state: 'detached' });

    await page.locator('.tab[data-tab="shoes"]').click();
    const updatedShoeRow = page.locator('#shoe-table tr').filter({ hasText: 'Browser Runner v2' });
    await updatedShoeRow.getByRole('button', { name: '編輯' }).click();
    await page.locator('#modal').getByRole('button', { name: '刪除' }).click();
    await page.locator('#shoe-table').getByText('Browser Runner v2', { exact: true }).waitFor({ state: 'detached' });

    assert.deepEqual(pageErrors, [], 'browser JavaScript errors');
    assert.ok(fs.existsSync(databasePath), 'FastAPI used the isolated temporary database');
    console.log('PASS Chromium: registration, login, shoe CRUD, run CRUD, and persistence');
  } catch (error) {
    error.message += `\nFastAPI log:\n${logs.join('')}`;
    throw error;
  } finally {
    if (browser) await browser.close();
    await stopProcess(server);
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
