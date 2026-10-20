const { test, assert, fs, path, vm, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, transportContext } = require('./helpers.cjs');

test('report streaming distinguishes saved completion from an interrupted response', () => {
  const generateReport = extract('generateReport');
  assert.match(generateReport, /readJsonEventStream\(res/);
  assert.match(generateReport, /receivedDone = true/);
  assert.match(generateReport, /receivedError = true/);
  assert.match(generateReport, /!receivedDone && !receivedError/);
  assert.match(generateReport, /內容不完整且未儲存/);
});

test('running goals are loaded, editable, and rendered as monthly and yearly progress', () => {
  assert.match(source, /apiGet\('\/running-goal'\)/);
  assert.match(source, /apiPut\('\/running-goal', payload\)/);
  assert.match(source, /id="goal-cards"/);
  assert.match(source, /id="goal-month-select"/);
  assert.doesNotMatch(source, /id="goal-yearly-km"/);
  const cards = extract('renderGoalCards');
  assert.match(cards, /progress\.month_achievement_percent/);
  assert.match(cards, /progress\.year_achievement_percent/);
  assert.match(cards, /dashboardGoalSummary\(progress\)/);
  assert.match(extract('loadGoalProgress'), /\/running-goal\/progress\?year=/);
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
  assert.match(loader, /!key\.startsWith\(cachePrefix\)/);
  assert.match(saveGoal, /expected_version: Number\(runningGoal\.version \|\| 0\)/);
  assert.match(saveGoal, /dashboardAnalyticsCache\.clear\(\)/);
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
  const goalProgress = extract('renderGoalCards');
  const insights = extract('renderDashboardInsights');
  assert.match(goalProgress, /progress\.ytd_km/);
  assert.match(goalProgress, /截至 \$\{month\} 月年度進度/);
  assert.match(insights, /較上月同期|comparison\.label/);
  assert.match(insights, /月底預測/);
  assert.doesNotMatch(source, /鞋款輪替建議|年活動熱圖|最近操作與復原|里程資料健康/);
  assert.doesNotMatch(source, /function renderYearHeatmap|function renderOperations|function undoOperation|function repairMileageData/);
  assert.doesNotMatch(source, /apiGet\('\/operations'\)|apiGet\('\/analytics\/reconciliation'\)/);
});
