// SPEC-064 / SPEC-065: race preparation and the pace trend only lay out backend values.
const { test, assert, vm, readText, htmlSource, extract } = require('./helpers.cjs');

const esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// SPEC-127: the plan view is a native module; the test VM cannot import, so it is installed directly.
let racePlanModule;
require('node:test').before(async () => {
  racePlanModule = await import('../../frontend/runtime/race-plan-view.mjs');
});

function racePrepContext({ race, pace, bests = null, puts = [], deletes = [] }) {
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
    invalidateDataResources: () => {}, localDateISO: () => '2026-11-17',
    apiGet: async path => {
      reads.push(path);
      return { '/analytics/race': race, '/analytics/personal-bests': bests }[path] || pace;
    },
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
  vm.runInContext(readText('frontend/app-race-goal.js'), context);
  context.installedRacePlanModule = racePlanModule;
  vm.runInContext('racePlanModule = installedRacePlanModule;', context);
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

const plan = {
  weeks_total: 12, weeks_chosen: true, default_weeks: 12, weeks_until_race: 9, start_date: '2026-09-21', started: true, baseline_km: 12.4, baseline_start: '2026-08-24', baseline_end: '2026-09-20',
  peak_km: 22, longest_planned_km: 11, long_threshold_km: 15.8, long_below_threshold: true, weeks_done: 1, weeks_past: 3,
  weeks: [
    { week: 1, week_start: '2026-09-21', phase: 'build', km: 15, long_km: 7, zone_runs: { easy: 2, steady: 1, race: 0, fast: 0 }, actual_km: 15.2, actual_longest_km: 7, status: 'done' },
    { week: 2, week_start: '2026-09-28', phase: 'build', km: 17, long_km: 8, zone_runs: { easy: 0, steady: 0, race: 0, fast: 0 }, actual_km: 11, actual_longest_km: 5, status: 'partial' },
    { week: 3, week_start: '2026-10-05', phase: 'build', km: 18, long_km: 9, zone_runs: { easy: 0, steady: 0, race: 0, fast: 0 }, actual_km: 4, actual_longest_km: 4, status: 'missed' },
    { week: 4, week_start: '2026-10-12', phase: 'recovery', km: 15, long_km: 7, zone_runs: { easy: 0, steady: 0, race: 0, fast: 0 }, actual_km: 6.5, actual_longest_km: 6.5, status: 'current' },
    { week: 5, week_start: '2026-10-19', phase: 'taper', km: 15, long_km: 8, zone_runs: { easy: 0, steady: 0, race: 0, fast: 0 }, actual_km: 0, actual_longest_km: 0, status: 'upcoming' },
    { week: 6, week_start: '2026-10-26', phase: 'race', km: 28, long_km: 21.1, zone_runs: { easy: 0, steady: 0, race: 0, fast: 0 }, actual_km: 0, actual_longest_km: 0, status: 'upcoming' },
  ],
};

test('SPEC-124 the plan compares actual runs per zone with the suggested quality runs', async () => {
  const quality = [{ steady: 1, race: 1 }, { race: 1 }, null, { race: 1 }, { race: 1 }, {}];
  const suggested = { ...plan, weeks: plan.weeks.map((week, index) => ({ ...week,
    quality_runs: quality[index] && { easy: 0, steady: 0, race: 0, fast: 0, ...quality[index] } })) };
  const { context, nodes } = racePrepContext({ race: { ...race, plan: suggested }, pace });
  await context.renderPaceAnalysis();
  const rows = nodes['race-plan-table'].innerHTML.split('</tr>').filter(row => row.includes('<tr'));
  assert.match(rows[0], /<span class="race-plan-zone"><i[^>]*><\/i>輕鬆 2\/0<\/span><span class="race-plan-zone race-plan-zone-met"><i[^>]*><\/i>穩定 1\/1<\/span><span class="race-plan-zone"><i[^>]*><\/i>比賽配速 0\/1<\/span><\/td>/);
  assert.doesNotMatch(rows[0], /更快/, 'a zone with neither runs nor a suggestion is left out');
  assert.match(rows[1], /比賽配速 0\/1/);
  assert.match(rows[2], /<td>—<\/td>\s*<td><span class="race-plan-status">未達/, 'a week without suggestions or timed runs shows a dash');
  assert.match(rows[4], /減量[\s\S]*>—<\/td>\s*<td><span class="race-plan-zone"><i[^>]*><\/i>比賽配速 0\/1<\/span><\/td>/, 'an upcoming week uses the same actual/suggested format');
  assert.match(rows[5], /比賽週[\s\S]*<td>—<\/td>/);
  assert.match(nodes['race-plan-note'].textContent, /還差 8\.5 km。強度建議：比賽配速 1 次（5:31–5:56），其餘輕鬆跑。課表從/);
});

test('SPEC-119 the weekly plan lays out backend targets, actual distance and status', async () => {
  const { context, nodes } = racePrepContext({ race: { ...race, plan }, pace });
  await context.renderPaceAnalysis();
  assert.equal(nodes['race-plan'].hidden, false);
  const rows = nodes['race-plan-table'].innerHTML.split('</tr>').filter(row => row.includes('<tr'));
  assert.equal(rows.length, 6);
  assert.match(rows[0], /class="race-plan-done"[\s\S]*第 1 週[\s\S]*9\/21[\s\S]*累積[\s\S]*>15<[\s\S]*15\.2<small> · 最長 7\.0<\/small>[\s\S]*輕鬆 2\/0<\/span>[\s\S]*穩定 1\/0<\/span><\/td>[\s\S]*達成/);
  assert.doesNotMatch(rows[0], /比賽配速 0|更快 0/, 'zones without runs are left out');
  assert.match(rows[1], /部分完成/);
  assert.match(rows[2], /class="race-plan-missed"[\s\S]*<td>—<\/td>[\s\S]*未達/, 'a week without timed runs shows a dash');
  assert.match(rows[3], /class="race-plan-current race-plan-light"[\s\S]*恢復週[\s\S]*本週/);
  assert.match(rows[4], /減量[\s\S]*>—<\/td>\s*<td>—<\/td>\s*<td><\/td>/, 'an upcoming week has no actual distance, zones or status');
  assert.match(rows[5], /比賽週[\s\S]*比賽 21\.1/);
  assert.equal(nodes['race-plan-note'].textContent,
    '本週是第 4 週（恢復週）：建議 15 km、最長一次 7 km，已跑 6.5 km，還差 8.5 km。課表從 9/21 開始共 12 週，已過 3 週、達成 1 週。起點是 8/24–9/20 平均每週 12.4 km，不到 15 km 以 15 km 起算，'
    + '每週最多加 10%，每 4 週一次恢復週，最後減量進入比賽週。輕鬆跑配速 6:26 以上；強度欄是「實際／建議」次數：每週 1 次比賽配速跑，'
    + '累積期跑量夠時再加 1 次更快或穩定的跑步，其餘輕鬆跑，比賽週只有比賽；每次有填時間的路跑依平均配速歸到下方強度分布的區間。'
    + '達到建議跑量與最長一次的 9 成算達成。依目前跑量，課表最長只排到 11 km，不到比賽距離 75% 的 15.8 km；'
    + '可以考慮選較晚的比賽或較短的距離。');

  // SPEC-122: a plan that has not started says which longer plan or weekly base reaches the threshold.
  const options = racePrepContext({ race: { ...race, plan: { ...plan, started: false, long_weeks_needed: 9, long_base_needed_km: 48 } }, pace });
  await options.context.renderPaceAnalysis();
  assert.match(options.nodes['race-plan-note'].textContent,
    /不到比賽距離 75% 的 15\.8 km；把課表拉長到 9 週（按「調整比賽」），或先把平常週跑量提高到約 48 km，就排得到。$/);
  const baseOnly = racePrepContext({ race: { ...race, plan: { ...plan, started: false, long_weeks_needed: null, long_base_needed_km: 42 } }, pace });
  await baseOnly.context.renderPaceAnalysis();
  assert.match(baseOnly.nodes['race-plan-note'].textContent, /15\.8 km；先把平常週跑量提高到約 42 km，就排得到。$/);

  // SPEC-123: a lowered week is marked and the note says the weeks ahead restart from what was run.
  const lowered = { ...plan, weeks: plan.weeks.map(week => ({ ...week, adjusted: week.week === 4 })) };
  const adapted = racePrepContext({ race: { ...race, plan: lowered }, pace });
  await adapted.context.renderPaceAnalysis();
  const adaptedRows = adapted.nodes['race-plan-table'].innerHTML.split('</tr>');
  assert.match(adaptedRows[3], /恢復週<small> · 已調降<\/small>/);
  assert.doesNotMatch(adaptedRows[2], /已調降/);
  assert.match(adapted.nodes['race-plan-note'].textContent, /前兩週不到建議跑量的 6 成，第 4 週起改從實際跑量重新累積，之後的週跟著調整，已開始的週不變。/);

  // A goal saved before plan lengths existed keeps the default and says how to change it.
  const legacy = racePrepContext({ race: { ...race, plan: { ...plan, weeks_chosen: false } }, pace });
  await legacy.context.renderPaceAnalysis();
  assert.match(legacy.nodes['race-plan-note'].textContent, /課表週數沿用半馬預設的 12 週；按「調整比賽」可以改成 4～24 週，例如從本週開始的 9 週。/);

  const upcoming = { ...plan, started: false, baseline_km: 30, long_below_threshold: false,
    weeks: plan.weeks.map(week => ({ ...week, status: 'upcoming' })) };
  const later = racePrepContext({ race: { ...race, plan: upcoming }, pace });
  await later.context.renderPaceAnalysis();
  assert.match(later.nodes['race-plan-note'].textContent, /^課表會從 9\/21 開始，共 12 週。起點是 8\/24–9\/20 平均每週 30\.0 km，每週/);

  const none = racePrepContext({ race: { ...race, plan: null }, pace });
  await none.context.renderPaceAnalysis();
  assert.equal(none.nodes['race-plan'].hidden, true);
  assert.equal(none.nodes['race-plan-table'].innerHTML, '');
});

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

test('SPEC-127 the plan view module lays out a plan without the DOM and a stale render writes nothing', async () => {
  const format = { esc, paceClock: () => '6:26', zoneColor: () => 'red', zoneRangeText: () => '5:31–5:56',
    raceShortDate: iso => iso.slice(5), raceDistanceName: () => '半馬' };
  assert.equal(racePlanModule.racePlanView({ ...race, plan: null }, format), null);
  const view = racePlanModule.racePlanView({ ...race, plan }, format);
  assert.equal(view.rows.split('</tr>').filter(row => row.includes('<tr')).length, 6);
  assert.match(view.rows, /<td>09-21<\/td>/, 'dates come from the injected formatter');
  assert.match(view.note, /^本週是第 4 週（恢復週）/);
  assert.ok(Object.isFrozen(racePlanModule.RACE_PLAN_PHASES));
  assert.doesNotMatch(readText('frontend/runtime/race-plan-view.mjs'), /document|window|fetch\(/);

  const { context, nodes } = racePrepContext({ race: { ...race, plan }, pace });
  nodes['race-plan-table'].innerHTML = 'kept';
  await context.renderRacePlan({ ...race, plan }, -1);
  assert.equal(nodes['race-plan-table'].innerHTML, 'kept', 'a superseded request leaves the plan alone');
});

test('SPEC-132 the plan module is imported while the page loads and retried after a failed load', async () => {
  // Every other native module is imported at startup; the plan view must not wait for a later deployment.
  assert.match(readText('frontend/app-pace-charts.js'), /^let racePlanModuleLoading = loadRacePlanModule\(\);$/m);
  const { context, nodes } = racePrepContext({ race: { ...race, plan }, pace });
  vm.runInContext('racePlanModule = null; racePlanModuleLoading = Promise.resolve(null); loadRacePlanModule = () => { racePlanModule = installedRacePlanModule; return Promise.resolve(racePlanModule); };', context);
  await context.renderRacePlan({ ...race, plan }, vm.runInContext('racePrepRequestId', context));
  assert.equal(nodes['race-plan'].hidden, false, 'a failed first load is tried again');
  vm.runInContext('racePlanModule = null; racePlanModuleLoading = Promise.resolve(null); loadRacePlanModule = () => Promise.resolve(null);', context);
  await assert.rejects(context.renderRacePlan({ ...race, plan }, 0), /課表模組載入失敗/);
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
    reference_distance_km: 10, reference_seconds: 3120, reference_temperature_c: 28, plan_weeks: 4 } });
  assert.equal(nodes['race-settings-status'].textContent, '比賽目標已儲存。');
  // SPEC-119: a blank plan length starts this week (four weeks before 12/13); a typed one is kept.
  context.updateRacePlanHint();
  assert.equal(nodes['race-plan-weeks'].placeholder, '4');
  assert.equal(nodes['race-plan-weeks-hint'].textContent, '距離比賽還有 4 週；留白排 4 週，從本週開始。');
  fill({ 'race-date': '2027-04-25', 'race-distance': '42.195' });
  context.updateRacePlanHint();
  assert.equal(nodes['race-plan-weeks-hint'].textContent, '距離比賽還有 23 週；留白排 16 週，比賽前 16 週開始。');
  fill({ 'race-plan-weeks': '10' });
  await context.saveRaceGoal();
  assert.equal(puts[1].payload.plan_weeks, 10);
  fill({ 'race-date': '2026-12-13', 'race-distance': '21.0975', 'race-plan-weeks': '' });

  for (const [values, message] of [
    [{ 'race-date': '' }, /比賽日期/],
    [{ 'race-date': '2026-12-13', 'race-target': '2 小時' }, /目標時間格式/],
    [{ 'race-target': '1:59:59', 'race-ref-time': '' }, /同時填距離與時間/],
    [{ 'race-ref-time': '52:00', 'race-ref-distance': '0.5' }, /至少 1 km/],
    [{ 'race-ref-distance': '10', 'race-plan-weeks': '3' }, /課表週數請填 4～24/],
    [{ 'race-plan-weeks': '8.5' }, /課表週數請填 4～24/],
  ]) {
    fill(values);
    await context.saveRaceGoal();
    assert.match(nodes['race-settings-status'].textContent, message);
  }
  assert.equal(puts.length, 2, 'invalid forms never reach the API');
});

// SPEC-136: the backend ranks the bests; a longer run holds a shorter best at its average pace.
const bests = { as_of: '2026-11-17', top_count: 3, distances: [
  { key: '5k', label: '5K', distance_km: 5, bests: [
    { rank: 1, seconds: 1350, pace: 270, date: '2026-04-03', run_km: 4.97, from_longer_run: false, shoe: 'Mizuno <b>Sky</b>' },
    { rank: 2, seconds: 1375, pace: 275, date: '2026-04-05', run_km: 5.02, from_longer_run: false, shoe: 'Mizuno Sky' },
    { rank: 3, seconds: 1400, pace: 280, date: '2026-03-01', run_km: 21.1, from_longer_run: true, shoe: 'Mizuno Sky' },
  ] },
  { key: '10k', label: '10K', distance_km: 10, bests: [] },
  { key: '15k', label: '15K', distance_km: 15, bests: [] },
  { key: 'half', label: '半馬', distance_km: 21.0975, bests: [
    { rank: 1, seconds: 5907, pace: 280, date: '2026-03-01', run_km: 25, from_longer_run: true, shoe: 'Mizuno Sky' },
  ] },
] };

test('SPEC-136 personal bests lay out the backend ranking, the runners-up and the source run', async () => {
  const { context, nodes, reads } = racePrepContext({ race, pace, bests });
  await context.renderPersonalBests();
  assert.deepEqual(reads, ['/analytics/personal-bests']);
  const cards = nodes['personal-bests'].innerHTML.split('<div class="review-card').slice(1);
  assert.equal(cards.length, 4, 'one card per distance, in the backend order');
  const [five, ten, , half] = cards;
  assert.match(five, /review-label">5K<\/div><div class="review-value">22:30<\/div>/);
  // v5.3.1: every result names its run's distance, about the distance or longer alike.
  assert.match(five, /4:30 \/km · 2026\/4\/3 · 5\.0 km<br>Mizuno &lt;b&gt;Sky&lt;\/b&gt;<\/div>/, 'the shoe name is escaped');
  assert.match(five, /<ol class="pb-others"><li><span>2\. 22:55<\/span><span>2026\/4\/5 · 5\.0 km<\/span><\/li><li><span>3\. 23:20<\/span><span>2026\/3\/1 · 21\.1 km<\/span><\/li><\/ol>/);
  assert.match(five, /data-click="use-personal-best" data-km="5" data-seconds="1350" data-label="5K">設為比賽參考成績<\/button>/);
  assert.match(ten, /review-value">—<\/div><div class="review-sub">還沒有 10 km 以上、有時間的路跑<\/div>/);
  assert.doesNotMatch(ten, /button/, 'nothing to hand to the race form');
  assert.match(half, /1:38:27<\/div><div class="review-sub">4:40 \/km · 2026\/3\/1 · 25\.0 km<br>/);
  assert.match(half, /data-km="21\.0975" data-seconds="5907" data-label="半馬"/);
  assert.doesNotMatch(half, /pb-others/);

  // Cached until the shoes or runs arrive again, as after a run is saved or a shoe renamed.
  await context.renderPersonalBests();
  assert.equal(reads.length, 1);
  context.resourceStore.accept([await context.resourceStore.read('shoes', { loader: async () => [] })], 'run');
  await context.renderPersonalBests();
  assert.equal(reads.length, 2);
  assert.match(htmlSource, /id="pb-title"[^>]*>個人最佳<\/h2>[\s\S]*id="personal-bests"[\s\S]*id="race-title"/, 'above race prep');
});

test('SPEC-136 a personal best fills the race form reference result and saves nothing', async () => {
  const puts = [];
  const { context, nodes } = racePrepContext({ race, pace, bests, puts });
  await context.renderPaceAnalysis();
  assert.equal(nodes['race-ref-temp'].value, '28');
  context.usePersonalBest({ dataset: { km: '5', seconds: '1350', label: '5K' } });
  assert.equal(nodes['race-settings'].hidden, false, 'the closed form opens');
  assert.deepEqual(['race-ref-distance', 'race-ref-time', 'race-ref-temp'].map(id => nodes[id].value), ['5', '22:30', '']);
  assert.equal(nodes['race-target'].value, '2:00:00', 'the rest of the goal stays');
  assert.equal(nodes['race-settings-status'].textContent, '已帶入 5K 個人最佳 22:30 當參考成績，按「儲存」後更新預估完賽。');

  // While the form is open, only the reference changes; what the user typed stays.
  nodes['race-target'].value = '1:55:00';
  context.usePersonalBest({ dataset: { km: '21.0975', seconds: '5907', label: '半馬' } });
  assert.deepEqual(['race-ref-distance', 'race-ref-time', 'race-target'].map(id => nodes[id].value), ['21.0975', '1:38:27', '1:55:00']);
  context.usePersonalBest({ dataset: { km: '', seconds: '5907', label: '半馬' } });
  assert.equal(nodes['race-ref-distance'].value, '21.0975', 'a malformed button changes nothing');
  assert.equal(puts.length, 0, 'nothing is saved until 儲存');
  assert.match(readText('frontend/app-race-goal.js'), /'use-personal-best': element => usePersonalBest\(element\)/);
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
