// Goal presentation consumes the same backend policy as dashboard and reports.
const goalProgressCache = new Map();
let goalProgressRequestId = 0;
let goalSaveOperation = null;

registerFeatureReset('goal-progress', () => {
  goalProgressCache.clear();
  goalProgressRequestId += 1;
  goalSaveOperation = null;
  document.getElementById('save-goal-btn').disabled = false;
  document.getElementById('goal-settings-status').textContent = '';
});

function goalFormValues(goal) {
  return { 'goal-start-year': String(goal.start_year), 'goal-monthly-km': String(goal.monthly_km) };
}

function prepareGoalForm() {
  const fields = goalFormValues(runningGoal);
  const values = getFormDraft('goal').reconcile(fields, readForm(Object.keys(fields)));
  for (const [id, value] of Object.entries(values)) document.getElementById(id).value = value;
}

function renderGoalProgress() {
  const cards = document.getElementById('goal-cards');
  if (!cards) return;
  prepareGoalForm();
  const year = selectedYear || new Date().getFullYear();
  const now = new Date();
  const rows = monthlyMileages.filter(item => item.year === year);
  if (!selectedGoalMonth) selectedGoalMonth = year === now.getFullYear()
    ? now.getMonth() + 1 : (rows.length ? Math.max(...rows.map(item => item.month)) : 12);
  document.getElementById('goal-month-select').innerHTML = Array.from({ length: 12 }, (_, index) =>
    `<option value="${index + 1}" ${index + 1 === selectedGoalMonth ? 'selected' : ''}>${index + 1} 月</option>`
  ).join('');
  loadGoalProgress(year, selectedGoalMonth);
}

async function loadGoalProgress(year, month) {
  const session = captureAuthSession();
  const requestId = ++goalProgressRequestId;
  const key = `${session.generation}|${runningGoal.version}|${localDateISO()}|${year}-${month}`;
  const cards = document.getElementById('goal-cards');
  if (goalProgressCache.has(key)) { renderGoalCards(goalProgressCache.get(key), year, month); return; }
  cards.innerHTML = '<div class="card"><div class="card-sub">目標進度載入中…</div></div>';
  try {
    const progress = await apiGet(`/running-goal/progress?year=${year}&month=${month}`);
    if (!isCurrentAuthSession(session) || requestId !== goalProgressRequestId || selectedYear !== year || selectedGoalMonth !== month) return;
    goalProgressCache.set(key, progress);
    renderGoalCards(progress, year, month);
  } catch (error) {
    if (error.name === 'AbortError' || !isCurrentAuthSession(session) || requestId !== goalProgressRequestId) return;
    cards.innerHTML = `<div class="card"><div class="card-sub">目標載入失敗：${esc(error.message)}</div><button class="btn btn-sm btn-edit" onclick="renderGoalProgress()">重試</button></div>`;
  }
}

function renderGoalCards(progress, year, month) {
  const cards = document.getElementById('goal-cards');
  if (!progress.active) {
    cards.innerHTML = `<div class="card"><div class="card-label">${year} 年目標</div><div class="card-value">尚未開始</div><div class="card-sub">目標自 ${Number(progress.start_year || runningGoal.start_year)} 年起生效</div></div>`;
    return;
  }
  const monthKm = Number(progress.month_km || 0), yearKm = Number(progress.ytd_km || 0);
  const monthPct = Number(progress.month_achievement_percent || 0), yearPct = Number(progress.year_achievement_percent || 0);
  const monthlyTarget = Number(progress.monthly_km || runningGoal.monthly_km);
  const yearlyTarget = Number(progress.yearly_km || runningGoal.yearly_km);
  const paceText = dashboardGoalSummary(progress);
  cards.innerHTML = `
    <div class="card"><div class="card-label">${year} 年 ${month} 月目標</div>
      <div class="card-value">${monthKm.toFixed(2)} / ${monthlyTarget.toLocaleString(undefined, { maximumFractionDigits: 2 })} km</div>
      <div class="card-sub">達成 ${monthPct.toFixed(1)}% · ${paceText} · 僅計逐筆日誌</div>
      <div class="goal-progress"><span style="width:${Math.max(0, Math.min(100, monthPct))}%"></span></div></div>
    <div class="card"><div class="card-label">${year} 年截至 ${month} 月年度進度</div>
      <div class="card-value">${yearKm.toFixed(2)} / ${yearlyTarget.toLocaleString(undefined, { maximumFractionDigits: 2 })} km</div>
      <div class="card-sub">達成 ${yearPct.toFixed(1)}% · 尚差 ${Number(progress.year_remaining_km || 0).toFixed(2)} km · 僅計逐筆日誌</div>
      <div class="goal-progress"><span style="width:${Math.max(0, Math.min(100, yearPct))}%"></span></div></div>`;
}

function onGoalMonthChange() {
  selectedGoalMonth = Number(document.getElementById('goal-month-select').value) || 1;
  renderGoalProgress();
}

async function saveRunningGoal() {
  if (goalSaveOperation) return;
  const status = document.getElementById('goal-settings-status');
  const payload = {
    expected_version: Number(runningGoal.version || 0),
    start_year: Number(document.getElementById('goal-start-year').value),
    monthly_km: Number(document.getElementById('goal-monthly-km').value),
  };
  if (!Number.isInteger(payload.start_year) || payload.start_year < 1900 || payload.start_year > 2100 ||
      !Number.isFinite(payload.monthly_km) || payload.monthly_km <= 0 || payload.monthly_km > 100000) {
    status.textContent = '請輸入有效的年份與正數里程。';
    return;
  }
  const operation = getFormOperations('goal').begin('save', readForm(Object.keys(goalFormValues(runningGoal))));
  if (!operation) return;
  goalSaveOperation = operation;
  document.getElementById('save-goal-btn').disabled = true;
  try {
    const goal = await apiPut('/running-goal', payload);
    if (goalSaveOperation !== operation || !isCurrentAuthSession(operation.session)) return;
    invalidateDataResources(['goal']);
    const serverValues = goalFormValues(goal);
    const values = getFormDraft('goal').acknowledge(serverValues, operation.form, readForm(Object.keys(serverValues)));
    for (const [id, value] of Object.entries(values)) document.getElementById(id).value = value;
    runningGoal = goal;
    dashboardAnalyticsCache.clear();
    dashboardAnalyticsRequest++;
    goalProgressCache.clear();
    goalProgressRequestId += 1;
    status.textContent = Object.keys(values).some(id => values[id] !== serverValues[id])
      ? '目標已儲存；新的變更尚未儲存。' : '目標已儲存。';
    invalidatePanels();
    renderActivePanel();
  } catch (error) {
    if (error.name === 'AbortError' || goalSaveOperation !== operation || !isCurrentAuthSession(operation.session)) return;
    status.textContent = error.message || '目標儲存失敗。';
  } finally {
    if (getFormOperations('goal').finish('save', operation) && goalSaveOperation === operation) {
      goalSaveOperation = null;
      document.getElementById('save-goal-btn').disabled = false;
    }
  }
}
