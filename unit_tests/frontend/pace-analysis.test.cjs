// SPEC-064 / SPEC-065: race preparation and the pace trend only lay out backend values.
const { test, assert, vm, readText, htmlSource, extract } = require('./helpers.cjs');

const esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function racePrepContext({ race, pace, puts = [], deletes = [] }) {
  const nodes = new Proxy({}, { get: (target, id) => target[id] ||= {
    id, value: '', textContent: '', innerHTML: '', hidden: false, disabled: false, options: [],
    insertAdjacentHTML(_, html) { this.options.push({ value: /value="([^"]*)"/.exec(html)[1] }); },
    setAttribute() {}, focus() {},
  } });
  nodes['race-settings'].hidden = true;
  const charts = [];
  class Chart {
    constructor(canvas, config) { this.canvas = canvas; this.config = config; this.destroyed = false; charts.push(this); }
    destroy() { this.destroyed = true; }
  }
  const reads = [];
  const context = vm.createContext({
    Chart, esc, console: { error() {} }, chartInstances: {}, registerFeatureReset() {},
    getThemeColor: (token, fallback) => fallback, confirm: () => true,
    invalidateDataResources: () => {},
    apiGet: async path => { reads.push(path); return path === '/analytics/race' ? race : pace; },
    apiPut: async (path, payload) => { puts.push({ path, payload }); return { version: 1, ...payload }; },
    apiDelete: async path => { deletes.push(path); return { deleted: true }; },
    document: {
      getElementById: id => nodes[id],
      querySelector: () => ({ dataset: { panel: 'monthly' } }),
    },
  });
  nodes['race-distance'].options = [{ value: '21.0975' }, { value: '10' }, { value: '5' }, { value: '42.195' }];
  vm.runInContext(extract('reviewCard'), context);
  vm.runInContext(readText('frontend/app-pace-charts.js'), context);
  return { context, nodes, charts, reads };
}

const zones = [
  { key: 'easy', label: '輕鬆', min_pace: 386, max_pace: null },
  { key: 'steady', label: '穩定', min_pace: 356, max_pace: 386 },
  { key: 'race', label: '比賽配速', min_pace: 331, max_pace: 356 },
  { key: 'fast', label: '更快', min_pace: null, max_pace: 331 },
];
const goal = { version: 2, race_name: '示範半馬', race_date: '2026-12-13', distance_km: 21.0975, target_seconds: 7200,
  reference_distance_km: 10, reference_seconds: 3120, reference_temperature_c: 28 };
const weekly = Array.from({ length: 12 }, (_, index) => ({
  week_start: new Date(Date.UTC(2026, 7, 31 + index * 7)).toISOString().slice(0, 10),
  km: 30, longest_km: index === 7 ? 16 : 10, partial: index === 11,
}));
const race = {
  as_of: '2026-11-17', goal, days_left: 19, goal_pace: 341, zones,
  prediction: { reference_distance_km: 10, reference_seconds: 3120, reference_pace: 312, reference_temperature_c: 28,
    hot_reference: true, predicted_seconds: 6884, predicted_pace: 326, margin_seconds: 316 },
  intensity: { weeks: 8, total_seconds: 100000, untimed_runs: 1, zones: [
    { key: 'easy', label: '輕鬆', runs: 4, km: 19.9, seconds: 9100, share: 9.1 },
    { key: 'steady', label: '穩定', runs: 7, km: 60, seconds: 24800, share: 24.8 },
    { key: 'race', label: '比賽配速', runs: 15, km: 139.6, seconds: 54100, share: 54.1 },
    { key: 'fast', label: '更快', runs: 5, km: 33.9, seconds: 12000, share: 12 },
  ] },
  long_runs: { weeks: 8, threshold_km: 15.8, target_count: 2, count: 1, runs: [{ date: '2026-10-25', km: 16, pace: 338 }],
    longest_recent: { date: '2026-10-25', km: 16, pace: 338 }, longest_ever: { date: '2025-12-20', km: 21.1, pace: 395 },
    longest_recent_percent: 76, enough: false, last_long_run_by: '2026-11-29', weekly, average_weekly_km: 31.68 },
};
const pace = {
  as_of: '2026-11-17', timed_run_count: 2, untimed_run_count: 1, goal_pace: 341, zones,
  summary: { first_date: '2025-07-01', first_90_days_pace: 388, recent_90_days_pace: 352, recent_30_days_pace: 347 },
  runs: [{ date: '2025-07-01', km: 5.52, pace: 389, zone: 'easy' }, { date: '2026-11-15', km: 13, pace: 335, zone: 'race' }],
  rolling: [{ date: '2025-07-01', pace: 389 }, { date: '2026-11-15', pace: 348 }],
};

test('SPEC-065 race prep shows the backend prediction, long-run gap and intensity mix', async () => {
  const { context, nodes, charts, reads } = racePrepContext({ race, pace });
  await context.renderPaceAnalysis();
  assert.deepEqual([...reads].sort(), ['/analytics/pace', '/analytics/race']);
  assert.deepEqual(charts.map(chart => chart.canvas.id), ['chart-race-long', 'chart-race-intensity', 'chart-pace-trend']);
  const cards = nodes['race-cards'].innerHTML;
  assert.match(cards, /19 天/);
  assert.match(cards, /5:41 <small>\/km<\/small>/);
  assert.match(cards, /1:54:44/);
  assert.match(cards, /比目標快 5:16/);
  assert.match(cards, /28°C，涼爽時通常更快/);
  assert.match(cards, /1 <small>\/ 2 次<\/small>/);
  assert.equal(nodes['race-goal-summary'].textContent, '示範半馬 · 12/13 半馬 目標 2:00:00');
  assert.equal(nodes['race-target'].value, '2:00:00');

  const [long, intensity, trend] = charts.map(chart => chart.config);
  assert.equal(long.data.datasets[0].data[7], 16);
  assert.equal(long.data.datasets[0].data[11], 10, 'a partial week with a run is drawn');
  assert.equal(long.data.datasets[1].data[0], 15.8, 'the threshold line comes from the backend');
  assert.equal(long.data.datasets[2].data[0], 21.0975);
  assert.equal(nodes['race-long-note'].textContent,
    '近 8 週達到 15.8 km（半馬的 75%）的長距離有 1 次，一般建議至少 2 次；最長是 10/25 的 16.0 km（76%）；平均每週 31.7 km。'
    + '長距離偏少：建議在 11/29 前再跑一次 16 km 以上的輕鬆長距離，之後開始減量。');

  assert.equal(intensity.options.indexAxis, 'y');
  assert.deepEqual(JSON.parse(JSON.stringify(intensity.data.datasets[0].data)), [9.1, 24.8, 54.1, 12]);
  assert.deepEqual(JSON.parse(JSON.stringify(intensity.data.labels[0])), ['輕鬆', '6:26 以上']);
  assert.match(nodes['race-intensity-note'].textContent, /^近 8 週輕鬆跑佔 9.1% 的時間，比賽配速或更快佔 66.1%。多數訓練建議約 7～8 成/);

  assert.equal(trend.options.scales.y.reverse, true);
  assert.deepEqual(JSON.parse(JSON.stringify(trend.data.datasets[0].backgroundColor)), ['#2fd8f0', '#c8ff3c'], 'points take their zone color');
  assert.deepEqual(JSON.parse(JSON.stringify(trend.data.datasets[2].data)).map(point => point.y), [341, 341], 'goal pace line');
  assert.match(nodes['pace-trend-note'].textContent, /快了 36 秒\/km。點的顏色是強度/);

  await context.renderPaceAnalysis();
  assert.equal(charts.slice(0, 3).every(chart => chart.destroyed), true, 'a redraw destroys the previous charts');
  assert.match(htmlSource, /id="race-settings"[^>]*data-submit="save-race-goal"/);
  assert.match(htmlSource, /<canvas id="chart-race-long"><\/canvas>[\s\S]*<canvas id="chart-race-intensity"><\/canvas>[\s\S]*<canvas id="chart-pace-trend"><\/canvas>/);
});

test('SPEC-065 inside the last two weeks the advice is to taper, not to add a long run', async () => {
  const late = { ...race, as_of: '2026-12-02', days_left: 11 };
  const { context, nodes } = racePrepContext({ race: late, pace });
  await context.renderPaceAnalysis();
  assert.match(nodes['race-long-note'].textContent, /已進入賽前兩週，不要再補長距離/);
});

test('SPEC-065 without a race goal only the pace trend is drawn and the form invites one', async () => {
  const plain = { ...pace, goal_pace: null, zones: [], runs: pace.runs.map(run => ({ ...run, zone: null })) };
  const { context, nodes, charts } = racePrepContext({ race: { as_of: '2026-11-17', goal: null }, pace: plain });
  await context.renderPaceAnalysis();
  assert.deepEqual(charts.map(chart => chart.canvas.id), ['chart-pace-trend']);
  assert.equal(nodes['race-cards'].innerHTML, '');
  assert.match(nodes['race-long-note'].textContent, /按「設定比賽」/);
  assert.equal(nodes['delete-race-btn'].hidden, true);
  assert.equal(nodes['race-edit-toggle'].textContent, '設定比賽');
  assert.equal(charts[0].config.data.datasets.length, 2, 'no goal pace line');
  assert.match(nodes['pace-trend-note'].textContent, /設定比賽目標後，點會依強度上色/);
});

test('SPEC-065 an account without times shows a hint instead of a pace trend', async () => {
  const empty = { ...pace, timed_run_count: 0, summary: null, runs: [], rolling: [] };
  const { context, nodes, charts } = racePrepContext({ race: { as_of: '2026-11-17', goal: null }, pace: empty });
  await context.renderPaceAnalysis();
  assert.equal(charts.length, 0);
  assert.equal(nodes['pace-trend-note'].textContent, '還沒有填跑步時間的紀錄。');
});

test('SPEC-065 the race form validates its fields and saves the parsed goal', async () => {
  const puts = [];
  const { context, nodes } = racePrepContext({ race, pace, puts });
  context.captureAuthSession = () => ({});
  context.isCurrentAuthSession = () => true;
  const fill = values => Object.entries(values).forEach(([id, value]) => { nodes[id].value = value; });
  fill({ 'race-name': ' 示範半馬 ', 'race-date': '2026-12-13', 'race-distance': '21.0975', 'race-target': '1:59:59',
    'race-ref-distance': '10', 'race-ref-time': '52:00', 'race-ref-temp': '28' });
  await context.saveRaceGoal();
  assert.deepEqual(JSON.parse(JSON.stringify(puts[0])), { path: '/race-goal', payload: {
    expected_version: 0, race_name: '示範半馬', race_date: '2026-12-13', distance_km: 21.0975, target_seconds: 7199,
    reference_distance_km: 10, reference_seconds: 3120, reference_temperature_c: 28 } });
  assert.equal(nodes['race-settings-status'].textContent, '比賽目標已儲存。');

  for (const [values, message] of [
    [{ 'race-date': '' }, /比賽日期/],
    [{ 'race-date': '2026-12-13', 'race-target': '2 小時' }, /目標時間格式/],
    [{ 'race-target': '1:59:59', 'race-ref-time': '' }, /同時填距離與時間/],
    [{ 'race-ref-time': '52:00', 'race-ref-distance': '0.5' }, /至少 1 km/],
  ]) {
    fill(values);
    await context.saveRaceGoal();
    assert.match(nodes['race-settings-status'].textContent, message);
  }
  assert.equal(puts.length, 1, 'invalid forms never reach the API');
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
