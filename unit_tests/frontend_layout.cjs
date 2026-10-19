// Browser regression check: node unit_tests/frontend_layout.cjs
// Requires Playwright with WebKit and Chromium (or PLAYWRIGHT_CHROMIUM_CHANNEL=msedge).
// Optional LAYOUT_SCREENSHOT_DIR saves the populated mobile pages for visual review.
const { chromium, webkit } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function selectTab(page, name) {
  const toggle = page.locator('.mobile-menu-toggle');
  if (await toggle.isVisible()) {
    if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
    assert.equal(await page.locator('.tab:visible').count(), 6, 'expanded menu exposes all destinations');
    await assertLayout(page, 'expanded mobile menu');
  }
  await page.locator(`.tab[data-tab="${name}"]`).click();
  if (await toggle.isVisible()) {
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false', 'selection closes mobile menu');
    assert.equal(await page.locator('.tab:visible').count(), 0, 'closed mobile menu hides destinations');
    const label = await page.locator(`.tab[data-tab="${name}"] > span:last-child`).textContent();
    assert.equal(await page.locator('#mobile-page-label').textContent(), label);
  }
}

async function assertLayout(page, label) {
  // Chart.js resizes via ResizeObserver after the viewport changes. Wait for
  // the observable result instead of assuming a fixed 100 ms is enough on CI.
  await page.waitForFunction(() => Object.values(chartInstances).every(chart =>
    !chart.canvas.getClientRects().length || chart.width <= chart.canvas.parentElement.clientWidth + 1
  ), null, { timeout: 5000 });
  const issues = await page.evaluate(() => {
    const problems = [];
    const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
    if (document.documentElement.scrollWidth > innerWidth + 1) problems.push('page overflow');
    for (const e of document.querySelectorAll('.form-group input, .form-group select, .form-group textarea')) {
      if (!visible(e)) continue;
      const box = e.getBoundingClientRect(), parent = e.parentElement.getBoundingClientRect();
      if (box.left < parent.left - 1 || box.right > parent.right + 1) {
        const identity = e.id || `${e.type}:${e.value || e.name || 'unnamed'}`;
        problems.push(`control exceeds field: ${identity}`);
      }
      if (innerWidth <= 760 && e.type === 'date' && e.closest('.form-row, .run-entry-grid')) {
        const grid = e.closest('.form-row, .run-entry-grid').getBoundingClientRect();
        if (box.width < grid.width - 2) problems.push(`mobile date field needs a full row: ${e.id}`);
      }
    }
    for (const grid of document.querySelectorAll('.run-entry-grid, .form-row, .agent-input-area, .agent-config')) {
      if (!visible(grid)) continue;
      const children = [...grid.children].filter(visible);
      for (let i = 0; i < children.length; i++) for (let j = i + 1; j < children.length; j++) {
        const a = children[i].getBoundingClientRect(), b = children[j].getBoundingClientRect();
        if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
            Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1) problems.push('overlapping fields');
      }
    }
    for (const tab of document.querySelectorAll('.tab')) {
      if (!visible(tab)) continue;
      const box = tab.getBoundingClientRect();
      if (box.left < 0 || box.right > innerWidth + 1 || tab.scrollWidth > tab.clientWidth + 1) problems.push('clipped tab');
    }
    const sidebar = document.querySelector('.app-sidebar');
    const workspace = document.querySelector('.app-workspace');
    if (visible(sidebar) && visible(workspace)) {
      const sidebarBox = sidebar.getBoundingClientRect(), workspaceBox = workspace.getBoundingClientRect();
      if (innerWidth > 800 && workspaceBox.left < sidebarBox.right - 1) problems.push('workspace does not follow sidebar');
      if (innerWidth <= 800 && workspaceBox.top < sidebarBox.bottom - 1) problems.push('mobile workspace overlaps navigation');
      if (innerWidth <= 800 && !document.getElementById('sidebar-menu').classList.contains('menu-open') && sidebarBox.height > 88) problems.push('collapsed mobile header is too tall');
      if (innerWidth <= 800 && (parseFloat(getComputedStyle(workspace).paddingLeft) < 12 || parseFloat(getComputedStyle(workspace).paddingRight) < 12)) problems.push('mobile content needs side gutters');
    }
    const metrics = document.querySelector('.run-metrics');
    if (visible(metrics)) {
      const cards = [...metrics.querySelectorAll('#run-stats > .card, .insight-grid > .insight-card')];
      if (cards.length === 6) {
        const boxes = cards.map(card => card.getBoundingClientRect());
        if (innerWidth <= 800) {
          for (let row = 0; row < 3; row++) {
            const [left, right] = boxes.slice(row * 2, row * 2 + 2);
            if (Math.abs(left.top - right.top) > 1 || Math.abs(left.bottom - right.bottom) > 1) problems.push(`run metrics row ${row + 1} is not aligned`);
            if (Math.abs(left.width - right.width) > 1 || left.right >= right.left) problems.push('run metrics need two equal columns');
            if (Math.abs(left.left - boxes[0].left) > 1 || Math.abs(right.left - boxes[1].left) > 1) problems.push('run metrics columns do not line up');
            if (row > 0 && left.top <= boxes[row * 2 - 2].bottom) problems.push('run metrics rows overlap');
          }
          for (const card of cards) if (card.scrollWidth > card.clientWidth + 1) problems.push('run metric text overflows');
          for (const alert of metrics.querySelectorAll('.insight-alerts')) {
            const box = alert.getBoundingClientRect();
            if (Math.abs(box.left - boxes[0].left) > 1 || Math.abs(box.right - boxes[1].right) > 1 || box.top < boxes[5].bottom) problems.push('run alerts must follow all six cards at full width');
          }
        } else {
          for (const start of [0, 3]) if (boxes.slice(start, start + 3).some(box => Math.abs(box.top - boxes[start].top) > 1)) problems.push('desktop run metrics must keep three columns');
        }
      }
    }
    for (const modal of document.querySelectorAll('.modal-overlay.active .modal')) {
      const box = modal.getBoundingClientRect();
      if (box.left < 0 || box.right > innerWidth + 1 || box.top < 0 || box.bottom > innerHeight + 1 ||
          modal.scrollWidth > modal.clientWidth + 1) problems.push('modal overflow');
    }
    for (const chart of Object.values(chartInstances)) {
      if (!visible(chart.canvas)) continue;
      if (chart.width > chart.canvas.parentElement.clientWidth + 1) problems.push(`canvas overflow: ${chart.canvas.id}`);
      if (chart.chartArea.width < 100 || chart.chartArea.height < 100) problems.push(`squeezed plot: ${chart.canvas.id}`);
    }
    return problems;
  });
  assert.deepEqual(issues, [], label);
}

async function run(engine, name) {
  const browser = await engine.launch({ headless: true,
    ...(name === 'chromium' && process.env.PLAYWRIGHT_CHROMIUM_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHROMIUM_CHANNEL } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: 'zh-TW' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('http://layout.test/**', async route => {
      const url = new URL(route.request().url());
      const relative = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      const asset = path.resolve(__dirname, '../frontend', relative);
      const frontendRoot = path.resolve(__dirname, '../frontend');
      if (asset !== frontendRoot && !asset.startsWith(frontendRoot + path.sep)) {
        return route.abort();
      }
      const contentTypes = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css',
        '.json': 'application/json', '.webmanifest': 'application/manifest+json',
        '.svg': 'image/svg+xml', '.png': 'image/png' };
      if (relative === 'app-boot.js') await new Promise(resolve => setTimeout(resolve, 250));
      return route.fulfill({ contentType: contentTypes[path.extname(asset)] || 'application/octet-stream',
        body: fs.readFileSync(asset) });
    });
    const navigation = page.goto('http://layout.test');
    await page.locator('#app-boot').waitFor({ state: 'visible' });
    assert.match(await page.locator('#app-boot-message').textContent(), /正在準備應用程式/);
    await navigation;
    await page.waitForFunction(() => typeof Chart !== 'undefined');
    await page.evaluate(() => {
      Chart.defaults.animation = false;
      document.querySelector('#auth-view').style.display = 'none';
      document.querySelector('#app-view').style.display = '';
      document.querySelector('#user-label').textContent = 'runner_with_a_very_long_username';
      shoes = Array.from({ length: 8 }, (_, i) => ({ id: i + 1, brand: 'Mizuno',
        model: i === 0 ? 'Wave Rider 29 非常長的鞋款名稱' : `非常長的鞋款名稱 Very long running shoe model ${i}`,
        date: '2026-01-01', price: 4000, orig_price: 5000, mileage: 120 + i * 10,
        expected_mileage: 800, monthly_km: 80, category: 'Daily', size: 'US 9' }));
      retiredShoes = [{ ...shoes[0], id: 20, is_retired: true }];
      runs = shoes.map((shoe, i) => ({ id: i + 1, shoe_id: shoe.id, date: `2026-09-${String(i + 1).padStart(2, '0')}`, km: 18.67, source: 'manual' }));
      yearlyRunsCache.set(2026, runs);
      monthlyMileages = Array.from({ length: 12 }, (_, i) => ({ id: i + 1, year: 2026, month: i + 1, km: 120 + i }));
      monthlySpending = Array.from({ length: 12 }, (_, i) => ({ year: 2026, month: i + 1, total_paid: 4000, total_orig: 5000 }));
      document.querySelector('#run-month').value = '2026-09';
      document.querySelector('#agent-model').innerHTML = '<option>Very long model provider and model name</option>';
      document.querySelector('#report-model').innerHTML = '<option>Very long model provider and model name</option>';
      document.querySelector('#shoe-analysis-content').innerHTML = '<div class="shoe-analysis-grid">' +
        ['627.62 km', '87 次', '61.9 / 222.7 km', '2026/10/01', '78.5%', '2026/12/12'].map((value, i) =>
          '<div class="insight-card"><div class="insight-card-label">指標 ' + i + '</div><div class="insight-card-value">' + value + '</div><div class="insight-card-sub">長內容測試</div></div>').join('') +
        '</div><div class="shoe-analysis-chart"></div>';
      document.querySelector('#agent-messages').innerHTML += '<div class="agent-message bot"><div class="agent-msg-content"><p>' + 'long-message'.repeat(40) + '</p><pre>' + 'code'.repeat(100) + '</pre><table><tr><td>' + 'wide-table'.repeat(50) + '</td></tr></table></div></div>';
      document.querySelector('#strava-mapping').innerHTML = '<div class="strava-group"><div>Very long imported shoe name from Strava</div><select><option>Very long matching running shoe name</option></select></div>';
      document.querySelectorAll('input[type="date"]').forEach(e => { e.value = '2026-09-06'; });
      render();
      window.layoutAnalytics = {
        comparison: { label: '較上月同期', delta_km: -23.45, through_day: 19, previous_km: 80.52 },
        recent_7_days: { km: 6.4, delta_km: -25.72 },
        goal: { active: true, start_year: 2026, month_state: 'current', month_achievement_percent: 45.7, pace_delta_km: -19.54, remaining_days: 12, required_daily_km: 5.66 },
        forecast: { state: 'current', projected_month_km: 93.11 },
        alerts: [{ severity: 'warning', message: 'Wave Rider 29 已使用 82.2% 預期壽命' }],
      };
      renderDashboardInsights(window.layoutAnalytics);
    });
    const screenshots = process.env.LAYOUT_SCREENSHOT_DIR;
    if (screenshots) fs.mkdirSync(screenshots, { recursive: true });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => applyTheme(theme), theme);
      for (const [width, height] of [[320, 740], [375, 812], [390, 844], [430, 932], [844, 390], [768, 1024], [1440, 900]]) {
        await page.setViewportSize({ width, height });
        for (const tab of ['runs', 'shoes', 'monthly', 'spending', 'agent', 'report']) {
          await selectTab(page, tab);
          await page.waitForTimeout(100);
          await assertLayout(page, `${name} ${theme} ${width} ${tab}`);
          const expected = { runs: 1, shoes: 4, monthly: 3, spending: 2, agent: 0, report: 0 }[tab];
          assert.equal(await page.locator('.tab-panel.active canvas').count(), expected);
          assert.equal(await page.evaluate(() => Object.values(chartInstances).filter(c => c.canvas.getClientRects().length).length), expected, 'all charts initialized with data');
          await page.locator('.tab-panel.active .table-wrap').evaluateAll(wrappers => wrappers.forEach(wrapper => {
            wrapper.scrollLeft = wrapper.scrollWidth;
            if (wrapper.scrollWidth > wrapper.clientWidth + 1 && wrapper.scrollLeft === 0) throw Error('wide table cannot scroll');
            wrapper.scrollLeft = 0;
          }));
          if (screenshots && width === 390) await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-${tab}.png`), fullPage: true });
          if (screenshots && width === 390 && tab === 'runs') {
            await page.locator('.run-metrics').screenshot({ path: path.join(screenshots, `${name}-${theme}-run-metrics.png`) });
            await page.evaluate(() => window.scrollTo(0, 0));
            await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-runs-top.png`) });
            await page.locator('.mobile-menu-toggle').click();
            await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-mobile-menu.png`) });
            await page.locator('.mobile-menu-toggle').click();
          }
          if (screenshots && width === 1440 && tab === 'runs') {
            await page.evaluate(() => window.scrollTo(0, 0));
            await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-runs-desktop.png`) });
          }
        }
        await selectTab(page, 'shoes');
        assert.equal(await page.locator('#chart-value-legend').count(), 0, 'monthly share legend is removed');
        const pairedHeights = await page.locator('#chart-retire, #chart-value').evaluateAll(canvases =>
          canvases.map(canvas => canvas.closest('.chart-box').getBoundingClientRect().height));
        assert.ok(Math.abs(pairedHeights[0] - pairedHeights[1]) <= 1, 'retirement and monthly share cards have equal heights');
        for (const id of await page.locator('.modal-overlay').evaluateAll(es => es.map(e => e.id))) {
          await page.evaluate(id => document.getElementById(id).classList.add('active'), id);
          await assertLayout(page, `${name} ${theme} ${width} ${id}`);
          if (screenshots && width === 390) await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-${id}.png`) });
          await page.evaluate(id => document.getElementById(id).classList.remove('active'), id);
        }
        console.log(`PASS ${name} ${theme} ${width}x${height}: all tabs, populated charts, controls and dialogs`);
      }
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await selectTab(page, 'runs');
    for (const message of ['<div class="insight-card">分析載入中…</div>', '<div class="insight-alert warning">進階分析暫時無法載入</div>']) {
      await page.evaluate(message => { document.getElementById('dashboard-insights').innerHTML = message; }, message);
      const widths = await page.evaluate(() => ({
        grid: document.querySelector('.run-metrics').clientWidth,
        message: document.querySelector('#dashboard-insights > div').getBoundingClientRect().width,
      }));
      assert.ok(Math.abs(widths.grid - widths.message) <= 1, 'analytics loading and error states span both columns');
      await assertLayout(page, `${name} analytics message`);
    }
    await page.evaluate(() => renderDashboardInsights(window.layoutAnalytics));
    await assertLayout(page, `${name} analytics recovery`);
    await page.evaluate(() => { shoes = []; retiredShoes = []; runs = []; monthlyMileages = []; monthlySpending = []; render(); });
    for (const tab of ['runs', 'shoes', 'monthly', 'spending', 'report']) {
      await selectTab(page, tab);
      await page.waitForTimeout(100);
      await assertLayout(page, `${name} empty ${tab}`);
    }
    await page.setViewportSize({ width: 320, height: 740 });
    await page.evaluate(() => { document.querySelector('#app-view').style.display = 'none'; document.querySelector('#auth-view').style.display = 'block'; });
    for (const action of ['showLoginForm', 'showRegisterForm', 'showChangeForm']) {
      await page.evaluate(action => window[action](), action);
      await assertLayout(page, `${name} ${action}`);
    }
    assert.deepEqual(errors, [], 'browser JavaScript errors');
  } finally { await browser.close(); }
}
(async () => { await run(webkit, 'webkit'); await run(chromium, 'chromium'); })().catch(error => { console.error(error); process.exitCode = 1; });
