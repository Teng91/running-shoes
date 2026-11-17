// SPEC-064: pace analysis charts only lay out backend values.
const { test, assert, vm, readText, htmlSource } = require('./helpers.cjs');

const esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function paceAnalysisContext(analysis) {
  const nodes = new Proxy({}, { get: (target, id) => target[id] ||= { id, textContent: '', innerHTML: '' } });
  const charts = [];
  class Chart {
    constructor(canvas, config) { this.canvas = canvas; this.config = config; this.destroyed = false; charts.push(this); }
    destroy() { this.destroyed = true; }
  }
  const reads = [];
  const context = vm.createContext({
    Chart, esc, console: { error() {} }, chartInstances: {},
    getThemeColor: (_, fallback) => fallback,
    apiGet: async path => { reads.push(path); return analysis; },
    document: {
      getElementById: id => nodes[id],
      querySelector: () => ({ dataset: { panel: 'monthly' } }),
    },
  });
  vm.runInContext(readText('frontend/app-pace-charts.js'), context);
  return { context, nodes, charts, reads };
}

const analysis = {
  as_of: '2026-11-17', timed_run_count: 3, untimed_run_count: 1,
  summary: { first_date: '2025-07-01', first_90_days_pace: 388, recent_90_days_pace: 352, recent_30_days_pace: 347 },
  runs: [{ date: '2025-07-01', km: 5.52, pace: 389 }, { date: '2026-11-15', km: 13.22, pace: 333 }],
  rolling: [{ date: '2025-07-01', pace: 389 }, { date: '2026-11-15', pace: 348 }],
  monthly: [{ month: '2025-07', km: 79.2, timed_km: 79.2, runs: 17, pace: 392 }, { month: '2025-08', km: 0, timed_km: 0, runs: 0, pace: null }],
  monthly_lag: { months: 3, same_month_correlation: -0.26, prior_months_correlation: -0.84, points: 14 },
  load: {
    weeks: 4, correlation: -0.39,
    points: [{ week_start: '2026-11-09', prior_week_km: 31.5, km: 28, pace: 345 }],
    trend: { slope_seconds_per_10km: -16.3, intercept: 410.5, min_km: 12.61, max_km: 47.85 },
    buckets: [{ min_km: 10, max_km: 20, weeks: 19, median_pace: 381 }, { min_km: 30, max_km: 40, weeks: 24, median_pace: 350 }],
    comparison: { low: { min_km: 10, max_km: 20, weeks: 19, median_pace: 381 }, fast: { min_km: 30, max_km: 40, weeks: 24, median_pace: 350 }, seconds_faster: 31 },
  },
  distance: [
    { min_km: 0, max_km: 5, runs: 46, km: 160.43, pace: 389, fastest_pace: 309 },
    { min_km: 8, max_km: 12, runs: 62, km: 586.32, pace: 354, fastest_pace: 287 },
    { min_km: 22, max_km: null, runs: 0, km: 0, pace: null, fastest_pace: null },
  ],
  distribution: { bin_seconds: 15, median_pace: 364, bins: [
    { min_pace: 315, max_pace: 330, runs: 23, open_min: true, open_max: false },
    { min_pace: 345, max_pace: 360, runs: 60, open_min: false, open_max: false },
    { min_pace: 405, max_pace: 420, runs: 22, open_min: false, open_max: true },
  ] },
};

test('SPEC-064 pace charts render backend values with reversed pace axes', async () => {
  const { context, nodes, charts, reads } = paceAnalysisContext(analysis);
  await context.renderPaceAnalysis();
  assert.deepEqual(reads, ['/analytics/pace']);
  assert.deepEqual(charts.map(chart => chart.canvas.id),
    ['chart-pace-trend', 'chart-pace-monthly', 'chart-pace-load', 'chart-pace-distance', 'chart-pace-distribution']);
  const [trend, monthly, load, distance, distribution] = charts.map(chart => chart.config);
  assert.equal(trend.options.scales.y.reverse, true);
  assert.equal(monthly.options.scales.pace.reverse, true);
  assert.equal(load.options.scales.y.reverse, true);
  assert.equal(distance.options.scales.y.reverse, true);
  assert.equal(trend.options.scales.y.ticks.callback(347), '5:47');
  assert.deepEqual(JSON.parse(JSON.stringify(monthly.data.datasets[1].data)), [392, null]);
  assert.deepEqual(JSON.parse(JSON.stringify(load.data.datasets[1].data)).map(point => Math.round(point.y * 10) / 10),
    [410.5 - 1.63 * 12.61, 410.5 - 1.63 * 47.85].map(value => Math.round(value * 10) / 10), 'trend line comes from backend coefficients');
  assert.deepEqual(distance.data.labels, ['5 km 以下', '8–12 km'], 'empty distance bands are skipped');
  assert.deepEqual(distribution.data.labels, ['5:30 以內', '5:45–6:00', '6:45 以上']);
  assert.match(nodes['pace-summary'].innerHTML, /近 30 天平均 <strong>5:47<\/strong>.*1 筆沒有時間/);
  assert.equal(nodes['pace-trend-note'].textContent, '最早 90 天（2025/7/1 起）平均 6:28，最近 90 天 5:52，快了 36 秒/km。');
  assert.match(nodes['pace-monthly-note'].textContent, /前 3 個月平均跑量和當月配速是 -0.84（14 個月）/);
  assert.equal(nodes['pace-load-note'].textContent,
    '前 4 週平均週跑量 10–20 km 時，當週配速中位數 6:21；30–40 km 時是 5:50，快 31 秒/km。趨勢線：週跑量每多 10 km，配速約快 16 秒。相關係數 -0.39（1 週）。');
  assert.equal(nodes['pace-distance-note'].textContent, '8–12 km 平均最快（5:54）；最常跑的是 8–12 km，共 62 次。');
  assert.match(nodes['pace-distribution-note'].textContent, /^配速中位數 6:04；最多的是 5:45–6:00（60 次）/);

  await context.renderPaceAnalysis();
  assert.equal(charts.slice(0, 5).every(chart => chart.destroyed), true, 'a redraw destroys the previous charts');
  assert.match(htmlSource, /<canvas id="chart-pace-trend"><\/canvas>[\s\S]*<canvas id="chart-pace-distribution"><\/canvas>/);
});

test('SPEC-064 an account without times shows a hint instead of charts', async () => {
  const empty = { ...analysis, timed_run_count: 0, untimed_run_count: 4, summary: null, runs: [], rolling: [], monthly: [],
    distance: [], distribution: { bin_seconds: 15, bins: [], median_pace: null } };
  const { context, nodes, charts } = paceAnalysisContext(empty);
  await context.renderPaceAnalysis();
  assert.equal(charts.length, 0);
  assert.match(nodes['pace-summary'].innerHTML, /填上跑步時間.*4 筆沒有時間/);
  assert.equal(nodes['pace-load-note'].textContent, '還沒有填跑步時間的紀錄。');
});

test('SPEC-064 classic scripts never redeclare a top-level name from another script', () => {
  // Classic scripts share one global scope: a repeated const/let/class aborts the later script.
  const { scriptPaths } = require('./helpers.cjs');
  const owners = new Map();
  const duplicates = [];
  for (const file of scriptPaths) {
    for (const match of readText(file).matchAll(/^(?:const|let|class)\s+([A-Za-z_$][\w$]*)/gm)) {
      if (owners.has(match[1])) duplicates.push(`${match[1]}: ${owners.get(match[1])} and ${file}`);
      else owners.set(match[1], file);
    }
  }
  assert.deepEqual(duplicates, []);
});
