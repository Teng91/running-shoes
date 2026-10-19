// Monthly mileage editing, exports, and running-goal interactions.
function renderMonthlyTable() {
  const tbody = document.getElementById('monthly-table');
  if (monthlyMileages.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:24px;">尚無月跑量紀錄，使用上方表單新增</td></tr>';
    return;
  }
  tbody.innerHTML = monthlyMileages.map((m, i) => `
    <tr>
      <td>${m.year}</td>
      <td>${m.month}</td>
      <td>${(m.km - (m.adjustment_km || 0)).toFixed(2)} km</td>
      <td>${(m.adjustment_km || 0).toFixed(2)} km</td>
      <td class="editable" ondblclick="inlineEditMonthly(${i},'km',this)"><strong>${m.km.toFixed(2)}</strong></td>
      <td>
        <button class="btn btn-sm btn-edit" onclick="editMonthlyMileage(${i})">編輯</button>
        <button class="btn btn-sm btn-delete" onclick="deleteMonthlyMileage(${i})">刪除</button>
      </td>
    </tr>
  `).join('');
}

async function inlineEditMonthly(idx, field, el) {
  const entry = { ...monthlyMileages[idx] };
  const current = entry[field];
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'inline-input';
  input.step = '0.01';
  input.min = '0';
  input.value = current;
  let committed = false;
  const commit = async () => {
    if (committed) return;
    committed = true;
    const val = parseFloat(input.value);
    if (!isNaN(val) && val >= 0) {
      try {
        await apiPut('/monthly-mileage/' + entry.id, {
          km: val,
          expected_version: entry.version || 0,
        });
      } catch (e) {
        alert(e.message || '更新失敗');
      }
    }
    await loadData();
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') commit();
    if (e.key === 'Escape') { committed = true; render(); }
  });
  el.innerHTML = '';
  el.appendChild(input);
  input.focus();
}

async function deleteMonthlyMileage(idx) {
  const m = monthlyMileages[idx];
  if (!confirm(`確定要刪除 ${m.year} 年 ${m.month} 月的紀錄？`)) return;
  try {
    await apiDelete('/monthly-mileage/' + m.id + '?expected_version=' + (m.version || 0));
  } catch (e) {
    console.error('刪除失敗:', e);
    alert(e.message || '刪除失敗');
    return;
  }
  await loadData();
}

// ====== Monthly Mileage: inline add form ======
function populateAddSelects() {
  const now = new Date();
  const yearSel = document.getElementById('add-year');
  const monthSel = document.getElementById('add-month');
  yearSel.innerHTML = '';
  const startY = now.getFullYear() - 5;
  const endY = now.getFullYear() + 5; // 往未來延伸 5 年
  for (let y = endY; y >= startY; y--) {
    const opt = document.createElement('option');
    opt.value = y;
    opt.textContent = y;
    if (y === now.getFullYear()) opt.selected = true;
    yearSel.appendChild(opt);
  }
  monthSel.innerHTML = '';
  for (let m = 1; m <= 12; m++) {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m + ' 月';
    if (m === now.getMonth() + 1) opt.selected = true;
    monthSel.appendChild(opt);
  }
}

let monthlySaving = false;
async function addMonthlyMileage() {
  if (monthlySaving) return;
  const year = parseInt(document.getElementById('add-year').value, 10);
  const month = parseInt(document.getElementById('add-month').value, 10);
  const rawKm = parseFloat(document.getElementById('add-km').value);
  const km = Number.isFinite(rawKm) ? rawKm : 0;
  const errEl = document.getElementById('add-error');
  errEl.style.display = 'none';

  const button = document.getElementById('add-monthly-btn');
  try {
    monthlySaving = true;
    button.disabled = true;
    await apiPost('/monthly-mileage', { year, month, km });
  } catch (e) {
    errEl.textContent = translateError(e.message) || '儲存失敗';
    errEl.style.display = '';
    return;
  } finally {
    monthlySaving = false;
    button.disabled = false;
  }
  document.getElementById('add-km').value = '';
  await loadData();
}

// ====== Monthly Mileage: edit modal ======
let editingMonthlyIdx = -1;

function editMonthlyMileage(idx) {
  editingMonthlyIdx = idx;
  const m = monthlyMileages[idx];
  populateMonthlyEditSelects(m.year, m.month);
  document.getElementById('monthly-modal-title').textContent = '編輯月份';
  document.getElementById('m-km').value = m.km;
  document.getElementById('monthly-error').style.display = 'none';
  document.getElementById('monthly-modal').classList.add('active');
}

function populateMonthlyEditSelects(year, month) {
  const now = new Date();
  const yearSel = document.getElementById('m-year');
  const monthSel = document.getElementById('m-month');
  yearSel.innerHTML = '';
  // Range that covers both existing data and future additions
  const years = new Set(monthlyMileages.map(m => m.year));
  years.add(now.getFullYear());
  years.add(now.getFullYear() + 1);
  years.add(now.getFullYear() + 2);
  years.add(now.getFullYear() + 3);
  years.add(now.getFullYear() + 4);
  years.add(now.getFullYear() + 5);
  years.add(now.getFullYear() - 1);
  [...years].sort((a, b) => b - a).forEach(y => {
    const opt = document.createElement('option');
    opt.value = y;
    opt.textContent = y;
    if (y === year) opt.selected = true;
    yearSel.appendChild(opt);
  });
  monthSel.innerHTML = '';
  for (let m = 1; m <= 12; m++) {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m + ' 月';
    if (m === month) opt.selected = true;
    monthSel.appendChild(opt);
  }
}

function closeMonthlyModal() {
  document.getElementById('monthly-modal').classList.remove('active');
  editingMonthlyIdx = -1;
}

// ====== Export Modal Functions ======
function openExportModal() {
  document.getElementById('export-error').textContent = '';
  document.getElementById('export-mode').value = 'active';
  document.getElementById('export-format').value = 'xlsx';
  document.getElementById('export-modal').classList.add('active');
}

function closeExportModal() {
  document.getElementById('export-modal').classList.remove('active');
}

async function doExport() {
  const format = document.getElementById('export-format').value;
  const mode = document.getElementById('export-mode').value;
  const backendMode = mode === 'retired' ? 'retired' : (mode === 'all' ? 'all' : 'active');
  const displayMode = backendMode === 'retired' ? '退役' : (backendMode === 'all' ? '全部' : '現役');

  const btn = document.querySelector('#export-modal .btn-primary');
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '匯出中';

  try {
    const params = new URLSearchParams({
      format: format,
      mode: backendMode
    });

    const res = await authenticatedFetch(API_BASE + '/export?' + params.toString(), {
      headers: authHeaders()
    });

    if (!res.ok) {
      const err = await readAuthenticatedError(res);
      throw new Error(err.detail || `匯出失敗: ${res.status}`);
    }

    // Get filename from Content-Disposition header
    const disposition = res.headers.get('Content-Disposition');
    let filename = `running_shoes_${backendMode}_${new Date().toISOString().slice(0,10)}.${format}`;
    if (disposition) {
      const match = disposition.match(/filename="([^"]+)"/);
      if (match) filename = match[1];
    }

    // Download the file
    const blob = await readAuthenticatedBody(res, 'blob');
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);

    closeExportModal();

  } catch (e) {
    if (e.name === 'AbortError') return;
    console.error('匯出失敗:', e);
    document.getElementById('export-error').textContent = '匯出失敗：' + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

async function exportAccountData() {
  const error = document.getElementById('export-error');
  error.textContent = '';
  try {
    const res = await authenticatedFetch(API_BASE + '/export/account', { headers: authHeaders() });
    if (!res.ok) throw new Error('完整備份失敗：' + res.status);
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const blob = await readAuthenticatedBody(res, 'blob');
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = match ? match[1] : `running_shoes_account_${localDateISO()}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
    closeExportModal();
  } catch (e) {
    if (e.name === 'AbortError') return;
    error.textContent = e.message || '完整備份失敗';
  }
}

async function saveMonthlyMileage() {
  if (monthlySaving) return;
  const year = parseInt(document.getElementById('m-year').value, 10);
  const month = parseInt(document.getElementById('m-month').value, 10);
  const rawKm = parseFloat(document.getElementById('m-km').value);
  const km = Number.isFinite(rawKm) ? rawKm : 0;
  const errEl = document.getElementById('monthly-error');
  errEl.style.display = 'none';

  const button = document.getElementById('save-monthly-btn');
  try {
    monthlySaving = true;
    button.disabled = true;
    if (editingMonthlyIdx >= 0) {
      const entry = monthlyMileages[editingMonthlyIdx];
      await apiPut('/monthly-mileage/' + entry.id, {
        year, month, km, expected_version: entry.version || 0,
      });
    } else {
      await apiPost('/monthly-mileage', { year, month, km });
    }
  } catch (e) {
    errEl.textContent = translateError(e.message) || '儲存失敗';
    errEl.style.display = 'block';
    return;
  } finally {
    monthlySaving = false;
    button.disabled = false;
  }
  closeMonthlyModal();
  await loadData();
}

// ====== Charts ======
function populateYearSelect() {
  const sel = document.getElementById('year-select');
  const stackedSel = document.getElementById('stacked-year-select');
  const years = [...new Set([
    ...monthlyMileages.map(m => m.year),
    runningGoal.start_year,
    new Date().getFullYear(),
  ])].sort((a, b) => b - a);
  if (years.length === 0) {
    sel.innerHTML = '<option value="">無資料</option>';
    if (stackedSel) stackedSel.innerHTML = '<option value="">無資料</option>';
    selectedYear = null;
    selectedStackedYear = null;
    return;
  }
  if (!selectedYear || !years.includes(selectedYear)) {
    selectedYear = years[0];
  }
  if (!selectedStackedYear || !years.includes(selectedStackedYear)) {
    selectedStackedYear = years[0];
  }
  sel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedYear ? 'selected' : ''}>${y}</option>`).join('');
  if (stackedSel) {
    stackedSel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedStackedYear ? 'selected' : ''}>${y}</option>`).join('');
  }
}

function onYearChange() {
  const sel = document.getElementById('year-select');
  selectedYear = parseInt(sel.value, 10) || null;
  selectedGoalMonth = null;
  renderGoalProgress();
  renderMonthlyYearChart();
}

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
    populateYearSelect();
    renderGoalProgress();
  } catch (error) {
    status.textContent = error.message || '目標儲存失敗。';
  }
}

