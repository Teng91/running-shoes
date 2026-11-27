// Browser regression check: node unit_tests/frontend_layout.cjs
// Requires Playwright with WebKit and Chromium (or PLAYWRIGHT_CHROMIUM_CHANNEL=msedge).
// Optional LAYOUT_SCREENSHOT_DIR saves the populated mobile pages for visual review.
const { chromium, webkit } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { startArtifacts, saveFailure, closeBrowser, withDeadline, trackCspViolations } = require('../scripts/browser_artifacts.cjs');

async function selectTab(page, name) {
  const toggle = page.locator('.mobile-menu-toggle');
  // SPEC-042: the monthly report is reached through the AI destination's switch.
  const destination = name === 'report' ? 'agent' : name;
  if (await toggle.isVisible()) {
    // SPEC-040: phones keep every destination in a fixed bottom tab bar; the menu holds account actions.
    assert.equal(await page.locator('.tab:visible').count(), 4, 'bottom tab bar exposes all destinations');
    if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
    assert.equal(await page.locator('#user-label').isVisible(), true, 'expanded menu shows account actions');
    await assertLayout(page, 'expanded mobile menu');
  }
  await page.locator(`.tab[data-tab="${destination}"]`).click();
  if (name === 'report') await page.locator('#panel-agent .ai-switch-btn', { hasText: '月報' }).click();
  assert.equal(await page.locator('.tab-panel.active').getAttribute('data-panel'), name);
  if (await toggle.isVisible()) {
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false', 'selection closes mobile menu');
    assert.equal(await page.locator('.tab:visible').count(), 4, 'the tab bar stays visible');
    const bar = await page.locator('.tabs').boundingBox();
    const viewport = page.viewportSize();
    assert.ok(Math.abs(bar.y + bar.height - viewport.height) <= 1, 'tab bar is pinned to the bottom');
    const label = await page.locator(`.tab[data-tab="${destination}"] > span:last-child`).textContent();
    assert.equal(await page.locator('#mobile-page-label').textContent(), label);
  }
  // switchTab schedules lazy rendering; let it finish before opening inline editors.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function assertLayout(page, label) {
  // Chart.js resizes via ResizeObserver after the viewport changes. Wait for
  // the observable result instead of assuming a fixed 100 ms is enough on CI.
  await page.waitForFunction(() => Object.values(chartInstances).every(chart =>
    !chart.canvas.getClientRects().length || (chart.width > 0 && chart.chartArea?.width > 0 && chart.chartArea?.height > 0 && chart.width <= chart.canvas.parentElement.clientWidth + 1)
  ), null, { timeout: 5000 });
  const issues = await page.evaluate(() => {
    const problems = [];
    const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
    if (document.documentElement.scrollWidth > innerWidth + 1) {
      const overflowing = [...document.querySelectorAll('body *')].filter(node => visible(node) && !node.closest('.table-wrap, pre') && (node.getBoundingClientRect().right > innerWidth + 1 || node.getBoundingClientRect().left < -1 || node.scrollWidth > node.clientWidth + 1));
      problems.push(`page overflow ${document.documentElement.scrollWidth}/${innerWidth}: ` + overflowing.slice(0, 8).map(node => node.id || node.className || node.tagName).join(', '));
    }
    for (const [id, expected] of [['shoe-table', 11], ['retired-table', 11], ['spending-table', 9]]) {
      const tbody = document.getElementById(id);
      if (!visible(tbody.closest('table'))) continue;
      const headers = [...tbody.closest('table').querySelectorAll('thead th')].map(th => th.textContent);
      if (headers.length !== expected) problems.push(`${id} header count`);
      if (id === 'spending-table') {
        if (headers.slice(3, 7).join('/') !== '尺寸/買價/原價/折數') problems.push('purchase columns missing from spending');
      } else if (['尺寸', '買價', '原價', '折數'].some(label => headers.includes(label))) {
        problems.push('purchase columns remain on shoes');
      }
      for (const row of tbody.rows) if (row.cells.length !== expected) problems.push(`${id} cells do not align with headers`);
    }
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
      // A sticky sidebar may cover already-scrolled content; compare flow origins.
      if (innerWidth <= 800 && workspaceBox.top + scrollY < sidebarBox.height - 1) problems.push('mobile workspace overlaps navigation');
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
  if (issues.length && process.env.LAYOUT_SCREENSHOT_DIR) {
    fs.mkdirSync(process.env.LAYOUT_SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: path.join(process.env.LAYOUT_SCREENSHOT_DIR, 'failed-layout.png'), fullPage: true });
  }
  assert.deepEqual(issues, [], label);
  assert.deepEqual(await page.evaluate(alignmentIssues), [], `${label}: component alignment`);
}

function alignmentIssues() {
  const issues = [];
  const visible = node => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden';
  const box = node => node.getBoundingClientRect();
  const near = (a, b) => Math.abs(a - b) <= 1;
  const controls = '.form-group input:not([type="checkbox"]):not([type="file"]), .form-group select, .year-select, .goal-settings button, .goal-heading-actions button, .agent-config select, .agent-config button, .strava-group select';
  for (const node of document.querySelectorAll(controls)) {
    if (visible(node) && !near(box(node).height, 44)) issues.push(`44px control: ${node.id || node.className} is ${box(node).height}`);
  }
  for (const input of document.querySelectorAll('.inline-input')) if (visible(input) && !near(box(input).height, innerWidth <= 760 ? 44 : 36)) issues.push('inline editor height');
  for (const form of document.querySelectorAll('.auth-box')) {
    if (!visible(form)) continue;
    const submit = form.querySelector('button[type="submit"]'), field = form.querySelector('input');
    if (!near(box(submit).height, 44) || !near(box(submit).left, box(field).left) || !near(box(submit).right, box(field).right)) issues.push('auth action alignment');
  }
  for (const grid of document.querySelectorAll('#summary-cards, #spending-cards')) {
    if (!visible(grid)) continue;
    const columns = innerWidth > 1100 ? 3 : 2;
    if (getComputedStyle(grid).gridTemplateColumns.split(' ').length !== columns) issues.push('summary cards need balanced columns');
    const cards = [...grid.children];
    for (let i = 0; i < cards.length; i += columns) {
      const row = cards.slice(i, i + columns);
      if (row.some(card => !near(box(card).top, box(row[0]).top) || !near(box(card).bottom, box(row[0]).bottom))) issues.push('summary card row edges');
    }
  }
  for (const grid of document.querySelectorAll('.shoe-analysis-grid')) {
    if (visible(grid) && getComputedStyle(grid).gridTemplateColumns.split(' ').length !== (innerWidth <= 760 ? 2 : 3)) issues.push('shoe analysis needs balanced columns');
  }
  for (const grid of document.querySelectorAll('.form-row, .run-entry-grid')) {
    if (!visible(grid) || getComputedStyle(grid).gridTemplateColumns.split(' ').length !== 2) continue;
    const fields = [...grid.children].filter(node => visible(node) && node.classList.contains('form-group'));
    for (let i = 0; i + 1 < fields.length; i += 2) {
      // Full-width fields (shoe, category, run duration, activity type) have no partner on their row.
      if (['shoe-field', 'category-field', 'duration-field', 'activity-field'].some(name => fields[i].classList.contains(name))) continue;
      const [a, b] = [fields[i], fields[i + 1]].map(field => field.querySelector('input:not([type="checkbox"]), select'));
      if (!a || !b) continue;
      if (!near(box(a).top, box(b).top) || !near(box(a).bottom, box(b).bottom) || !near(box(a).width, box(b).width)) issues.push(`paired controls: ${a.id}/${b.id}`);
    }
  }
  for (const row of document.querySelectorAll('.modal-actions, .table-header, .agent-config')) {
    if (!visible(row)) continue;
    const buttons = [...row.querySelectorAll('button')].filter(visible);
    for (const button of buttons) {
      if (!near(box(button).height, 44)) issues.push(`44px action: ${button.id || button.textContent.trim()}`);
      if (button.scrollWidth > button.clientWidth + 1) issues.push(`clipped action: ${button.textContent.trim()}`);
    }
    for (const a of buttons) for (const b of buttons) {
      if (a === b || Math.min(box(a).bottom, box(b).bottom) - Math.max(box(a).top, box(b).top) <= 1) continue;
      if (!near(box(a).top, box(b).top) || !near(box(a).bottom, box(b).bottom)) issues.push('actions on same row are not aligned');
    }
  }
  const agent = document.querySelector('.agent-config');
  if (visible(agent)) {
    const select = box(document.getElementById('agent-model')), refresh = box(document.getElementById('agent-refresh-btn'));
    if (!near(select.top, refresh.top) || !near(select.bottom, refresh.bottom)) issues.push('agent model and refresh must share a row');
    if (innerWidth > 760) {
      const label = box(agent.querySelector('label'));
      if (!near(label.top + label.height / 2, select.top + select.height / 2)) issues.push('agent label center');
    }
    const input = box(document.getElementById('agent-input')), send = box(document.getElementById('agent-send-btn'));
    if (!near(input.bottom, send.bottom)) issues.push('chat composer bottom');
  }
  for (const chartGrid of document.querySelectorAll('.charts')) {
    const charts = [...chartGrid.children].filter(visible);
    for (let i = 0; i < charts.length; i++) for (let j = i + 1; j < charts.length; j++) {
      if (!near(box(charts[i]).top, box(charts[j]).top)) continue;
      const a = charts[i].querySelector('.chart-canvas, .run-calendar, .run-shoe-canvas');
      const b = charts[j].querySelector('.chart-canvas, .run-calendar, .run-shoe-canvas');
      if (a && b && !near(box(a).top, box(b).top)) issues.push('chart content start');
    }
  }
  for (const table of document.querySelectorAll('.table-wrap table')) {
    if (!visible(table)) continue;
    for (const row of table.rows) for (const cell of row.cells) {
      if (cell.classList.contains('numeric') && getComputedStyle(cell).textAlign !== 'right') issues.push('numeric cell must align right');
    }
    for (const row of table.tBodies[0]?.rows || []) {
      if (row.cells.length !== table.rows[0].cells.length) continue;
      for (let i = 0; i < row.cells.length; i++) {
        if (row.cells[i].classList.contains('numeric') !== table.rows[0].cells[i].classList.contains('numeric')) issues.push('numeric header/body mismatch');
        if (row.cells[i].classList.contains('numeric') && getComputedStyle(row.cells[i]).paddingRight !== getComputedStyle(table.rows[0].cells[i]).paddingRight) issues.push('numeric header/body right edge');
      }
      const buttons = [...row.querySelectorAll('button')];
      if (buttons.some(button => !near(box(button).height, innerWidth <= 760 ? 44 : 36))) issues.push('table action density');
    }
  }
  for (const [id, numeric] of Object.entries({ 'shoe-table': [3,4,5,6,7], 'retired-table': [3,4,5,6,7], 'run-table': [1], 'spending-table': [4,5,6] })) {
    const table = document.getElementById(id).closest('table');
    if (visible(table) && numeric.some(index => !table.rows[0].cells[index].classList.contains('numeric'))) issues.push(`${id} numeric column contract`);
  }
  return [...new Set(issues)];
}

async function run(engine, name) {
  let browser, page;
  try {
    await withDeadline(async () => {
      browser = await engine.launch({ headless: true, timeout: 30000,
        ...(name === 'chromium' && process.env.PLAYWRIGHT_CHROMIUM_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHROMIUM_CHANNEL } : {}) });
      page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: 'zh-TW' });
      await startArtifacts(page.context());
      const cspViolations = await trackCspViolations(page.context());
      const errors = [];
      let allowBootScript;
      const bootScriptGate = new Promise(resolve => { allowBootScript = resolve; });
      page.on('pageerror', error => errors.push(error.message));
      await page.route('http://layout.test/**', async route => {
        const url = new URL(route.request().url());
        const relative = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        const asset = path.resolve(__dirname, '../frontend', relative);
        const frontendRoot = path.resolve(__dirname, '../frontend');
        if (asset !== frontendRoot && !asset.startsWith(frontendRoot + path.sep)) {
          return route.abort();
        }
        if (url.pathname === '/api/running-goal/year') {
          // SPEC-044: every month state (met, missed, current, future) in one fixture.
          const kms = [132.4, 98.6, 140.2, 125, 87.3, 151.9, 126.4, 110.8, 133.1, 45.2, 0, 0];
          return route.fulfill({ json: {
            version: 1, start_year: 2026, monthly_km: 125, yearly_km: 1500,
            year: Number(url.searchParams.get('year')), active: true, year_state: 'current', focus_month: 10,
            month_km: 45.2, month_state: 'current', month_achievement_percent: 36.2, pace_delta_km: -46.29,
            remaining_days: 8, required_daily_km: 9.98, ytd_km: 1150.9, year_achievement_percent: 76.7,
            year_remaining_km: 349.1, year_expected_km_to_date: 1212.33, year_pace_delta_km: -61.43,
            year_remaining_days: 69, required_weekly_km: 35.42, months_closed: 9, months_met: 6,
            months: kms.map((km, index) => ({ month: index + 1, km, percent: Math.round(km / 1.25 * 10) / 10,
              state: index < 9 ? 'past' : index === 9 ? 'current' : 'future', met: index < 10 && km >= 125 })),
          } });
        }
        // SPEC-075: the sign-up form asks which registration mode is active.
        if (url.pathname === '/api/auth/registration') return route.fulfill({ json: { mode: 'invite', mail_enabled: true } });
        // SPEC-077: the sidebar asks whether to show the admin entry.
        if (url.pathname === '/api/auth/me') return route.fulfill({ json: { id: 1, username: 'layout', is_admin: false, email: null } });
        if (url.pathname === '/api/runs/totals') return route.fulfill({ json: { run_count: 210, total_km: 1234.56 } });
        if (url.pathname === '/api/runs/year-summary') return route.fulfill({ json: {
          shoes: Array.from({ length: 8 }, (_, index) => ({ shoe_id: index + 1,
            monthly_km: Array.from({ length: 12 }, (_, month) => month === 8 ? 18.67 : 0) })),
        } });
        if (url.pathname === '/api/analytics/trends') {
          const year = Number(url.searchParams.get('year'));
          const days = Array.from({ length: 300 }, (_, index) => new Date(Date.UTC(year, 0, 1 + index)).toISOString().slice(0, 10));
          return route.fulfill({ json: {
            year, end_date: `${year}-10-27`, thresholds: { spike_percent: 30, spike_min_base_km: 5 },
            weekly_goal: { active: true, km: 28.77 },
            weekday: Array.from({ length: 7 }, (_, weekday) => ({ weekday, km: [180, 120, 0, 95.5, 60, 320.2, 210][weekday],
              run_days: [24, 18, 0, 15, 10, 40, 30][weekday], runs: [25, 18, 0, 16, 10, 41, 30][weekday],
              pace: [369, 364, null, 354, 370, 371, 354][weekday] })),
            daily: days.filter((_, index) => index % 3 !== 1).map((date, index) => ({ date, km: (index % 5) * 4.5 + 2 })),
            streaks: { longest_days: 12, longest_end: `${year}-05-24`, current_days: 3 },
            weekly: Array.from({ length: 16 }, (_, index) => ({
              week_start: new Date(Date.UTC(year, 6, 13 + index * 7)).toISOString().slice(0, 10),
              km: 20 + (index % 4) * 6, average_km: 26, baseline_km: 24, change_percent: index % 4 === 3 ? 42.5 : -4,
              spike: index % 4 === 3, partial: index === 15, longest_km: 8 + (index % 5) * 3.5, goal_met: index % 4 !== 0,
            })),
            cumulative: { goal_active: true, yearly_goal_km: 1500,
              actual_km: Array.from({ length: 300 }, (_, index) => index * 4.3),
              goal_km: Array.from({ length: 365 }, (_, index) => (index + 1) * 1500 / 365),
              ytd_km: 1285.7, expected_km: 1232.9, delta_km: 52.8, projected_km: 1564 },
          } });
        }
        if (url.pathname === '/api/analytics/home') return route.fulfill({ json: {
          as_of: '2026-10-27',
          suggestion: [{ shoe_id: 3, days_since_last_run: 87, remaining_km: 500, usage_percent: 37.5, near_end: false }],
        } });
        if (url.pathname === '/api/analytics/year-review') {
          const year = Number(url.searchParams.get('year'));
          return route.fulfill({ json: {
            year, end_date: `${year}-10-27`, complete: false, has_runs: true, total_km: 1285.7, run_count: 187, run_days: 170,
            active_day_percent: 56.9, average_km: 6.88, longest_streak_days: 12,
            longest_run: { date: `${year}-03-01`, km: 42.2, shoe_id: 1 }, biggest_week: { week_start: `${year}-03-02`, km: 88.8 },
            biggest_month: { month: 3, km: 301.5 }, top_shoe: { shoe_id: 2, km: 512.3, runs: 70 },
            shoes_bought: 8, shoe_spend: 32000, cost_per_km: 24.89, previous_year_km: 980.4,
            goal: { active: true, yearly_km: 1500, percent: 85.7 },
          } });
        }
        if (url.pathname === '/api/analytics/shoe-distance-mix') return route.fulfill({ json: {
          buckets: ['<5', '5–10', '10–15', '15–21', '≥21'],
          shoes: Array.from({ length: 8 }, (_, index) => ({ shoe_id: index + 1, counts: [3 + index, 8, 4, index % 3, index % 2],
            runs: 16 + index, km: 120 + index * 40, longest_km: 18 + index, average_km: 7.5 })),
        } });
        if (url.pathname === '/api/analytics/shoe-timeline') return route.fulfill({ json: {
          as_of: '2026-10-27', idle_days: 30, shoes: Array.from({ length: 8 }, (_, index) => ({
            shoe_id: index + 1, first_run_date: `2025-${String(index + 2).padStart(2, '0')}-01`,
            last_run_date: index === 2 ? '2026-08-01' : '2026-10-20', km: 120 + index * 40, run_count: 10 + index,
            shoe_km: 120 + index * 40 + (index % 2) * 12.4, other_km: (index % 2) * 12.4,
            days_since_last_run: index === 2 ? 87 : 7, idle: index === 2,
          })),
        } });
        if (url.pathname === '/api/analytics/personal-bests') {
          // SPEC-136: full cards with runners-up and a long shoe name, plus one distance without a best.
          const entry = (km, rank, seconds, date, runKm, longer) => ({ rank, seconds, pace: Math.round(seconds / km), date,
            run_km: runKm, from_longer_run: longer, shoe: 'ASICS Superblast 2（長距離與比賽日的主力鞋）' });
          return route.fulfill({ json: { as_of: '2026-10-27', top_count: 3, distances: [
            { key: '5k', label: '5K', distance_km: 5, bests: [entry(5, 1, 1350, '2026-04-03', 5.01, false),
              entry(5, 2, 1375, '2026-10-25', 16, true), entry(5, 3, 1400, '2025-12-20', 21.1, true)] },
            { key: '10k', label: '10K', distance_km: 10, bests: [entry(10, 1, 2750, '2026-10-25', 16, true),
              entry(10, 2, 2800, '2025-12-20', 21.1, true), entry(10, 3, 3120, '2026-09-14', 10.02, false)] },
            { key: '15k', label: '15K', distance_km: 15, bests: [entry(15, 1, 4125, '2026-10-25', 16, true)] },
            { key: 'half', label: '半馬', distance_km: 21.0975, bests: [] },
          ] } });
        }
        if (url.pathname === '/api/analytics/pace') {
          // SPEC-065: a populated trend whose points carry intensity zones and a goal pace.
          const days = Array.from({ length: 120 }, (_, index) => new Date(Date.UTC(2025, 6, 1 + index * 4)).toISOString().slice(0, 10));
          const zoneKeys = ['easy', 'steady', 'race', 'fast'];
          return route.fulfill({ json: {
            as_of: '2026-10-27', timed_run_count: 120, untimed_run_count: 3, goal_pace: 341,
            zones: [{ key: 'easy', label: '輕鬆', min_pace: 386, max_pace: null }, { key: 'steady', label: '穩定', min_pace: 356, max_pace: 386 },
              { key: 'race', label: '比賽配速', min_pace: 331, max_pace: 356 }, { key: 'fast', label: '更快', min_pace: null, max_pace: 331 }],
            summary: { first_date: '2025-07-01', first_90_days_pace: 388, recent_90_days_pace: 352, recent_30_days_pace: 347 },
            runs: days.map((date, index) => ({ date, km: 5 + (index % 9), pace: 320 + (index * 37) % 90, zone: zoneKeys[index % 4] })),
            rolling: days.map((date, index) => ({ date, pace: 390 - index * 0.3 })),
          } });
        }
        if (url.pathname === '/api/analytics/race') {
          const weekly = Array.from({ length: 12 }, (_, index) => ({
            week_start: new Date(Date.UTC(2026, 7, 10 + index * 7)).toISOString().slice(0, 10),
            km: 25 + (index % 4) * 5, longest_km: [10, 12.5, 16, 9.8][index % 4], partial: index === 11 }));
          return route.fulfill({ json: {
            as_of: '2026-10-27', days_left: 40, goal_pace: 341,
            goal: { version: 1, race_name: '示範城市半馬', race_date: '2026-12-13', distance_km: 21.0975, target_seconds: 7200,
              reference_distance_km: 10, reference_seconds: 3120, reference_temperature_c: 28 },
            zones: [{ key: 'easy', label: '輕鬆', min_pace: 386, max_pace: null }, { key: 'steady', label: '穩定', min_pace: 356, max_pace: 386 },
              { key: 'race', label: '比賽配速', min_pace: 331, max_pace: 356 }, { key: 'fast', label: '更快', min_pace: null, max_pace: 331 }],
            prediction: { reference_distance_km: 10, reference_seconds: 3120, reference_pace: 312, reference_temperature_c: 28,
              hot_reference: true, predicted_seconds: 6884, predicted_pace: 326, margin_seconds: 316 },
            intensity: { weeks: 8, total_seconds: 100000, untimed_runs: 1, zones: [
              { key: 'easy', label: '輕鬆', runs: 4, km: 19.9, seconds: 9100, share: 9.1 },
              { key: 'steady', label: '穩定', runs: 7, km: 60, seconds: 24800, share: 24.8 },
              { key: 'race', label: '比賽配速', runs: 15, km: 139.6, seconds: 54100, share: 54.1 },
              { key: 'fast', label: '更快', runs: 5, km: 33.9, seconds: 12000, share: 12 }] },
            long_runs: { weeks: 8, threshold_km: 15.8, target_count: 2, count: 1, runs: [{ date: '2026-10-25', km: 16, pace: 338 }],
              longest_recent: { date: '2026-10-25', km: 16, pace: 338 }, longest_ever: { date: '2025-12-20', km: 21.1, pace: 395 },
              longest_recent_percent: 76, enough: false, last_long_run_by: '2026-11-29', weekly, average_weekly_km: 31.68 },
            // SPEC-119: the weekly plan table lays out at every width.
            plan: {
            weeks_total: 12, weeks_chosen: true, default_weeks: 12, weeks_until_race: 7, start_date: '2026-09-21', started: true, baseline_km: 28.4, baseline_start: '2026-08-24', baseline_end: '2026-09-20',
            peak_km: 42, longest_planned_km: 19, long_threshold_km: 15.8, long_below_threshold: false, weeks_done: 3, weeks_past: 5,
            weeks: ['build', 'build', 'build', 'recovery', 'build', 'build', 'build', 'recovery', 'build', 'peak', 'taper', 'race'].map((phase, index) => ({
              week: index + 1, week_start: new Date(Date.UTC(2026, 8, 21 + index * 7)).toISOString().slice(0, 10), phase,
              km: phase === 'race' ? 33.7 : 28 + index, long_km: phase === 'race' ? 21.1 : 14 + (index % 3), zone_runs: { easy: 2, steady: 1, race: index % 2, fast: 0 }, quality_runs: { easy: 0, steady: phase === 'build' ? 1 : 0, race: phase === 'race' ? 0 : 1, fast: 0 },
              actual_km: index < 6 ? 25.5 + index : 0, actual_longest_km: index < 6 ? 12.4 : 0,
              adjusted: index === 5, status: ['done', 'partial', 'done', 'missed', 'done', 'current'][index] || 'upcoming' })),
          },
          } });
        }
        const contentTypes = { '.html': 'text/html', '.js': 'application/javascript', '.mjs': 'application/javascript', '.css': 'text/css',
          '.json': 'application/json', '.webmanifest': 'application/manifest+json',
          '.svg': 'image/svg+xml', '.png': 'image/png' };
        if (relative === 'app-boot.js') await bootScriptGate;
        return route.fulfill({ contentType: contentTypes[path.extname(asset)] || 'application/octet-stream',
          body: fs.readFileSync(asset) });
      });
      const navigation = page.goto('http://layout.test');
      try {
        await page.locator('#app-boot').waitFor({ state: 'visible' });
        assert.match(await page.locator('#app-boot-message').textContent(), /正在準備應用程式/);
      } finally { allowBootScript(); }
      await navigation;
      await page.waitForFunction(() => typeof Chart !== 'undefined');
      await page.locator('#app-boot').waitFor({ state: 'hidden' });
      await page.evaluate(() => {
        Chart.defaults.animation = false;
        document.querySelector('#auth-view').hidden = true;
        document.querySelector('#app-view').hidden = false;
        document.querySelector('#user-label').textContent = 'runner_with_a_very_long_username';
        // SPEC-095: fixtures enter the core data store the way loaded resources do.
        const shoes = Array.from({ length: 8 }, (_, i) => ({ id: i + 1, brand: 'Mizuno',
          model: i === 0 ? 'Wave Rider 29 非常長的鞋款名稱' : `非常長的鞋款名稱 Very long running shoe model ${i}`,
          date: '2026-01-01', price: 4000, orig_price: 5000, mileage: 120 + i * 10,
          expected_mileage: 800, monthly_km: 80, category: 'Daily', size: 'US 9',
          discount_percent: 80, cost_per_km: 33.33, expected_cost_per_km: 5,
          usage_percent: 15 + i * 1.25, remaining_mileage_km: 680 - i * 10,
          forecast_retirement_date: '2027-06-01', forecast_source: 'recent_90_days', forecast_monthly_km: 80, actual_monthly_km_90_days: 80 - i * 5 }));
        applyCoreResource('shoes', [shoes, [{ ...shoes[0], id: 20, is_retired: true }]]);
        runController.state.rows = shoes.map((shoe, i) => ({ id: i + 1, shoe_id: shoe.id, date: `2026-09-${String(i + 1).padStart(2, '0')}`, km: 18.67, source: 'manual' }));
        applyCoreResource('monthly', Array.from({ length: 12 }, (_, i) => ({ id: i + 1, year: 2026, month: i + 1, km: 120 + i })));
        applyCoreResource('spending', { total_paid: 48000, total_original: 60000, savings: 12000,
          average_discount_percent: 80, average_monthly_paid: 4000, month_span: 12,
          start_month: '2026-01', highest_month: { year: 2026, month: 1, total_paid: 4000 },
          monthly: Array.from({ length: 12 }, (_, i) => ({ year: 2026, month: i + 1, total_paid: 4000, total_orig: 5000 })) });
        document.querySelector('#run-month').value = '2026-09';
        document.querySelector('#agent-model').innerHTML = '<option>Very long model provider and model name</option>';
        document.querySelector('#report-model').innerHTML = '<option>Very long model provider and model name</option>';
        document.querySelector('#shoe-analysis-content').innerHTML = '<div class="shoe-analysis-grid">' +
          ['627.62 km', '87 次', '61.9 / 222.7 km', '2026/10/01', '78.5%', '2026/12/12'].map((value, i) =>
            '<div class="insight-card"><div class="insight-card-label">指標 ' + i + '</div><div class="insight-card-value">' + value + '</div><div class="insight-card-sub">長內容測試</div></div>').join('') +
          '</div><div class="shoe-analysis-chart"></div>';
        document.querySelector('#agent-messages').innerHTML += '<div class="agent-message bot"><div class="agent-msg-content"><p>' + 'long-message'.repeat(40) + '</p><pre>' + 'code'.repeat(100) + '</pre><table><tr><td>' + 'wide-table'.repeat(50) + '</td></tr></table></div></div>';
        addAgentMessage('user', '請幫我檢查這個月的跑步紀錄與跑鞋使用情況。');
        document.querySelector('#agent-messages').insertAdjacentHTML('beforeend', '<div class="agent-thinking">正在分析很長的訓練內容與跑鞋資料。</div><div class="agent-tools"><div class="tool-item done"><span class="tool-icon">✅</span><span class="tool-name">query_run_history</span></div><div class="tool-item failed"><span class="tool-icon">⚠️</span><span class="tool-name">web_search_' + 'very-long-query'.repeat(10) + '</span><span class="tool-detail">來源暫時無法使用</span></div></div>');
        const markdown = '# 跑步與鞋款分析\n\n> 本月穩定進步，請繼續保持。\n\n## 訓練摘要\n\n- 第一項訓練建議\n- 第二項訓練建議\n\n| 指標 | 本月 | 上月 |\n| --- | --- | --- |\n| 總里程 | 120.50 km | 100.00 km |\n\n**注意恢復**，資料僅供訓練參考。';
        const answer = addAgentMessage('bot', markdown);
        appendAgentSourceStatus(answer, { web: { status: 'live', result_count: 1, sources: [{ id: '1', title: '這是一個很長的參考資料標題', url: 'https://example.test/source' }] } }, true, true);
        addRetryButton();
        renderReport({ year: 2026, month: 9, model: 'mock', content_md: markdown, updated_at: '2026-10-01T00:00:00Z' });
        document.querySelector('#strava-mapping').innerHTML = '<div class="strava-group"><div>Very long imported shoe name from Strava</div><select><option>Very long matching running shoe name</option></select></div>';
        renderStravaImportHistory();
        document.querySelectorAll('input[type="date"]').forEach(e => { e.value = '2026-09-06'; });
        refreshPanels();
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
        for (const [width, height] of [[320, 740], [375, 812], [390, 844], [430, 932], [844, 390], [768, 1024], [800, 1024], [1024, 768], [1280, 800], [1440, 900]]) {
          await page.setViewportSize({ width, height });
          for (const tab of ['runs', 'shoes', 'monthly', 'agent', 'report']) {
            await selectTab(page, tab);
            await page.waitForTimeout(100);
            await assertLayout(page, `${name} ${theme} ${width} ${tab}`);
            const expected = { runs: 1, shoes: 8, monthly: 11, agent: 0, report: 0 }[tab];
            if (tab === 'monthly') {
              assert.equal(await page.locator('#run-heatmap .heatmap-grid .heat-cell:not(.blank)').count(), 365, 'heatmap renders every day');
              assert.equal(await page.locator('#goal-overview .goal-month').count(), 12, 'goal shows every month');
              assert.equal(await page.locator('#goal-month-select').count(), 0, 'no separate month picker');
              const columns = await page.locator('#goal-overview .goal-months').evaluate(node => getComputedStyle(node).gridTemplateColumns.split(' ').length);
              assert.equal(columns, width <= 760 || (width > 800 && width <= 940) ? 6 : 12, 'monthly goal cells wrap to two rows when narrow');
              assert.equal(await page.locator('#goal-overview .goal-month-km, #goal-overview .goal-month-name').evaluateAll(nodes => nodes.filter(node => node.scrollWidth > node.clientWidth + 1).length), 0, 'month numbers fit their cells');
              await page.locator('#goal-edit-toggle').click();
              await assertLayout(page, `${name} ${theme} ${width} goal editor`);
              if (screenshots && [390, 1440].includes(width)) await page.locator('.goal-section').screenshot({ path: path.join(screenshots, `${name}-${theme}-goal-${width}.png`) });
              await page.locator('#cancel-goal-btn').click();
              assert.equal(await page.locator('#goal-settings').isHidden(), true, 'cancel closes the goal editor');
              // SPEC-065: the race settings form shows the saved goal and lays out at every width.
              await page.waitForFunction(() => document.getElementById('race-cards').textContent.includes('1:54:44'));
              await page.locator('#race-edit-toggle').click();
              assert.equal(await page.locator('#race-target').inputValue(), '2:00:00');
              await assertLayout(page, `${name} ${theme} ${width} race editor`);
              await page.locator('#cancel-race-btn').click();
              assert.equal(await page.locator('#race-settings').isHidden(), true, 'cancel closes the race editor');
              assert.match(await page.locator('#race-cards').innerText(), /1:54:44/);
              assert.equal(await page.locator('#race-plan-table tr').count(), 12, 'the weekly plan is shown');
              // SPEC-136: personal best cards lay out at every width and hand a best to the race form.
              await page.waitForFunction(() => document.querySelectorAll('#personal-bests .pb-card').length === 3);
              assert.match(await page.locator('#personal-bests').innerText(), /22:30[\s\S]*還沒有 21\.1 km 以上/);
              if (screenshots && [390, 1440].includes(width)) await page.locator('.pb-section').screenshot({ path: path.join(screenshots, `${name}-${theme}-personal-bests-${width}.png`) });
              await page.locator('#personal-bests .pb-use').first().click();
              assert.equal(await page.locator('#race-ref-time').inputValue(), '22:30');
              await assertLayout(page, `${name} ${theme} ${width} personal best in the race form`);
              await page.locator('#cancel-race-btn').click();
              assert.equal(await page.locator('#race-ref-time').inputValue(), '52:00', 'cancel restores the saved reference');
            }
            assert.equal(await page.locator('.tab-panel.active canvas').count(), expected);
            assert.equal(await page.evaluate(() => Object.values(chartInstances).filter(c => c.canvas.getClientRects().length).length), expected, 'all charts initialized with data');
            await page.locator('.tab-panel.active .table-wrap').evaluateAll(wrappers => wrappers.forEach(wrapper => {
              wrapper.scrollLeft = wrapper.scrollWidth;
              if (wrapper.scrollWidth > wrapper.clientWidth + 1 && wrapper.scrollLeft === 0) throw Error('wide table cannot scroll');
              wrapper.scrollLeft = 0;
            }));
            if (screenshots && width === 390) await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-${tab}.png`), fullPage: true });
            if (screenshots && width === 1440) {
              await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-${tab}-desktop.png`), fullPage: true });
            }
            if (screenshots && [390, 1440].includes(width) && tab === 'agent') {
              await page.locator('#agent-messages').evaluate(node => { node.scrollTop = node.scrollHeight; });
              await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-agent-status-${width}.png`) });
              await page.locator('#agent-messages').evaluate(node => { node.scrollTop = 0; });
            }
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
            if (id === 'modal') await page.evaluate(() => shoeModal.openForCreate());
            if (id === 'run-modal') await page.evaluate(() => openRunModal(runController.state.rows[0].id));
            if (id === 'workspace-modal') await page.evaluate(() => {
              document.getElementById('workspace-owner').textContent = '目前帳號：layout-synthetic；備份會合併到此帳號。';
              const queue = document.getElementById('workspace-queue');
              queue.innerHTML = '<div class="workspace-item"><p>2026-01-02 · 180 km · 需要處理：原鞋款已刪除，請明確重新選擇鞋款後重試同步，其他草稿會保留。</p><select aria-label="重新配對鞋款"><option>請明確選擇鞋款</option><option>Very long shoe nickname · Brand Reliable Runner · 2026-01-01 · #123</option></select><button class="btn btn-edit">重新配對並重試</button><button class="btn btn-cancel">移除待同步紀錄</button></div>';
              document.getElementById('workspace-drafts').innerHTML = '<div class="workspace-item"><button class="btn btn-edit">繼續編輯 鞋款 新增草稿</button><button class="btn btn-cancel">捨棄草稿</button></div>';
              document.getElementById('restore-preview').textContent = '預計新增 123 雙鞋、12345 筆跑步；略過 12 雙鞋、345 筆跑步。預覽後資料變更，請重新預覽。';
              document.getElementById('workspace-history').innerHTML = '<div class="workspace-item"><p>2026/10/24 · 跑步 #123 · 刪除 · run.delete</p><button class="btn btn-edit">復原誤刪</button></div>';
            });
            if (id === 'shoe-analysis-modal') await page.evaluate(() => renderShoeAnalytics({
              shoe: { brand: 'Mizuno', model: 'Wave Rider 29 非常長的鞋款名稱', categories: ['Daily'], purchase_date: '2026-01-01', is_retired: false },
              lifecycle: { total_mileage_km: 627.62, usage_percent: 78.5, remaining_mileage_km: 172.38, forecast_retirement_date: '2027-06-01', forecast_source: 'recent_90_days', forecast_monthly_km: 80 },
              usage: { count: 87, km_30_days: 61.9, km_90_days: 222.7, actual_monthly_km_90_days: 74.2, first_run_date: '2026-01-01', last_run_date: '2026-10-01' },
              recent_runs: runController.state.rows.slice(0, 2), monthly_history: Array.from({ length: 12 }, (_, i) => ({ year: 2026, month: i + 1, km: 60, count: 4 })),
            }));
            await page.evaluate(id => document.getElementById(id).classList.add('active'), id);
            await assertLayout(page, `${name} ${theme} ${width} ${id}`);
            if (screenshots && [390, 1440].includes(width)) await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-${id}-${width}.png`) });
            if (id === 'modal') {
              for (const retired of [false, true]) {
                await page.evaluate(retired => shoeModal.openForEdit(retired ? coreData.retiredShoes[0] : coreData.shoes[0], retired), retired);
                assert.equal(await page.locator('#shoe-secondary-actions').isVisible(), true);
                await assertLayout(page, `${name} ${theme} ${width} shoe edit ${retired}`);
                if (screenshots && [390, 1440].includes(width)) await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-shoe-edit-${retired}-${width}.png`) });
              }
            }
            const error = page.locator(`#${id} .auth-error`).first();
            if (await error.count()) {
              await error.evaluate(node => { node.textContent = '驗證失敗：這是一段很長的錯誤訊息，請檢查輸入資料後再試一次。'; node.style.display = 'block'; });
              await assertLayout(page, `${name} ${theme} ${width} ${id} error`);
              await error.evaluate(node => { node.textContent = ''; node.style.display = ''; });
            }
            const buttons = page.locator(`#${id} .modal-actions button`);
            const disabled = await buttons.evaluateAll(nodes => nodes.map(node => node.disabled));
            await buttons.evaluateAll(nodes => nodes.forEach(node => { node.disabled = true; }));
            await assertLayout(page, `${name} ${theme} ${width} ${id} disabled`);
            await buttons.evaluateAll((nodes, states) => nodes.forEach((node, index) => { node.disabled = states[index]; }), disabled);
            // SPEC-135: Escape closes every dialog through the close function its feature registered.
            await page.keyboard.press('Escape');
            assert.equal(await page.locator(`#${id}.active`).count(), 0, `${name} ${theme} ${width} ${id} closes on Escape`);
          }
          await selectTab(page, 'shoes');
          await page.evaluate(() => inlineEditRow(inlineTableRows.get('shoe-table'), 0, 'mileage', document.querySelector('#shoe-table .editable')));
          await assertLayout(page, `${name} ${theme} ${width} shoes inline edit`);
          await page.locator('.inline-input').press('Escape');
          await page.evaluate(() => { document.getElementById('app-view').hidden = true; document.getElementById('auth-view').hidden = false; });
          for (const action of ['showLoginForm', 'showRegisterForm', 'showResetForm']) {
            await page.evaluate(action => window[action](), action);
            await assertLayout(page, `${name} ${theme} ${width} ${action}`);
            if (screenshots && [390, 1440].includes(width)) await page.screenshot({ path: path.join(screenshots, `${name}-${theme}-${action}-${width}.png`), fullPage: true });
          }
          await page.evaluate(() => { document.getElementById('app-view').hidden = false; document.getElementById('auth-view').hidden = true; });
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
      await page.evaluate(() => {
        applyCoreResource('shoes', [[], []]); applyCoreResource('monthly', []);
        applyCoreResource('spending', { ...coreData.spendingSummary, monthly: [] });
        runController.state.rows = []; refreshPanels();
      });
      for (const tab of ['runs', 'shoes', 'monthly', 'report']) {
        await selectTab(page, tab);
        await page.waitForTimeout(100);
        await assertLayout(page, `${name} empty ${tab}`);
      }
      await page.setViewportSize({ width: 320, height: 740 });
      await page.evaluate(() => { document.querySelector('#app-view').hidden = true; document.querySelector('#auth-view').hidden = false; });
      for (const action of ['showLoginForm', 'showRegisterForm', 'showResetForm']) {
        await page.evaluate(action => window[action](), action);
        await assertLayout(page, `${name} ${action}`);
      }
      assert.deepEqual(errors, [], 'browser JavaScript errors');
      assert.deepEqual(cspViolations, [], 'Content-Security-Policy violations (SPEC-054)');
    }, 300000, 'layout engine ' + name);
  } catch (error) {
    await saveFailure(page?.context(), page, 'layout-' + name, error);
    throw error;
  } finally { await closeBrowser(null, browser); }
}
(async () => { await run(webkit, 'webkit'); await run(chromium, 'chromium'); })().catch(error => { console.error(error); process.exitCode = 1; });
