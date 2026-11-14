const { runContext, test, assert, vm, extract, htmlSource, source } = require('./helpers.cjs');

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
    // Returns the token name so assertions show which theme color each mark uses (SPEC-051).
    getThemeColor: token => token, brandColor: () => '#123456', shoeColor: () => '#123456', fitChartLabel: label => label,
    Chart: function(_, config) { this.config = config; this.destroy = () => {}; },
    console: { error: assert.fail }, ...globals,
  });
}

const trendRenderers = ['renderTrends', 'heatLevel', 'renderRunHeatmap', 'renderWeeklyChart', 'weeklyGoalText',
  'renderCumulativeChart', 'renderLongRunChart', 'longRunText', 'renderWeekdayChart', 'weekdayText'];
const weekdayLabels = source.match(/const WEEKDAY_LABELS = [^\n]+/)[0];

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
  const nodes = elements(); nodes['year-select'].value = '2026';
  const urls = [];
  const context = trendsContext(nodes, { apiGet: async url => { urls.push(url); return sample; } });
  vm.runInContext(`let trendsRequestId = 0;\n${weekdayLabels}\n${trendRenderers.map(extract).join('\n')}`, context);
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
  assert.deepEqual(weekly.backgroundColor, ['--chart-1', '--chart-warn', '--chart-1-soft'], 'spikes stay orange, the partial week is muted');
  assert.match(nodes['weekly-note'].textContent, /橘色的 1 週比前 4 週平均多 30%/);
  assert.equal(context.chartInstances.cumulative.config.data.datasets.length, 2);
  assert.match(nodes['cumulative-note'].textContent, /累計 36\.0 km，超前目標進度 16\.3 km；照目前速度全年約 2190 km（目標 1200 km）/);
});

test('SPEC-038 future years render no charts and malformed trends are not cached', async () => {
  const nodes = elements(); nodes['year-select'].value = '2027';
  let calls = 0;
  const context = trendsContext(nodes, { console: { error() {} },
    apiGet: async () => (++calls === 1 ? { daily: 'bad' } : { ...sample, year: 2027, end_date: null, daily: [], weekly: [] }) });
  vm.runInContext(`let trendsRequestId = 0;\n${weekdayLabels}\n${trendRenderers.map(extract).join('\n')}`, context);
  await context.renderTrends();
  assert.equal(context.chartInstances.weekly, undefined);
  await context.renderTrends();
  assert.equal(calls, 2, 'a malformed response is retried');
  assert.equal(context.chartInstances.weekly, undefined);
  assert.equal(context.chartInstances.cumulative, undefined);
  assert.match(nodes['weekly-note'].textContent, /還沒開始/);
  assert.equal(nodes['run-heatmap'].innerHTML.match(/heat-cell future/g).length, 365);
});

test('SPEC-038 rotation timeline names active shoes and calls out idle ones without retired pairs', async () => {
  const nodes = elements();
  const context = trendsContext(nodes, { panel: 'shoes',
    shoes: [{ id: 2, brand: 'Mizuno', model: 'Rider', nickname: '日常' }, { id: 3, brand: 'PUMA', model: 'Nitro', nickname: '' }],
    retiredShoes: [{ id: 1, brand: 'Mizuno', model: 'Sky', nickname: '' }],
    apiGet: async () => ({ as_of: '2026-05-01', idle_days: 30, shoes: [
      { shoe_id: 3, first_run_date: '2025-06-01', last_run_date: '2026-03-01', km: 16, run_count: 2, days_since_last_run: 61, idle: true },
      { shoe_id: 2, first_run_date: '2026-02-01', last_run_date: '2026-04-30', km: 30, run_count: 3, days_since_last_run: 1, idle: false },
    ] }) });
  vm.runInContext(`const DAY_MS = 86400000; let shoeTimelineRequestId = 0;\n${extract('renderShoeTimeline')}`, context);
  await context.renderShoeTimeline();
  const { config } = context.chartInstances.timeline;
  assert.deepEqual(config.data.labels, ['PUMA Nitro', 'Mizuno Rider（日常）']);
  assert.deepEqual(config.data.datasets[0].backgroundColor, ['--chart-warn', '#123456']);
  const [start, end] = config.data.datasets[0].data[1];
  assert.equal(end - start, (88 + 1) * 86400000, 'bars include their last day');
  assert.equal(nodes['shoe-timeline-canvas'].style.height, '140px');
  assert.match(nodes['timeline-note'].textContent, /超過 30 天沒穿的現役鞋（PUMA Nitro）。已退役的鞋不列出/);
  assert.doesNotMatch(nodes['timeline-note'].textContent, /灰色/);
});

// The shoes panel draws two run-derived charts from their own reads. Real resource store,
// cache hooks and panel bookkeeping; only the HTTP responses are held back.
function shoesPanelContext() {
  const nodes = elements();
  const state = { panel: 'shoes', pending: [], urls: [] };
  const timeline = { as_of: '2026-05-01', idle_days: 30, shoes: [
    { shoe_id: 2, first_run_date: '2026-02-01', last_run_date: '2026-04-30', km: 30, run_count: 3, days_since_last_run: 1, idle: false },
  ] };
  const mix = { buckets: ['<5', '5–10', '10–15', '15–20', '≥20'],
    shoes: [{ shoe_id: 2, counts: [1, 0, 0, 1, 1], runs: 3, average_km: 12, longest_km: 21 }] };
  const noop = () => {};
  const context = trendsContext(nodes, {
    document: { getElementById: id => nodes[id], querySelector: () => ({ dataset: { panel: state.panel } }) },
    shoes: [{ id: 2, brand: 'Mizuno', model: 'Rider', nickname: '' }], retiredShoes: [],
    shoeName: () => 'Mizuno Rider', panelRevision: 0, currentTheme: 'light', localDateISO: () => '2026-05-01',
    renderCards: noop, renderAlerts: noop, renderCategorySummary: noop, renderTable: noop, renderRetiredTable: noop,
    renderSpendingCharts: noop, populateRunShoeSelects: noop, renderRunLog: noop, renderHomeSummary: noop,
    selectedRunMonth: () => '2026-05', spendingSummary: null, spendingLoadRequestId: 0, spendingLoadPending: false,
    goalProgressRequestId: 0,
    apiGet: url => new Promise(resolve => {
      state.urls.push(url);
      state.pending.push(() => resolve(url.endsWith('shoe-timeline') ? timeline : mix));
    }),
  });
  vm.runInContext(`const DAY_MS = 86400000; let shoeTimelineRequestId = 0, distanceMixRequestId = 0;
    const DISTANCE_COLORS = ['#ef4444'];
    function renderCharts() { renderShoeTimeline(); renderDistanceMix(); }
    ${['invalidatePanels', 'renderActivePanel', 'renderShoeTimeline', 'renderDistanceMix'].map(extract).join('\n')}`, context);
  const settle = () => new Promise(resolve => setImmediate(resolve));
  // Mirrors loadData's applyResource: accept (cache hooks run), then render(resource).
  context.arrive = async (resource, value) => {
    const result = await context.resourceStore.read(resource, { loader: async () => value });
    context.resourceStore.accept([result]);
    context.invalidatePanels(resource);
    context.renderActivePanel();
    await settle();
  };
  context.respond = async () => {
    do { state.pending.shift()?.(); await settle(); } while (state.pending.length);
  };
  return { context, state, nodes };
}

test('the shoes panel redraws its rotation timeline and distance mix when runs arrive mid-read', async () => {
  for (const later of ['runs', 'goal']) {
    const { context, state } = shoesPanelContext();
    await context.arrive('shoes', [context.shoes, []]);
    assert.deepEqual(state.urls, ['/analytics/shoe-timeline', '/analytics/shoe-distance-mix']);
    // Accepting runs or the goal drops both cached reads while they are still in flight.
    await context.arrive(later, later === 'runs' ? { page: { rows: [] }, summary: {}, requestId: 0 } : {});
    await context.respond();
    assert.ok(context.chartInstances.timeline, `${later}: the rotation timeline is drawn`);
    assert.ok(context.chartInstances.distanceMix, `${later}: the distance mix is drawn`);
  }
});

test('the shoes panel redraws its run charts after leaving the tab during their reads', async () => {
  const { context, state } = shoesPanelContext();
  await context.arrive('shoes', [context.shoes, []]);
  state.panel = 'runs';
  await context.respond();
  assert.equal(context.chartInstances.timeline, undefined);
  state.panel = 'shoes';
  context.renderActivePanel();
  await context.respond();
  assert.ok(context.chartInstances.timeline, 'the rotation timeline is drawn on return');
  assert.ok(context.chartInstances.distanceMix, 'the distance mix is drawn on return');
  assert.equal(state.urls.length, 2, 'the finished reads are reused instead of fetched again');
});

test('SPEC-038 trend sections are present with an accessible scroll region and legend', () => {
  // SPEC-040: one shared selector drives the trends together with every other year view.
  assert.match(htmlSource, /<label for="year-select">年份<\/label>\s*<select id="year-select" class="year-select" data-change="year">/);
  assert.doesNotMatch(htmlSource, /trends-year-select|stacked-year-select/);
  for (const id of ['run-heatmap', 'streak-stats', 'chart-weekly', 'chart-cumulative', 'chart-shoe-timeline', 'timeline-note']) {
    assert.match(htmlSource, new RegExp(`id="${id}"`));
  }
  assert.match(htmlSource, /class="heatmap-scroll" tabindex="0" role="region" aria-label="可左右滑動的年度熱力圖"/);
  assert.match(htmlSource, /0／&lt;5／5–10／10–15／≥15 km/);
});

const analysis = {
  ...sample,
  weekly_goal: { active: true, km: 23.01 },
  weekly: sample.weekly.map((week, index) => ({ ...week, longest_km: [8, 21.1, 12][index], goal_met: [false, true, false][index] })),
  weekday: [
    { weekday: 0, km: 21, run_days: 1 }, { weekday: 1, km: 0, run_days: 0 }, { weekday: 2, km: 0, run_days: 0 },
    { weekday: 3, km: 3, run_days: 1 }, { weekday: 4, km: 12, run_days: 1 }, { weekday: 5, km: 0, run_days: 0 },
    { weekday: 6, km: 0, run_days: 0 },
  ],
};

test('SPEC-056 the weekly chart draws the weekly goal and counts finished weeks that met it', async () => {
  const nodes = elements(); nodes['year-select'].value = '2026';
  const context = trendsContext(nodes, { apiGet: async () => analysis });
  vm.runInContext(`let trendsRequestId = 0;\n${weekdayLabels}\n${trendRenderers.map(extract).join('\n')}`, context);
  await context.renderTrends();
  const datasets = context.chartInstances.weekly.config.data.datasets;
  assert.deepEqual([...datasets].map(set => set.label), ['週跑量', '4 週平均', '週目標']);
  assert.deepEqual([...datasets[2].data], [23.01, 23.01, 23.01]);
  assert.deepEqual([...datasets[2].borderDash], [6, 4]);
  assert.match(nodes['weekly-note'].textContent, /^本週 21\.0／23\.0 km；週目標 23\.0 km，已結束的 2 週有 1 週達標。橘色的 1 週/);

  // Before the goal's start year the chart keeps its two series and the plain note.
  const inactive = elements(); inactive['year-select'].value = '2026';
  const before = trendsContext(inactive, { apiGet: async () => ({ ...analysis, weekly_goal: { active: false, km: 23.01 } }) });
  vm.runInContext(`let trendsRequestId = 0;\n${weekdayLabels}\n${trendRenderers.map(extract).join('\n')}`, before);
  await before.renderTrends();
  assert.equal(before.chartInstances.weekly.config.data.datasets.length, 2);
  assert.match(inactive['weekly-note'].textContent, /^橘色的 1 週/);
});

test('SPEC-056 long-run and weekday charts lay out the backend values', async () => {
  const nodes = elements(); nodes['year-select'].value = '2026';
  const context = trendsContext(nodes, { apiGet: async () => analysis });
  vm.runInContext(`let trendsRequestId = 0;\n${weekdayLabels}\n${trendRenderers.map(extract).join('\n')}`, context);
  await context.renderTrends();
  const longRun = context.chartInstances.longRun.config;
  assert.deepEqual([...longRun.data.labels], ['12/22', '12/29', '1/5']);
  assert.deepEqual([...longRun.data.datasets[0].data], [8, 21.1, 12]);
  assert.equal(longRun.data.datasets[0].borderColor, '--chart-2');
  assert.equal(nodes['long-run-note'].textContent, '近 16 週最長 21.1 km（12/29 那週）；近 4 週平均最長一次 13.7 km。');

  const weekday = context.chartInstances.weekday.config;
  assert.deepEqual([...weekday.data.labels], ['週一', '週二', '週三', '週四', '週五', '週六', '週日']);
  assert.deepEqual([...weekday.data.datasets[0].data], [21, 0, 0, 3, 12, 0, 0]);
  assert.equal(weekday.options.plugins.tooltip.callbacks.label({ dataIndex: 4 }), '12.0 km · 1 天 · 平均 12.0 km');
  assert.equal(nodes['weekday-title'].textContent, '2026 年星期幾跑量');
  assert.equal(nodes['weekday-note'].textContent, '跑最多的是週一（21.0 km、1 天）；週二、週三、週六、週日這一年沒跑過。');
  assert.match(htmlSource, /<canvas id="chart-long-run"><\/canvas>[\s\S]*<canvas id="chart-weekday"><\/canvas>/);
});

test('SPEC-056 future years draw no long-run or weekday chart', async () => {
  const nodes = elements(); nodes['year-select'].value = '2027';
  const context = trendsContext(nodes, { apiGet: async () => ({ ...analysis, year: 2027, end_date: null, daily: [], weekly: [] }) });
  vm.runInContext(`let trendsRequestId = 0;\n${weekdayLabels}\n${trendRenderers.map(extract).join('\n')}`, context);
  await context.renderTrends();
  assert.equal(context.chartInstances.longRun, undefined);
  assert.equal(context.chartInstances.weekday, undefined);
  assert.match(nodes['long-run-note'].textContent, /還沒開始/);
  assert.match(nodes['weekday-note'].textContent, /還沒開始/);
});
