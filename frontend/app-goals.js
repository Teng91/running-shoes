// Running-goal settings and selected-period progress presentation.
function renderGoalProgress() {
  const cards = document.getElementById('goal-cards');
  if (!cards) return;
  document.getElementById('goal-start-year').value = runningGoal.start_year;
  document.getElementById('goal-monthly-km').value = runningGoal.monthly_km;
  const year = selectedYear || new Date().getFullYear();
  const now = new Date();
  const rows = monthlyMileages.filter(item => item.year === year);
  const latestRecordedMonth = rows.length
    ? Math.max(...rows.map(item => item.month))
    : null;
  if (!selectedGoalMonth) {
    selectedGoalMonth = year === now.getFullYear()
      ? now.getMonth() + 1
      : (latestRecordedMonth || 12);
  }
  const monthSelect = document.getElementById('goal-month-select');
  monthSelect.innerHTML = Array.from({length: 12}, (_, index) => {
    const month = index + 1;
    return `<option value="${month}" ${month === selectedGoalMonth ? 'selected' : ''}>${month} 月</option>`;
  }).join('');
  if (year < runningGoal.start_year) {
    cards.innerHTML = `<div class="card"><div class="card-label">${year} 年目標</div><div class="card-value">尚未開始</div><div class="card-sub">目標自 ${runningGoal.start_year} 年起生效</div></div>`;
    return;
  }
  const selectedRow = rows.find(item => item.month === selectedGoalMonth);
  const monthKm = selectedRow ? selectedRow.km : 0;
  const monthPct = monthKm / runningGoal.monthly_km * 100;
  const yearKm = rows.filter(item => item.month <= selectedGoalMonth).reduce((sum, item) => sum + item.km, 0);
  const yearPct = yearKm / runningGoal.yearly_km * 100;
  const daysInMonth = new Date(year, selectedGoalMonth, 0).getDate();
  const selectedKey = year * 100 + selectedGoalMonth;
  const currentKey = now.getFullYear() * 100 + now.getMonth() + 1;
  let paceText;
  if (selectedKey < currentKey) {
    paceText = monthKm >= runningGoal.monthly_km
      ? `已達成目標，超過 ${(monthKm - runningGoal.monthly_km).toFixed(2)} km`
      : `月底結算，未達目標 ${(runningGoal.monthly_km - monthKm).toFixed(2)} km`;
  } else if (selectedKey > currentKey) {
    paceText = '尚未開始';
  } else {
    const elapsedDays = now.getDate();
    const remainingDays = daysInMonth - elapsedDays;
    const expectedKm = runningGoal.monthly_km * elapsedDays / daysInMonth;
    const paceDelta = monthKm - expectedKm;
    const remainingKm = Math.max(0, runningGoal.monthly_km - monthKm);
    const dailyNeeded = remainingDays > 0 ? remainingKm / remainingDays : null;
    paceText = `${paceDelta >= 0 ? '超前' : '落後'} ${Math.abs(paceDelta).toFixed(2)} km · 剩 ${remainingDays} 天` +
      (dailyNeeded === null ? '' : ` · 每天需 ${dailyNeeded.toFixed(2)} km`);
  }
  cards.innerHTML = `
    <div class="card">
      <div class="card-label">${year} 年 ${selectedGoalMonth} 月目標</div>
      <div class="card-value">${monthKm.toFixed(2)} / ${Number(runningGoal.monthly_km).toFixed(0)} km</div>
      <div class="card-sub">達成 ${monthPct.toFixed(1)}% · ${paceText}</div>
      <div class="goal-progress"><span style="width:${Math.min(100, monthPct)}%"></span></div>
    </div>
    <div class="card">
      <div class="card-label">${year} 年截至 ${selectedGoalMonth} 月年度進度</div>
      <div class="card-value">${yearKm.toFixed(2)} / ${Number(runningGoal.yearly_km).toFixed(0)} km</div>
      <div class="card-sub">達成 ${yearPct.toFixed(1)}% · 尚差 ${Math.max(0, runningGoal.yearly_km - yearKm).toFixed(2)} km</div>
      <div class="goal-progress"><span style="width:${Math.min(100, yearPct)}%"></span></div>
    </div>`;
}

function onGoalMonthChange() {
  selectedGoalMonth = Number(document.getElementById('goal-month-select').value) || 1;
  renderGoalProgress();
}

async function saveRunningGoal() {
  const status = document.getElementById('goal-settings-status');
  const payload = {
    expected_version: Number(runningGoal.version || 0),
    start_year: Number(document.getElementById('goal-start-year').value),
    monthly_km: Number(document.getElementById('goal-monthly-km').value),
  };
  if (!Number.isInteger(payload.start_year) || payload.monthly_km <= 0) {
    status.textContent = '請輸入有效的年份與正數里程。';
    return;
  }
  try {
    runningGoal = await apiPut('/running-goal', payload);
    dashboardAnalyticsCache.clear();
    status.textContent = '目標已儲存。';
    invalidatePanels();
    renderActivePanel();
  } catch (error) {
    status.textContent = error.message || '目標儲存失敗。';
  }
}
