// Goal presentation consumes the same backend policy as dashboard and reports.
let goalProgressRequestId = 0;
let goalSaveOperation = null;

registerFeatureReset('goal-progress', () => {
  resourceStore?.invalidate(['goal-progress']);
  goalProgressRequestId += 1;
  goalSaveOperation = null;
  document.getElementById('save-goal-btn').disabled = false;
  document.getElementById('goal-settings-status').textContent = '';
  setGoalSettingsOpen(false);
});

function goalFormValues(goal) {
  return { 'goal-start-year': String(goal.start_year), 'goal-monthly-km': String(goal.monthly_km) };
}

function formatGoalKm(value, digits = 1) {
  return Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

// Years with history, the saved start year and next year; a draft year is always kept selectable.
function goalStartYearOptions(selected) {
  const current = appCalendarDate().year;
  const known = [...coreData.monthlyMileages.map(item => item.year), coreData.runningGoal.start_year, current, Number(selected || NaN)]
    .filter(year => Number.isInteger(year) && year >= 1900 && year <= 2100);
  const first = Math.min(...known), last = Math.max(current + 1, ...known);
  return Array.from({ length: last - first + 1 }, (_, index) => first + index);
}

function setGoalField(id, value) {
  const field = document.getElementById(id);
  if (id === 'goal-start-year') {
    field.innerHTML = goalStartYearOptions(value).map(year => `<option value="${year}">${year} 年</option>`).join('');
  }
  field.value = value;
}

function prepareGoalForm() {
  const fields = goalFormValues(coreData.runningGoal);
  const values = getFormDraft('goal').reconcile(fields, readForm(Object.keys(fields)));
  for (const [id, value] of Object.entries(values)) setGoalField(id, value);
  // An unsaved draft (typed earlier, restored from this device) stays visible.
  if (Object.keys(fields).some(id => values[id] !== fields[id])) setGoalSettingsOpen(true);
  updateGoalYearlyHint();
  const summary = document.getElementById('goal-target-summary');
  summary.textContent = `每月 ${Number(coreData.runningGoal.monthly_km).toLocaleString()} km · 全年 ${Number(coreData.runningGoal.yearly_km ?? coreData.runningGoal.monthly_km * 12).toLocaleString()} km`;
}

function updateGoalYearlyHint() {
  const monthly = Number(document.getElementById('goal-monthly-km').value);
  document.getElementById('goal-yearly-hint').textContent = Number.isFinite(monthly) && monthly > 0
    ? `全年 ${(monthly * 12).toLocaleString(undefined, { maximumFractionDigits: 2 })} km` : '';
}

function setGoalSettingsOpen(open) {
  const form = document.getElementById('goal-settings');
  const toggle = document.getElementById('goal-edit-toggle');
  form.hidden = !open;
  toggle.hidden = open;
  toggle.setAttribute('aria-expanded', String(open));
}

function toggleGoalSettings(open) {
  if (open) {
    document.getElementById('goal-settings-status').textContent = '';
    setGoalSettingsOpen(true);
    document.getElementById('goal-monthly-km').focus();
    return;
  }
  // Cancel discards the unsaved draft and returns to the saved goal.
  getFormDraft('goal').reset();
  prepareGoalForm();
  if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
  setGoalSettingsOpen(false);
  document.getElementById('goal-edit-toggle').focus();
}

function renderGoalProgress() {
  const target = document.getElementById('goal-overview');
  if (!target) return;
  prepareGoalForm();
  loadGoalProgress(selectedYear || appCalendarDate().year);
}

async function loadGoalProgress(year) {
  const session = captureAuthSession();
  const requestId = ++goalProgressRequestId;
  const key = `${session.generation}|${coreData.runningGoal.version}|${localDateISO()}|${year}`;
  const target = document.getElementById('goal-overview');
  target.innerHTML = '<div class="goal-card"><div class="card-sub">目標進度載入中…</div></div>';
  try {
    const result = await resourceStore.read('goal-progress', { key, refresh: false,
      loader: async () => {
        const value = await apiGet(`/running-goal/year?year=${year}`);
        if (value?.year !== year || !Array.isArray(value.months)) throw new Error('年度目標資料格式錯誤');
        return value;
      } });
    if (!resourceStore.current(result)) return;
    if (result.status === 'rejected') throw result.error;
    if (!isCurrentAuthSession(session) || requestId !== goalProgressRequestId || selectedYear !== year) return;
    renderGoalOverview(result.value);
  } catch (error) {
    if (error.name === 'AbortError' || !isCurrentAuthSession(session) || requestId !== goalProgressRequestId) return;
    target.innerHTML = `<div class="goal-card"><div class="card-sub">目標載入失敗：${esc(error.message)}</div><button class="btn btn-sm btn-edit" data-click="render-goal-progress">重試</button></div>`;
  }
}

function goalMonthCell(row) {
  const percent = Number(row.percent || 0);
  const km = Number(row.km || 0);
  let state, status;
  if (row.state === 'future') { state = 'future'; status = '尚未開始'; }
  else if (row.met) { state = 'met'; status = row.state === 'current' ? '本月已達標' : '達標'; }
  else if (row.state === 'current') { state = 'current'; status = `進行中，達成 ${percent.toFixed(1)}%`; }
  else { state = 'missed'; status = `未達標，達成 ${percent.toFixed(1)}%`; }
  const label = `${row.month} 月 ${km.toFixed(2)} km，${status}`;
  return `<li class="goal-month ${state}${row.state === 'current' ? ' is-current' : ''}" title="${label}">
    <span class="goal-month-name">${row.month}月</span>
    <span class="goal-month-km" aria-hidden="true">${row.state === 'future' ? '—' : Math.round(km)}</span>
    <span class="goal-month-bar" aria-hidden="true"><span style="width:${Math.max(0, Math.min(100, percent))}%"></span></span>
    <span class="visually-hidden">${label}</span>
  </li>`;
}

function goalYearStatus(goal) {
  const remaining = Number(goal.year_remaining_km || 0);
  const over = Math.max(0, Number(goal.ytd_km || 0) - Number(goal.yearly_km || 0));
  if (goal.year_state === 'future') return '這一年還沒開始';
  if (remaining <= 0) return `已達成全年目標${over > 0 ? `，超過 ${formatGoalKm(over)} km` : ''}`;
  if (goal.year_state === 'past') return `全年差 ${formatGoalKm(remaining)} km 未達標`;
  const delta = Number(goal.year_pace_delta_km || 0);
  const weekly = goal.required_weekly_km == null ? '' : `，平均每週 ${formatGoalKm(goal.required_weekly_km)} km`;
  return `${delta >= 0 ? '超前' : '落後'}進度 ${formatGoalKm(Math.abs(delta))} km · 年底前還差 ${formatGoalKm(remaining)} km${weekly}`;
}

function renderGoalOverview(goal) {
  const target = document.getElementById('goal-overview');
  const year = Number(goal.year);
  if (!goal.active) {
    target.innerHTML = `<div class="goal-card goal-card-inactive">
      <div class="goal-inactive-title">${year} 年不計算目標</div>
      <div class="card-sub">目標從 ${Number(goal.start_year)} 年開始計算；想追蹤這一年，請在「調整目標」把開始年份往前調。</div></div>`;
    return;
  }
  const yearlyTarget = Number(goal.yearly_km || 0);
  const yearPct = Number(goal.year_achievement_percent || 0);
  const expectedPct = yearlyTarget > 0 ? Number(goal.year_expected_km_to_date || 0) / yearlyTarget * 100 : 0;
  const marker = goal.year_state === 'current'
    ? `<span class="goal-pace-marker" style="left:${Math.max(0, Math.min(100, expectedPct)).toFixed(2)}%" title="今天應累計 ${formatGoalKm(goal.year_expected_km_to_date)} km"></span>` : '';
  const monthsSummary = goal.months_closed > 0
    ? `已結束的 ${goal.months_closed} 個月中 ${goal.months_met} 個月達標` : '';
  const current = goal.year_state === 'current'
    ? `<p class="goal-month-detail"><strong>${goal.focus_month} 月</strong> ${formatGoalKm(goal.month_km, 2)} / ${Number(goal.monthly_km).toLocaleString()} km（${Number(goal.month_achievement_percent || 0).toFixed(1)}%）· ${dashboardGoalSummary(goal)}</p>` : '';
  target.innerHTML = `<div class="goal-card">
    <div class="goal-hero">
      <div class="goal-hero-main">
        <div class="goal-hero-value"><strong>${formatGoalKm(goal.ytd_km)}</strong> / ${yearlyTarget.toLocaleString(undefined, { maximumFractionDigits: 2 })} km</div>
        <div class="goal-hero-sub">${goalYearStatus(goal)}</div>
      </div>
      <div class="goal-hero-percent">${yearPct.toFixed(1)}%</div>
    </div>
    <div class="goal-year-track">
      <div class="goal-progress" role="progressbar" aria-label="${year} 年度目標達成率" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(100, yearPct)}"><span style="width:${Math.max(0, Math.min(100, yearPct))}%"></span></div>
      ${marker}
    </div>
    <div class="goal-months-head"><span>每月 ${Number(goal.monthly_km).toLocaleString()} km</span><span>${monthsSummary}</span></div>
    <ol class="goal-months" aria-label="${year} 年每月達成">${goal.months.map(goalMonthCell).join('')}</ol>
    <div class="goal-legend" aria-hidden="true"><span class="met">達標</span><span class="missed">未達標</span>${marker ? '<span class="current">本月進行中</span><span class="pace">今天應有的進度</span>' : ''}</div>
    ${current}
    <p class="goal-footnote">只計跑步日誌，不含手動歷史調整。</p>
  </div>`;
}

async function saveRunningGoal() {
  if (goalSaveOperation) return;
  const status = document.getElementById('goal-settings-status');
  const payload = {
    expected_version: Number(coreData.runningGoal.version || 0),
    start_year: Number(document.getElementById('goal-start-year').value),
    monthly_km: Number(document.getElementById('goal-monthly-km').value),
  };
  if (!Number.isInteger(payload.start_year) || payload.start_year < 1900 || payload.start_year > 2100 ||
      !Number.isFinite(payload.monthly_km) || payload.monthly_km <= 0 || payload.monthly_km > 100000) {
    status.textContent = '請輸入有效的年份與正數里程。';
    return;
  }
  const operation = getFormOperations('goal').begin('save', readForm(Object.keys(goalFormValues(coreData.runningGoal))));
  if (!operation) return;
  goalSaveOperation = operation;
  document.getElementById('save-goal-btn').disabled = true;
  try {
    const goal = await apiPut('/running-goal', payload);
    if (goalSaveOperation !== operation || !isCurrentAuthSession(operation.session)) return;
    invalidateDataResources(['goal', 'goal-progress', 'dashboard-analytics']);
    const serverValues = goalFormValues(goal);
    applyCoreResource('goal', goal);
    const values = getFormDraft('goal').acknowledge(serverValues, operation.form, readForm(Object.keys(serverValues)));
    for (const [id, value] of Object.entries(values)) setGoalField(id, value);
    if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
    dashboardAnalyticsRequest++;
    resourceStore?.invalidate(['goal-progress']);
    goalProgressRequestId += 1;
    const newerInput = Object.keys(values).some(id => values[id] !== serverValues[id]);
    status.textContent = newerInput ? '目標已儲存；新的變更尚未儲存。' : '目標已儲存。';
    if (!newerInput) {
      const hadFocus = document.getElementById('goal-settings').contains(document.activeElement);
      setGoalSettingsOpen(false);
      if (hadFocus) document.getElementById('goal-edit-toggle').focus();
    }
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
