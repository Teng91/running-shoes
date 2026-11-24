const { test, assert, fs, path, vm, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, reportGenerationSource, transportContext } = require('./helpers.cjs');

test('report streaming distinguishes saved completion from an interrupted response', () => {
  const generateReport = reportGenerationSource();
  assert.match(generateReport, /readJsonEventStream\(res/);
  assert.match(generateReport, /receivedDone = true/);
  assert.match(generateReport, /receivedError = true/);
  assert.match(generateReport, /!report\.receivedDone && !report\.receivedError/);
  assert.match(generateReport, /內容不完整且未儲存/);
});

test('running goals are loaded, editable, and rendered as monthly and yearly progress', () => {
  assert.match(source, /apiGet\('\/running-goal'\)/);
  assert.match(source, /apiPut\('\/running-goal', payload\)/);
  assert.match(source, /id="goal-overview"/);
  assert.doesNotMatch(source, /id="goal-yearly-km"/);
  assert.match(extract('loadGoalProgress'), /\/running-goal\/year\?year=\$\{year\}/);
  assert.match(extract('renderGoalOverview'), /dashboardGoalSummary\(goal\)/);
});

function overviewContext() {
  const nodes = {};
  const context = vm.createContext({ document: { getElementById: id => nodes[id] ||= { innerHTML: '' } } });
  vm.runInContext(['formatGoalKm', 'goalMonthCell', 'goalYearStatus', 'renderGoalOverview', 'dashboardGoalSummary'].map(extract).join('\n'), context);
  return { context, html: () => nodes['goal-overview'].innerHTML };
}

const MONTH_KM = [132.4, 98.6, 140.2, 125, 87.3, 151.9, 126.4, 110.8, 133.1, 45.2, 0, 0];
function annualGoal(overrides = {}) {
  return { active: true, year: 2026, start_year: 2026, monthly_km: 125, yearly_km: 1500, year_state: 'current',
    focus_month: 10, month_km: 45.2, month_state: 'current', month_achievement_percent: 36.2, pace_delta_km: -46.29,
    remaining_days: 8, required_daily_km: 9.98, ytd_km: 1150.9, year_achievement_percent: 76.7,
    year_remaining_km: 349.1, year_expected_km_to_date: 1212.33, year_pace_delta_km: -61.43,
    required_weekly_km: 35.42, months_closed: 9, months_met: 6,
    months: MONTH_KM.map((km, index) => ({ month: index + 1, km, percent: Math.round(km / 1.25 * 10) / 10,
      state: index < 9 ? 'past' : index === 9 ? 'current' : 'future', met: index < 10 && km >= 125 })),
    ...overrides };
}

test('SPEC-044 the annual goal shows twelve month cells instead of a month picker', () => {
  assert.doesNotMatch(htmlSource, /id="goal-month-select"|查看月份<\/label><select id="goal|目標開始年份/);
  assert.match(htmlSource, /<form class="goal-settings" id="goal-settings" hidden/);
  assert.match(htmlSource, /<label for="goal-start-year">從哪一年開始計算<\/label><select id="goal-start-year"|<label for="goal-start-year">從哪一年開始計算<\/label>\s*<select id="goal-start-year"/);
  const { context, html } = overviewContext();
  context.renderGoalOverview(annualGoal());
  const cells = html().match(/<li class="goal-month [^"]+"/g);
  assert.equal(cells.length, 12);
  assert.deepEqual(cells.map(cell => cell.match(/goal-month ([a-z]+)/)[1]),
    ['met', 'missed', 'met', 'met', 'missed', 'met', 'met', 'missed', 'met', 'current', 'future', 'future']);
  assert.match(cells[9], /is-current/);
  assert.match(html(), /<strong>1,150\.9<\/strong> \/ 1,500 km/);
  assert.match(html(), /76\.7%/);
  assert.match(html(), /落後進度 61\.4 km · 年底前還差 349\.1 km，平均每週 35\.4 km/);
  assert.match(html(), /已結束的 9 個月中 6 個月達標/);
  assert.match(html(), /goal-pace-marker" style="left:80\.82%/);
  assert.match(html(), /<strong>10 月<\/strong> 45\.20 \/ 125 km（36\.2%）· 落後 46\.29 km · 剩 8 天 · 每天需 9\.98 km/);
  assert.match(html(), /只計跑步日誌/);
});

test('SPEC-044 past, future and not-yet-tracked years explain their goal state', () => {
  const { context, html } = overviewContext();
  context.renderGoalOverview(annualGoal({ year: 2025, year_state: 'past', ytd_km: 1380.5, year_achievement_percent: 92,
    year_remaining_km: 119.5, months_closed: 12, months_met: 7,
    months: MONTH_KM.map((km, index) => ({ month: index + 1, km: km || 120, percent: 0, state: 'past', met: km >= 125 })) }));
  assert.match(html(), /全年差 119\.5 km 未達標/);
  assert.match(html(), /已結束的 12 個月中 7 個月達標/);
  assert.doesNotMatch(html(), /goal-pace-marker|goal-month-detail|is-current|本月進行中/);
  context.renderGoalOverview(annualGoal({ year: 2025, year_state: 'past', ytd_km: 1600, year_remaining_km: 0 }));
  assert.match(html(), /已達成全年目標，超過 100\.0 km/);
  context.renderGoalOverview(annualGoal({ year: 2027, year_state: 'future', ytd_km: 0, months_closed: 0, months_met: 0,
    months: MONTH_KM.map((_, index) => ({ month: index + 1, km: 0, percent: 0, state: 'future', met: false })) }));
  assert.match(html(), /這一年還沒開始/);
  assert.equal((html().match(/goal-month future/g) || []).length, 12);
  context.renderGoalOverview(annualGoal({ year: 2024, active: false }));
  assert.match(html(), /2024 年不計算目標/);
  assert.match(html(), /目標從 2026 年開始計算/);
  assert.doesNotMatch(html(), /goal-month/);
});

test('SPEC-044 the goal editor offers known years and cancel restores the saved goal', () => {
  const nodes = {};
  const node = id => nodes[id] ||= { id, value: '', textContent: '', innerHTML: '', hidden: false, attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; }, focus() { focused.push(id); } };
  const focused = [];
  const context = vm.createContext({ document: { getElementById: node }, runningGoal: { version: 2, start_year: 2026, monthly_km: 125, yearly_km: 1500 },
    monthlyMileages: [{ year: 2023, month: 5, km: 40 }], persistWorkspaceDrafts() {} });
  vm.runInContext(extract('toggleGoalSettings'), context);
  context.prepareGoalForm();
  assert.equal(nodes['goal-start-year'].value, '2026');
  const years = [...nodes['goal-start-year'].innerHTML.matchAll(/value="(\d+)"/g)].map(match => Number(match[1]));
  const thisYear = new Date().getFullYear();
  assert.equal(years[0], 2023, 'years with history can become the start year');
  assert.equal(years.at(-1), Math.max(thisYear + 1, 2026));
  assert.match(nodes['goal-target-summary'].textContent, /每月 125 km · 全年 1,500 km/);
  assert.match(nodes['goal-yearly-hint'].textContent, /全年 1,500 km/);
  context.toggleGoalSettings(true);
  assert.equal(nodes['goal-settings'].hidden, false);
  assert.equal(nodes['goal-edit-toggle'].hidden, true);
  assert.equal(nodes['goal-edit-toggle'].attributes['aria-expanded'], 'true');
  assert.deepEqual(focused, ['goal-monthly-km']);
  nodes['goal-monthly-km'].value = '160';
  context.prepareGoalForm();
  assert.equal(nodes['goal-monthly-km'].value, '160', 'redraw keeps the draft');
  context.toggleGoalSettings(false);
  assert.equal(nodes['goal-monthly-km'].value, '125', 'cancel restores the saved goal');
  assert.equal(nodes['goal-settings'].hidden, true);
  assert.equal(nodes['goal-edit-toggle'].attributes['aria-expanded'], 'false');
  assert.deepEqual(focused, ['goal-monthly-km', 'goal-edit-toggle']);
  context.prepareGoalForm();
  assert.equal(nodes['goal-settings'].hidden, true, 'a clean form stays collapsed');
  context.setGoalField('goal-start-year', '2019');
  assert.match(nodes['goal-start-year'].innerHTML, /<option value="2019">2019 年<\/option>/, 'a restored draft year stays selectable');
  assert.doesNotMatch(nodes['goal-start-year'].innerHTML, /value="0"|value="1899"/);
  context.prepareGoalForm();
  assert.equal(nodes['goal-start-year'].value, '2019');
  assert.equal(nodes['goal-settings'].hidden, false, 'a restored draft opens the editor');
});

test('dashboard monthly goal shows whether current progress is ahead or behind', () => {
  const context = vm.createContext({});
  vm.runInContext(extract('dashboardGoalSummary'), context);
  assert.equal(
    context.dashboardGoalSummary({ active: true, month_state: 'current',
      pace_delta_km: 3, remaining_days: 19, required_daily_km: 3.87 }),
    '超前 3.00 km · 剩 19 天 · 每天需 3.87 km',
  );
  assert.equal(
    context.dashboardGoalSummary({ active: true, month_state: 'current',
      pace_delta_km: -8.25, remaining_days: 12, required_daily_km: 5.5 }),
    '落後 8.25 km · 剩 12 天 · 每天需 5.50 km',
  );
  assert.equal(
    context.dashboardGoalSummary({ active: true, month_state: 'past',
      month_remaining_km: 10 }),
    '月底結算，未達目標 10.00 km',
  );
  const insights = extract('renderDashboardInsights');
  assert.match(insights, /dashboardGoalSummary\(goal\)/);
});

test('dashboard analytics cache expires by local date and goals invalidate it', () => {
  const loader = extract('loadDashboardAnalytics');
  const saveGoal = extract('saveRunningGoal');
  assert.match(loader, /const cachePrefix = `\$\{session\.generation\}\|\$\{localDateISO\(\)\}\|`/);
  assert.match(loader, /const cacheKey = `\$\{cachePrefix\}\$\{month\}`/);
  assert.match(loader, /resourceStore\.read\('dashboard-analytics'/);
  assert.match(saveGoal, /expected_version: Number\(coreData\.runningGoal\.version \|\| 0\)/);
  assert.match(saveGoal, /invalidateDataResources\(\['goal', 'goal-progress', 'dashboard-analytics'\]\)/);
});

test('every JSON and upload helper ignores a previous session 401', async () => {
  for (const call of [
    ctx => ctx.apiGet('/test'), ctx => ctx.apiPost('/test', {}),
    ctx => ctx.apiPut('/test', {}), ctx => ctx.apiDelete('/test'),
    ctx => ctx.apiUpload('/test', new Blob(['test']), { mapping: '{}' }),
  ]) {
    const context = transportContext();
    let finish;
    context.fetch = () => new Promise(resolve => { finish = resolve; });
    const request = call(context);
    context.switchSession('B');
    finish({ status: 401 });
    await assert.rejects(request, { name: 'AbortError' });
    assert.equal(context.activeToken(), 'B');
    assert.equal(context.clearCalls, 0);
    assert.equal(context.loginCalls, 0);
  }
});

test('late JSON bodies and network errors cannot return old session data', async () => {
  const context = transportContext();
  let finishBody;
  const reading = new Promise(resolve => {
    context.fetch = async () => ({ status: 200, ok: true, json: () => {
      resolve();
      return new Promise(finish => { finishBody = finish; });
    } });
  });
  const request = context.apiGet('/test');
  await reading;
  context.switchSession('B');
  finishBody({ private: 'A' });
  await assert.rejects(request, { name: 'AbortError' });
  let fail;
  context.fetch = () => new Promise((_, reject) => { fail = reject; });
  const failed = context.apiGet('/test');
  context.switchSession('C');
  fail(new TypeError('offline'));
  await assert.rejects(failed, { name: 'AbortError' });
  assert.equal(context.activeToken(), 'C');
});

test('current 401 expires login, but an identical token from a new session is protected', async () => {
  const context = transportContext();
  let finish;
  context.fetch = () => new Promise(resolve => { finish = resolve; });
  const request = context.apiGet('/test');
  context.switchSession('A');
  finish({ status: 401 });
  await assert.rejects(request, { name: 'AbortError' });
  assert.equal(context.activeToken(), 'A');
  context.fetch = async () => ({ status: 401 });
  await assert.rejects(context.apiGet('/test'), /登入已過期/);
  assert.equal(context.activeToken(), null);
  assert.equal(context.clearCalls, 1);
  assert.equal(context.loginCalls, 1);
});

test('selected-month YTD and forecast remain without removed dashboard features', () => {
  const goalProgress = extract('renderGoalOverview');
  const insights = extract('renderDashboardInsights');
  assert.match(goalProgress, /goal\.ytd_km/);
  assert.match(goalProgress, /goal\.months\.map\(goalMonthCell\)/);
  assert.match(insights, /較上月同期|comparison\.label/);
  assert.match(insights, /月底預測/);
  assert.doesNotMatch(source, /鞋款輪替建議|年活動熱圖|最近操作與復原|里程資料健康/);
  assert.doesNotMatch(source, /function renderYearHeatmap|function renderOperations|function undoOperation|function repairMileageData/);
  assert.doesNotMatch(source, /apiGet\('\/operations'\)|apiGet\('\/analytics\/reconciliation'\)/);
});

test('SPEC-044 month cells use twelve columns on desktop and two rows of six when narrow', () => {
  assert.match(styleSource, /\.goal-months \{[^}]*grid-template-columns: repeat\(12, minmax\(0, 1fr\)\)/);
  assert.match(styleSource, /@media \(max-width: 760px\), \(min-width: 801px\) and \(max-width: 940px\) \{\n  \.goal-months \{ grid-template-columns: repeat\(6, minmax\(0, 1fr\)\); \}/);
  assert.match(styleSource, /\.goal-settings\[hidden\] \{ display: none; \}/);
});
