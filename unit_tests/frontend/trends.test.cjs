const { runContext, test, assert, vm, extract, htmlSource, source, readText } = require('./helpers.cjs');

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
    document: { getElementById: id => nodes[id], querySelector: () => ({ dataset: { panel: globals.panel || 'monthly' } }),
      querySelectorAll: selector => (globals.pagerNodes?.[selector] || []) },
    localDateISO: () => '2026-01-06', chartInstances: {}, renderedPanels: new Map(), runningGoal: { start_year: 2026 },
    // Returns the token name so assertions show which theme color each mark uses (SPEC-051).
    getThemeColor: token => token, brandColor: () => '#123456', shoeColor: () => '#123456', fitChartLabel: label => label,
    Chart: function(_, config) { this.config = config; this.destroy = () => {}; },
    console: { error: assert.fail }, ...globals,
  });
}

const trendRenderers = ['addDaysISO', 'changeWeeklyWindow', 'renderWeekPagers', 'weeklyWindowLabel', 'weekInProgress',
  'partialWeekText', 'renderTrends', 'heatLevel', 'renderRunHeatmap', 'renderWeeklyChart', 'weeklyGoalText',
  'renderCumulativeChart', 'renderLongRunChart', 'longRunText', 'renderWeekdayChart', 'weekdayRuns', 'weekdayText'];
// The weekly window state (SPEC-072) rides along with the shared declarations.
const weekdayLabels = `${source.match(/const WEEKDAY_LABELS = [^\n]+/)[0]}\nlet weeklyWindowEnd = null;\nlet weeklyWindow = null;`;

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

test('SPEC-067 the rotation tooltip shows the shoe total with runs and walking', () => {
  const context = vm.createContext({});
  vm.runInContext(['floorShoeKm', 'formatShoeMileage', 'timelineMileageLines'].map(extract).join('\n'), context);
  const row = { km: 365.19, shoe_km: 407.2, other_km: 42.01, run_count: 50 };
  assert.deepEqual([...context.timelineMileageLines(row)], ['鞋子里程 407.2 km', '跑步 365.1 km · 50 次｜步行與暖身 42.0 km']);
  assert.deepEqual([...context.timelineMileageLines({ ...row, km: 49.11, shoe_km: 48.8, other_km: -0.31, run_count: 7 })],
    ['鞋子里程 48.8 km', '跑步 49.1 km · 7 次'], 'a negative gap is not shown as walking');
  assert.deepEqual([...context.timelineMileageLines({ ...row, other_km: 0.04 })][1], '跑步 365.1 km · 50 次');
});

test('SPEC-068 shoe mileage is truncated to one decimal exactly like Strava', () => {
  const context = vm.createContext({});
  vm.runInContext(['floorShoeKm', 'formatShoeMileage'].map(extract).join('\n'), context);
  // Strava shows the meter sum 673.352 km as 673.3, not 673.4.
  assert.deepEqual([673.352, 401.7, 48.84, 167.31, 0.29, 4.35, 1.1, 0, '261.89', null].map(context.formatShoeMileage),
    ['673.3', '401.7', '48.8', '167.3', '0.2', '4.3', '1.1', '0.0', '261.8', '0.0'], 'binary floating point never drops a tenth');
  for (const file of ['frontend/app-dashboard.js', 'frontend/app-run-insights.js', 'frontend/app-shoe-charts.js']) {
    assert.doesNotMatch(readText(file), /total_mileage_km\)\.toFixed\(|\{s\.mileage\}<|已跑 \$\{shoe\.mileage\}|totalMileage\.toLocaleString\(\)/, file);
  }
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
  weekly: sample.weekly.map((week, index) => ({ ...week, longest_km: [8, 21, 12][index], goal_met: [false, true, false][index] })),
  weekday: [
    { weekday: 0, km: 21, run_days: 1, runs: 1 }, { weekday: 1, km: 0, run_days: 0, runs: 0 }, { weekday: 2, km: 0, run_days: 0, runs: 0 },
    { weekday: 3, km: 3, run_days: 1, runs: 1 }, { weekday: 4, km: 12, run_days: 1, runs: 2 }, { weekday: 5, km: 0, run_days: 0, runs: 0 },
    { weekday: 6, km: 0, run_days: 0, runs: 0 },
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
  // v4.14.1: the note states the basis (annual goal over 52.1 weeks, not month ÷ 4).
  assert.match(nodes['weekly-note'].textContent, /^本週 21\.0／23\.0 km；週目標 23\.0 km（年度目標 1200 km ÷ 52\.1 週），已結束的 2 週有 1 週達標。橘色的 1 週/);
  // The unfinished week has no 4-week average point, so the line does not dip.
  assert.deepEqual([...datasets[1].data], [20, 25, null]);
  assert.equal(context.chartInstances.weekly.config.options.plugins.tooltip.callbacks.label({ raw: null, dataset: datasets[1] }), '4 週平均: 本週結束後計算');

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
  assert.deepEqual([...longRun.data.datasets[0].data], [8, 21, 12], 'a long run already done this week is shown');
  assert.equal(longRun.data.datasets[0].borderColor, '--chart-2');
  assert.deepEqual([...longRun.options.plugins.tooltip.callbacks.afterBody([{ dataIndex: 2 }])], ['本週進行中']);
  // v4.14.1: only finished weeks count toward the recent average.
  assert.equal(nodes['long-run-note'].textContent, '近 16 週最長 21.0 km（12/29 那週）；過去 2 週（不含本週）平均最長一次 14.5 km。');

  const weekday = context.chartInstances.weekday.config;
  assert.deepEqual([...weekday.data.labels], ['週一', '週二', '週三', '週四', '週五', '週六', '週日']);
  assert.deepEqual([...weekday.data.datasets[0].data], [21, 0, 0, 3, 12, 0, 0]);
  assert.equal(weekday.options.plugins.tooltip.callbacks.label({ dataIndex: 4 }), '12.0 km · 1 天 2 次 · 平均每次 6.0 km');
  assert.equal(nodes['weekday-title'].textContent, '2026 年星期幾跑量與配速');
  assert.equal(weekday.data.datasets.length, 1, 'no pace line without any timed run');
  assert.equal(nodes['weekday-note'].textContent, '跑最多的是週一：21.0 km、1 次，平均每次跑 21.0 km；週二、週三、週六、週日這一年沒跑過。');
  const everyDay = analysis.weekday.map(row => ({ ...row, km: row.km || 5, run_days: row.run_days || 1, runs: row.runs || 1 }));
  assert.equal(context.weekdayText(everyDay), '跑最多的是週一：21.0 km、1 次，平均每次跑 21.0 km。', 'no filler when every weekday has runs');
  assert.equal(context.weekdayRuns({ run_days: 3 }), 3, 'an older response without run counts uses running days');
  assert.match(htmlSource, /<canvas id="chart-long-run"><\/canvas>[\s\S]*<canvas id="chart-weekday"><\/canvas>/);
});

test('SPEC-056 an unfinished week without a run is not drawn as a 0 km long run', async () => {
  const nodes = elements(); nodes['year-select'].value = '2026';
  const quiet = { ...analysis, weekly: analysis.weekly.map((week, index) => ({ ...week, longest_km: [8, 21, 0][index] })) };
  const context = trendsContext(nodes, { apiGet: async () => quiet });
  vm.runInContext(`let trendsRequestId = 0;\n${weekdayLabels}\n${trendRenderers.map(extract).join('\n')}`, context);
  await context.renderTrends();
  assert.deepEqual([...context.chartInstances.longRun.config.data.datasets[0].data], [8, 21, null]);
  assert.match(nodes['long-run-note'].textContent, /過去 2 週（不含本週）平均最長一次 14\.5 km/);
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

test('SPEC-064 the weekday chart adds the backend weekday pace on a reversed axis', async () => {
  const nodes = elements(); nodes['year-select'].value = '2026';
  const timed = { ...analysis, weekday: analysis.weekday.map(row => ({ ...row, pace: { 0: 369, 3: 354, 4: 370 }[row.weekday] ?? null })) };
  const context = trendsContext(nodes, { apiGet: async () => timed });
  vm.runInContext(`let trendsRequestId = 0;\n${weekdayLabels}\n${trendRenderers.map(extract).join('\n')}`, context);
  await context.renderTrends();
  const weekday = context.chartInstances.weekday.config;
  assert.deepEqual(JSON.parse(JSON.stringify(weekday.data.datasets[1].data)), [369, null, null, 354, 370, null, null]);
  assert.equal(weekday.options.scales.pace.reverse, true);
  assert.equal(weekday.options.scales.pace.ticks.callback(354), '5:54');
  assert.equal(weekday.options.plugins.tooltip.callbacks.label({ dataIndex: 3, dataset: weekday.data.datasets[1] }), '平均配速 5:54 /km');
  assert.equal(nodes['weekday-note'].textContent,
    '跑最多的是週一：21.0 km、1 次，平均每次跑 21.0 km；平均配速最快是週四（5:54 /km），最慢是週五（6:10 /km）；週二、週三、週六、週日這一年沒跑過。');
});

test('SPEC-072 a past year pages back 16 weeks at a time and never calls its last week "本週"', async () => {
  const nodes = elements(); nodes['year-select'].value = '2024';
  const buttons = [{ dataset: { weekPager: 'earlier' } }, { dataset: { weekPager: 'later' } }];
  const pagers = [{ hidden: true }, { hidden: true }];
  const week = (start, km, extra = {}) => ({ week_start: start, km, average_km: km, baseline_km: km, change_percent: 0,
    spike: false, partial: false, longest_km: km, goal_met: false, ...extra });
  const latest = { ...sample, year: 2024, end_date: '2024-12-31', weekly_goal: { active: true, km: 28.7 },
    weekly: [week('2024-12-23', 5), week('2024-12-30', 0, { partial: true })],
    weekly_window: { end: '2024-12-31', has_earlier: true, has_later: false } };
  const earlier = { ...latest, weekly: [week('2024-05-13', 20), week('2024-08-26', 12)],
    weekly_window: { end: '2024-09-03', has_earlier: true, has_later: true } };
  const urls = [];
  const context = trendsContext(nodes, {
    pagerNodes: { '.week-pager': pagers, '[data-week-pager]': buttons }, localDateISO: () => '2026-11-18',
    resourceStore: { read: async (_, { loader }) => ({ status: 'fulfilled', value: await loader() }), current: () => true },
    apiGet: async url => { urls.push(url); return url.includes('weeks_end') ? earlier : latest; },
  });
  vm.runInContext(`let trendsRequestId = 0;\n${weekdayLabels}\n${trendRenderers.map(extract).join('\n')}`, context);
  await context.renderTrends();
  assert.deepEqual(pagers.map(pager => pager.hidden), [false, false]);
  assert.deepEqual(buttons.map(button => button.disabled), [false, true], 'the latest window cannot go later');
  assert.doesNotMatch(nodes['weekly-note'].textContent, /本週/, 'a finished year has no current week');
  const tooltip = context.chartInstances.weekly.config.options.plugins.tooltip.callbacks.afterBody([{ dataIndex: 1 }]);
  assert.equal(Array.from(tooltip).at(-1), '只算到 12/31');

  context.changeWeeklyWindow(-1);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(urls, ['/analytics/trends?year=2024', '/analytics/trends?year=2024&weeks_end=2024-09-10']);
  assert.deepEqual(buttons.map(button => button.disabled), [false, false]);
  assert.match(nodes['long-run-note'].textContent, /^5\/13～9\/1 這 16 週最長 20\.0 km/);
});
