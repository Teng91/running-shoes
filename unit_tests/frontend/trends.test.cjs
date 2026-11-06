const { runContext, test, assert, vm, extract, htmlSource } = require('./helpers.cjs');

function elements() {
  return new Proxy({}, { get: (target, id) => target[id] ||= {
    id, value: '', textContent: '', innerHTML: '', hidden: false,
    style: { setProperty(name, value) { this[name] = value; } },
    attributes: {}, setAttribute(name, value) { this.attributes[name] = value; },
    parentElement: { scrollLeft: 0, scrollWidth: 900 },
  } });
}

function trendsContext(nodes, globals = {}) {
  return runContext({
    document: { getElementById: id => nodes[id], querySelector: () => ({ dataset: { panel: globals.panel || 'monthly' } }) },
    chartInstances: {}, renderedPanels: new Map(), runningGoal: { start_year: 2026 },
    getThemeColor: () => '#000', brandColor: () => '#123456', fitChartLabel: label => label,
    Chart: function(_, config) { this.config = config; this.destroy = () => {}; },
    console: { error: assert.fail }, ...globals,
  });
}

const trendRenderers = ['renderTrends', 'heatLevel', 'renderRunHeatmap', 'renderWeeklyChart', 'renderCumulativeChart'];

const sample = {
  year: 2026, end_date: '2026-01-06', thresholds: { spike_percent: 30, spike_min_base_km: 5 },
  daily: [{ date: '2026-01-01', km: 3 }, { date: '2026-01-02', km: 12 }, { date: '2026-01-05', km: 21 }],
  streaks: { longest_days: 2, longest_end: '2026-01-02', current_days: 1 },
  weekly: [
    { week_start: '2025-12-22', km: 20, average_km: 20, baseline_km: 20, change_percent: 0, spike: false, partial: false },
    { week_start: '2025-12-29', km: 40, average_km: 25, baseline_km: 20, change_percent: 100, spike: true, partial: false },
    { week_start: '2026-01-05', km: 21, average_km: 26, baseline_km: 25, change_percent: -16, spike: false, partial: true },
  ],
  cumulative: { goal_active: true, yearly_goal_km: 1200, actual_km: [3, 15, 15, 15, 36, 36], goal_km: Array(365).fill(1),
    ytd_km: 36, expected_km: 19.73, delta_km: 16.27, projected_km: 2190 },
};

test('SPEC-038 trends render a Monday-first heatmap, weekly spikes and the goal pace note', async () => {
  const nodes = elements(); nodes['trends-year-select'].value = '2026';
  const urls = [];
  const context = trendsContext(nodes, { apiGet: async url => { urls.push(url); return sample; } });
  vm.runInContext(`let trendsRequestId = 0;\n${trendRenderers.map(extract).join('\n')}`, context);
  await context.renderTrends();
  assert.deepEqual(urls, ['/analytics/trends?year=2026']);
  const html = nodes['run-heatmap'].innerHTML;
  // 2026-01-01 is a Thursday: three blank Monday-first cells precede it.
  assert.equal(html.match(/heat-cell blank/g).length, 3);
  assert.match(html, /level-1" title="2026-01-01 · 3\.00 km"/);
  assert.match(html, /level-3" title="2026-01-02 · 12\.00 km"/);
  assert.match(html, /level-4" title="2026-01-05 · 21\.00 km"/);
  assert.match(html, /level-0" title="2026-01-03 · 未跑"/);
  assert.equal(html.match(/heat-cell future/g).length, 365 - 6);
  assert.equal(html.match(/月<\/span>/g).length, 12);
  assert.match(nodes['streak-stats'].innerHTML, /3<\/strong> 天有跑.*最長連續 <strong>2.*目前連續 <strong>1/);
  assert.equal(nodes['run-heatmap'].parentElement.scrollLeft, 900, 'phones start at the latest weeks');

  const weekly = context.chartInstances.weekly.config.data.datasets[0];
  assert.deepEqual(weekly.backgroundColor, ['#6366f1', '#f97316', 'rgba(99,102,241,.45)']);
  assert.match(nodes['weekly-note'].textContent, /橘色的 1 週比前 4 週平均多 30%/);
  assert.equal(context.chartInstances.cumulative.config.data.datasets.length, 2);
  assert.match(nodes['cumulative-note'].textContent, /累計 36\.0 km，超前目標進度 16\.3 km；照目前速度全年約 2190 km（目標 1200 km）/);
});

test('SPEC-038 future years render no charts and malformed trends are not cached', async () => {
  const nodes = elements(); nodes['trends-year-select'].value = '2027';
  let calls = 0;
  const context = trendsContext(nodes, { console: { error() {} },
    apiGet: async () => (++calls === 1 ? { daily: 'bad' } : { ...sample, year: 2027, end_date: null, daily: [], weekly: [] }) });
  vm.runInContext(`let trendsRequestId = 0;\n${trendRenderers.map(extract).join('\n')}`, context);
  await context.renderTrends();
  assert.equal(context.chartInstances.weekly, undefined);
  await context.renderTrends();
  assert.equal(calls, 2, 'a malformed response is retried');
  assert.equal(context.chartInstances.weekly, undefined);
  assert.equal(context.chartInstances.cumulative, undefined);
  assert.match(nodes['weekly-note'].textContent, /還沒開始/);
  assert.equal(nodes['run-heatmap'].innerHTML.match(/heat-cell future/g).length, 365);
});

test('SPEC-038 rotation timeline names shoes, greys retired pairs and calls out idle active shoes', async () => {
  const nodes = elements();
  const context = trendsContext(nodes, { panel: 'shoes',
    shoes: [{ id: 2, brand: 'Mizuno', model: 'Rider', nickname: '日常' }, { id: 3, brand: 'PUMA', model: 'Nitro', nickname: '' }],
    retiredShoes: [{ id: 1, brand: 'Mizuno', model: 'Sky', nickname: '' }],
    apiGet: async () => ({ as_of: '2026-05-01', idle_days: 30, shoes: [
      { shoe_id: 1, is_retired: true, first_run_date: '2025-01-01', last_run_date: '2025-08-01', km: 15, run_count: 2, days_since_last_run: 273, idle: false },
      { shoe_id: 3, is_retired: false, first_run_date: '2025-06-01', last_run_date: '2026-03-01', km: 16, run_count: 2, days_since_last_run: 61, idle: true },
      { shoe_id: 2, is_retired: false, first_run_date: '2026-02-01', last_run_date: '2026-04-30', km: 30, run_count: 3, days_since_last_run: 1, idle: false },
    ] }) });
  vm.runInContext(`const DAY_MS = 86400000; let shoeTimelineRequestId = 0;\n${extract('renderShoeTimeline')}`, context);
  await context.renderShoeTimeline();
  const { config } = context.chartInstances.timeline;
  assert.deepEqual(config.data.labels, ['Mizuno Sky', 'PUMA Nitro', 'Mizuno Rider（日常）']);
  assert.deepEqual(config.data.datasets[0].backgroundColor, ['#64748b', '#f97316', '#123456']);
  const [start, end] = config.data.datasets[0].data[2];
  assert.equal(end - start, (88 + 1) * 86400000, 'bars include their last day');
  assert.equal(nodes['shoe-timeline-canvas'].style.height, `${3 * 34 + 48}px`);
  assert.match(nodes['timeline-note'].textContent, /超過 30 天沒穿的現役鞋（PUMA Nitro）/);
});

test('SPEC-038 trend sections are present with an accessible scroll region and legend', () => {
  assert.match(htmlSource, /id="trends-year-select" class="year-select" aria-label="訓練趨勢年份" onchange="onTrendsYearChange\(\)"/);
  for (const id of ['run-heatmap', 'streak-stats', 'chart-weekly', 'chart-cumulative', 'chart-shoe-timeline', 'timeline-note']) {
    assert.match(htmlSource, new RegExp(`id="${id}"`));
  }
  assert.match(htmlSource, /class="heatmap-scroll" tabindex="0" role="region" aria-label="可左右滑動的年度熱力圖"/);
  assert.match(htmlSource, /0／&lt;5／5–10／10–15／≥15 km/);
});
