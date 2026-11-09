const { runContext, test, assert, vm, extract, htmlSource, styleSource } = require('./helpers.cjs');

function elements() {
  return new Proxy({}, { get: (target, id) => target[id] ||= {
    id, value: '', textContent: '', innerHTML: '', hidden: false, dataset: {},
    style: {}, replaceChildren() { this.innerHTML = ''; }, dispatched: [],
    dispatchEvent(event) { this.dispatched.push(event.type); },
  } });
}

const shoes = [
  { id: 1, brand: 'Mizuno', model: 'Rider', nickname: '日常' },
  { id: 4, brand: 'Mizuno', model: 'Neo', nickname: '' },
  { id: 3, brand: 'PUMA', model: 'Nitro', nickname: '<b>x</b>' },
];
const retiredShoes = [{ id: 2, brand: 'Mizuno', model: 'Sky', nickname: '' }];
const esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function context(nodes, globals = {}) {
  return runContext({
    document: { getElementById: id => nodes[id], querySelector: () => ({ dataset: { panel: globals.panel || 'runs' } }) },
    Event: class { constructor(type) { this.type = type; } },
    shoes, retiredShoes, esc, renderedPanels: new Map(), chartInstances: {}, localDateISO: () => '2026-05-10',
    BRAND_COLORS: { Mizuno: ['#m0', '#m1', '#m2'], PUMA: ['#p0'] },
    getThemeColor: () => '#000', fitChartLabel: label => label, console: { error: assert.fail },
    Chart: function(_, config) { this.config = config; this.destroy = () => {}; },
    ...globals,
  });
}

const summary = {
  as_of: '2026-05-10', week: { start: '2026-05-04', km: 23, runs: 4 }, streak_days: 3,
  month_goal: { active: true, km: 23, goal_km: 100, percent: 23 },
  total: { km: 244.5, reached_km: 100, next_km: 250, remaining_km: 5.5 },
  records: { longest_run: { date: '2026-03-02', km: 30, shoe_id: 1 }, biggest_week: { week_start: '2026-03-02', km: 40 },
    biggest_month: { year: 2026, month: 3, km: 120 } },
  achievements: [{ kind: 'shoe', shoe_id: 3, km: 300 }, { kind: 'longest_run', km: 30, date: '2026-05-09' }],
  suggestion: [{ shoe_id: 2, days_since_last_run: 90, remaining_km: 10, usage_percent: 99, near_end: true },
    { shoe_id: 4, days_since_last_run: 12, remaining_km: 600, usage_percent: 25, near_end: false }],
};

test('SPEC-040 run log summary shows week, streak, goal ring, milestones and the next shoe', async () => {
  const nodes = elements(); const urls = [];
  const ctx = context(nodes, { apiGet: async url => { urls.push(url); return summary; } });
  vm.runInContext(`let homeSummaryRequestId = 0;\n${['brandColor', 'shoeColor', 'shoeName', 'goalRing', 'homeTile',
    'achievementText', 'renderShoeSuggestion', 'renderHomeSummary'].map(extract).join('\n')}`, ctx);
  await ctx.renderHomeSummary(); await ctx.renderHomeSummary();
  assert.deepEqual(urls, ['/analytics/home'], 'the summary is cached for the day');
  const tiles = nodes['home-tiles'].innerHTML;
  assert.match(tiles, /本週<\/div><div class="home-tile-value">23\.0 km<\/div><div class="home-tile-sub">4 次跑步/);
  assert.match(tiles, /連續跑步.*3 天/);
  assert.match(tiles, /class="goal-ring".*本月目標.*23%.*23\.0 km \/ 100\.0 km/);
  assert.match(tiles, /再 5\.5 km 就到 250 km/);
  const chips = nodes['home-achievements'].innerHTML;
  assert.match(chips, /👟 PUMA Nitro（&lt;b&gt;x&lt;\/b&gt;） 突破 300 km/, 'shoe names are escaped');
  assert.match(chips, /🏅 新的最長距離 30\.0 km（5\/9）/);
  assert.match(chips, /個人紀錄：最長 30\.0 km · 單週最高 40\.0 km · 單月最高 120\.0 km/);
  // The retired first choice is skipped: only shoes that can be selected are suggested.
  assert.equal(nodes['shoe-suggestion'].hidden, false);
  assert.match(nodes['shoe-suggestion'].innerHTML, /建議 <strong>Mizuno Neo<\/strong>（已經 12 天沒穿）/);
  nodes['run-shoe'].dataset.requiresSelection = 'true';
  nodes['use-suggested-shoe'].onclick();
  assert.equal(nodes['run-shoe'].value, '4');
  assert.equal(nodes['run-shoe'].dataset.requiresSelection, undefined);
  assert.deepEqual(nodes['run-shoe'].dispatched, ['change'], 'drafts observe the chosen shoe');
});

test('SPEC-040 shoes keep one color in every chart regardless of list order', () => {
  const ctx = context(elements());
  vm.runInContext(['brandColor', 'shoeColor', 'shoeName'].map(extract).join('\n'), ctx);
  // Within a brand, colors follow shoe ids across active and retired pairs.
  assert.deepEqual([1, 2, 4, 3].map(id => ctx.shoeColor(id)), ['#m0', '#m1', '#m2', '#p0']);
  ctx.shoes = [...shoes].reverse();
  assert.equal(ctx.shoeColor(4), '#m2', 'reordering the list never changes a color');
  assert.equal(ctx.shoeColor(99), '#64748b');
  assert.equal(ctx.shoeName(99), '已刪除的鞋款');
  assert.match(htmlSource, /id="chart-distance-mix"/);
});

const review = {
  year: 2025, end_date: '2025-12-31', complete: true, has_runs: true, total_km: 1200, run_count: 150, run_days: 140,
  active_day_percent: 38.4, average_km: 8, longest_streak_days: 9,
  longest_run: { date: '2025-10-12', km: 42.2, shoe_id: 3 }, biggest_week: { week_start: '2025-10-06', km: 70 },
  biggest_month: { month: 10, km: 180 }, top_shoe: { shoe_id: 1, km: 500, runs: 60 },
  shoes_bought: 2, shoe_spend: 9000, cost_per_km: 7.5, previous_year_km: 1000,
  goal: { active: true, yearly_km: 1500, percent: 80 },
};

test('SPEC-040 year review lays out the backend summary for the shared year', async () => {
  const nodes = elements(); nodes['year-select'].value = '2025'; const urls = [];
  const ctx = context(nodes, { panel: 'monthly', apiGet: async url => { urls.push(url); return review; } });
  vm.runInContext(`let yearReviewRequestId = 0;\n${['brandColor', 'shoeColor', 'shoeName', 'reviewCard', 'renderYearReview'].map(extract).join('\n')}`, ctx);
  await ctx.renderYearReview();
  assert.deepEqual(urls, ['/analytics/year-review?year=2025']);
  assert.equal(nodes['year-review-title'].textContent, '2025 年度回顧');
  const html = nodes['year-review'].innerHTML;
  assert.match(html, /總跑量<\/div><div class="review-value">1200\.0 km<\/div><div class="review-sub">比 2024 年 \+20%（1000\.0 km）<br>年度目標 1500\.0 km 的 80%/);
  assert.match(html, /150 次.*140 天有跑（38\.4% 的日子）/);
  assert.match(html, /最長一次.*42\.2 km.*10\/12 · PUMA Nitro（&lt;b&gt;x&lt;\/b&gt;）/);
  assert.match(html, /最多的月份.*10 月.*180\.0 km/);
  assert.match(html, /買鞋.*2 雙.*NT\$ 9,000 · 每 km NT\$ 7\.5/);
});

test('SPEC-040 year review explains ongoing, empty and future years and rejects malformed data', async () => {
  const nodes = elements(); nodes['year-select'].value = '2026';
  const answers = [{ bad: true }, { year: 2026, end_date: '2026-05-10', complete: false, has_runs: false },
    { year: 2027, end_date: null, complete: false, has_runs: false }];
  let calls = 0;
  const ctx = context(nodes, { panel: 'monthly', console: { error() {} }, apiGet: async () => answers[calls++] });
  vm.runInContext(`let yearReviewRequestId = 0;\n${['brandColor', 'shoeColor', 'shoeName', 'reviewCard', 'renderYearReview'].map(extract).join('\n')}`, ctx);
  await ctx.renderYearReview();
  assert.equal(nodes['year-review'].innerHTML, '', 'malformed data renders nothing');
  await ctx.renderYearReview();
  assert.equal(calls, 2, 'a malformed response is not cached');
  assert.equal(nodes['year-review-title'].textContent, '2026 年度回顧（統計到 5/10）');
  assert.match(nodes['year-review'].innerHTML, /這一年還沒有跑步紀錄/);
  nodes['year-select'].value = '2027';
  await ctx.renderYearReview();
  assert.match(nodes['year-review'].innerHTML, /2027 年還沒開始/);
});

test('SPEC-040 the shared year selector redraws every year view and the comparison chart', () => {
  const nodes = elements(); nodes['year-select'].value = '2026';
  const calls = [];
  const ctx = context(nodes, { panel: 'monthly',
    monthlyMileages: [{ year: 2025, month: 1, km: 50 }, { year: 2026, month: 1, km: 80 }, { year: 2026, month: 2, km: 90 }],
    ...Object.fromEntries(['renderGoalProgress', 'renderMonthlyYearChart', 'renderShoeStackedChart', 'renderYearReview', 'renderTrends']
      .map(name => [name, () => calls.push(name)])),
  });
  vm.runInContext(`let selectedYear = null, selectedGoalMonth = 3;\nconst YEAR_LINE_COLORS = ['#a', '#b'];\n${['onYearChange', 'renderYearOverYearChart'].map(extract).join('\n')}`, ctx);
  ctx.onYearChange();
  assert.deepEqual(calls, ['renderGoalProgress', 'renderMonthlyYearChart', 'renderShoeStackedChart', 'renderYearReview', 'renderTrends']);
  assert.equal(vm.runInContext('selectedYear', ctx), 2026);
  assert.equal(vm.runInContext('selectedGoalMonth', ctx), null);
  const { datasets } = ctx.chartInstances.yearOverYear.config.data;
  assert.deepEqual(Array.from(datasets, row => [row.label, row.borderWidth]), [['2025', 1.5], ['2026', 3]]);
  assert.deepEqual(Array.from(datasets[1].data.slice(0, 3)), [80, 90, null], 'missing months stay gaps');
  assert.match(nodes['yoy-note'].textContent, /粗線為 2026 年/);
});

test('SPEC-040 distance mix stacks bucket counts per active shoe and names the long-run pair', async () => {
  const nodes = elements();
  const ctx = context(nodes, { panel: 'shoes', apiGet: async () => ({ buckets: ['<5', '5–10', '10–15', '15–21', '≥21'], shoes: [
    { shoe_id: 1, counts: [2, 5, 1, 0, 0], runs: 8, km: 60, longest_km: 12, average_km: 7.5 },
    { shoe_id: 3, counts: [0, 0, 1, 2, 1], runs: 4, km: 70, longest_km: 30, average_km: 17.5 },
  ] }) });
  vm.runInContext(`let distanceMixRequestId = 0;\nconst DISTANCE_COLORS = ['#1', '#2', '#3', '#4', '#5'];\n${['brandColor', 'shoeColor', 'shoeName', 'renderDistanceMix'].map(extract).join('\n')}`, ctx);
  await ctx.renderDistanceMix();
  const { config } = ctx.chartInstances.distanceMix;
  assert.deepEqual(config.data.labels, ['Mizuno Rider（日常）', 'PUMA Nitro（<b>x</b>）']);
  assert.deepEqual(config.data.datasets.map(row => row.label), ['<5 km', '5–10 km', '10–15 km', '15–21 km', '≥21 km']);
  assert.deepEqual(config.data.datasets[3].data, [0, 2]);
  assert.equal(config.options.scales.x.stacked, true);
  assert.equal(nodes['distance-mix-canvas'].style.height, '140px');
  assert.equal(nodes['distance-mix-note'].textContent, '15 km 以上的長跑最常穿 PUMA Nitro（<b>x</b>）（3 次）。');
});

test('SPEC-040 phones use a fixed bottom tab bar while the header menu keeps account actions', () => {
  const sidebar = htmlSource.slice(htmlSource.indexOf('id="sidebar-menu"'), htmlSource.indexOf('</aside>'));
  // Destinations sit outside the collapsible account section.
  assert.ok(sidebar.indexOf('class="tabs"') < sidebar.indexOf('id="sidebar-navigation"'));
  assert.ok(sidebar.indexOf('id="user-label"') > sidebar.indexOf('id="sidebar-navigation"'));
  assert.match(sidebar, /<span aria-hidden="true">☰<\/span> 帳號<\/button>/);
  assert.match(styleSource, /\.tabs \{\s*position: fixed;\s*right: 0;\s*bottom: 0;[\s\S]*?grid-template-columns: repeat\(6, minmax\(0, 1fr\)\);/);
  assert.match(styleSource, /calc\(84px \+ env\(safe-area-inset-bottom\)\)/, 'content clears the tab bar');
});
