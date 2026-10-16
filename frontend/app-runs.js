// ====== Run Log ======
let editingRunId = null;

function localDateISO(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function allRunShoes() { return [...shoes, ...retiredShoes]; }
function runShoe(shoeId) { return allRunShoes().find(s => s.id === shoeId); }

function populateRunShoeSelects(selectedId = null) {
  const shoeList = allRunShoes();
  const options = shoeList.map(s =>
    `<option value="${s.id}">${esc(s.brand)} ${esc(s.model)}${s.is_retired ? ' · 已退役' : ''}</option>`
  ).join('');
  ['run-shoe', 'edit-run-shoe'].forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;
    const previous = id === 'edit-run-shoe' && selectedId !== null
      ? selectedId
      : parseInt(select.value, 10);
    select.innerHTML = options || '<option value="">請先新增跑鞋</option>';
    if (previous && shoeList.some(s => s.id === previous)) {
      select.value = String(previous);
    } else if (id === 'edit-run-shoe' && selectedId !== null) {
      select.insertAdjacentHTML(
        'afterbegin',
        '<option value="" selected disabled>原鞋款已刪除，請重新選擇</option>',
      );
    }
  });
}

function selectedRunMonth() {
  const value = document.getElementById('run-month').value;
  return /^\d{4}-\d{2}$/.test(value) ? value : localDateISO().slice(0, 7);
}

const RUN_PAGE_SIZE = 200;

async function fetchRunPages({ year, month = null }) {
  const rows = [];
  for (let offset = 0; ; offset += RUN_PAGE_SIZE) {
    const params = new URLSearchParams({
      year: String(year),
      limit: String(RUN_PAGE_SIZE),
      offset: String(offset),
    });
    if (month !== null) params.set('month', String(month));
    const page = await apiGet('/runs?' + params.toString());
    rows.push(...page);
    if (page.length < RUN_PAGE_SIZE) return rows;
  }
}

async function loadRunsForSelectedMonth() {
  const requestId = ++runListRequestId;
  const [year, month] = selectedRunMonth().split('-').map(Number);
  try {
    const loadedRuns = await fetchRunPages({ year, month });
    if (requestId !== runListRequestId) return;
    runs = loadedRuns;
    renderRunLog();
  } catch (error) {
    if (requestId !== runListRequestId) return;
    console.error('載入跑步紀錄失敗:', error);
    document.getElementById('data-load-error').hidden = false;
  }
}

function monthRuns() {
  const month = selectedRunMonth();
  return runs.filter(run => run.date.slice(0, 7) === month);
}

let runSaving = false;
async function addRun() {
  if (runSaving) return;
  const error = document.getElementById('run-error');
  error.textContent = '';
  const date = document.getElementById('run-date').value;
  const km = parseFloat(document.getElementById('run-km').value);
  const shoeId = parseInt(document.getElementById('run-shoe').value, 10);
  if (!date || !Number.isFinite(km) || km <= 0 || !shoeId) {
    error.textContent = '請填寫日期、正確里程與鞋款。';
    return;
  }
  if (date > localDateISO()) {
    error.textContent = '跑步日期不可晚於今天。';
    return;
  }
  try {
    runSaving = true;
    document.getElementById('add-run-btn').disabled = true;
    await apiPost('/runs', {
      date, km, shoe_id: shoeId,
    });
    document.getElementById('run-km').value = '';
    document.getElementById('run-month').value = date.slice(0, 7);
    await loadData();
  } catch (e) {
    error.textContent = e.message || '新增失敗，請稍後再試。';
  } finally {
    runSaving = false;
    document.getElementById('add-run-btn').disabled = false;
  }
}

function openRunModal(runId) {
  const run = runs.find(item => item.id === runId);
  if (!run) return;
  editingRunId = runId;
  document.getElementById('edit-run-date').value = run.date;
  document.getElementById('edit-run-km').value = run.km;
  populateRunShoeSelects(run.shoe_id);
  document.getElementById('edit-run-error').style.display = 'none';
  document.getElementById('run-modal').classList.add('active');
}

function closeRunModal() {
  editingRunId = null;
  document.getElementById('run-modal').classList.remove('active');
}

async function saveRun() {
  if (!editingRunId) return;
  const error = document.getElementById('edit-run-error');
  const editingRun = runs.find(item => item.id === editingRunId);
  if (!editingRun) {
    error.textContent = '找不到這筆跑步紀錄，請重新載入。';
    error.style.display = 'block';
    return;
  }
  const payload = {
    date: document.getElementById('edit-run-date').value,
    km: parseFloat(document.getElementById('edit-run-km').value),
    shoe_id: parseInt(document.getElementById('edit-run-shoe').value, 10),
    expected_version: editingRun.version || 0,
  };
  if (!payload.date || !Number.isFinite(payload.km) || payload.km <= 0 || !payload.shoe_id) {
    error.textContent = '請完整填寫紀錄。';
    error.style.display = 'block';
    return;
  }
  if (payload.date > localDateISO()) {
    error.textContent = '跑步日期不可晚於今天。';
    error.style.display = 'block';
    return;
  }
  try {
    await apiPut('/runs/' + editingRunId, payload);
    closeRunModal();
    document.getElementById('run-month').value = payload.date.slice(0, 7);
    await loadData();
  } catch (e) {
    error.textContent = e.message || '儲存失敗。';
    error.style.display = 'block';
  }
}

async function deleteEditingRun() {
  const run = runs.find(item => item.id === editingRunId);
  if (!run || !confirm(`確定刪除 ${run.date.replace(/-/g, '/')} 的 ${run.km} km 紀錄？`)) return;
  try {
    await apiDelete('/runs/' + editingRunId + '?expected_version=' + (run.version || 0));
    closeRunModal();
    await loadData();
  } catch (e) { alert(e.message || '刪除失敗'); }
}

function openStravaModal() {
  if (stravaPreviewController) stravaPreviewController.abort();
  stravaPreviewRequestId += 1;
  stravaPreview = null;
  stravaPreviewKey = '';
  document.getElementById('strava-file').value = '';
  document.getElementById('strava-summary').innerHTML = '';
  document.getElementById('strava-mapping').innerHTML = '';
  document.getElementById('strava-error').style.display = 'none';
  document.getElementById('strava-import-btn').disabled = true;
  renderStravaImportHistory();
  const rangeKey = `strava-import-range:${currentUser || 'anonymous'}`;
  let savedRange = null;
  try { savedRange = JSON.parse(localStorage.getItem(rangeKey)); } catch {}
  const now = new Date();
  const defaultStart = new Date(now.getFullYear(), now.getMonth() - 13, 1);
  const defaultEnd = new Date(now.getFullYear(), now.getMonth(), 0);
  const formatDate = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const lastEnd = stravaImports[0]?.end_date;
  let nextStart = '';
  const today = formatDate(now);
  if (/^\d{4}-\d{2}-\d{2}$/.test(lastEnd || '')) {
    const next = new Date(`${lastEnd}T00:00:00`);
    next.setDate(next.getDate() + 1);
    nextStart = formatDate(next) <= today ? formatDate(next) : today;
  }
  document.getElementById('strava-start-date').value = nextStart || savedRange?.start || formatDate(defaultStart);
  document.getElementById('strava-end-date').value = nextStart ? today : savedRange?.end || formatDate(defaultEnd);
  document.getElementById('strava-modal').classList.add('active');
}

function renderStravaImportHistory() {
  const target = document.getElementById('strava-history');
  const last = stravaImports[0];
  if (!last) { target.textContent = '目前沒有 Strava 匯入紀錄。'; return; }
  const when = new Date(last.imported_at).toLocaleString('zh-TW');
  const range = last.start_date || last.end_date ? `${last.start_date || '不限'} ～ ${last.end_date || '不限'}` : '未限制日期';
  target.innerHTML = `<strong>上次成功匯入</strong><br>${esc(when)} · ${esc(range)}<br>新增 ${last.imported_count} 筆／${Number(last.imported_km).toFixed(2)} km · 重複 ${last.duplicate_count} 筆 · 未配對 ${last.unmapped_count} 筆 · 格式略過 ${last.invalid_count} 筆`;
}

function closeStravaModal() {
  if (stravaPreviewController) stravaPreviewController.abort();
  stravaPreviewController = null;
  stravaPreviewRequestId += 1;
  stravaPreview = null;
  stravaPreviewKey = '';
  document.getElementById('strava-modal').classList.remove('active');
}

function stravaInputKey(file, startDate, endDate) {
  if (!file) return '';
  return [file.name, file.size, file.lastModified, startDate, endDate].join('|');
}

async function previewStravaFile() {
  const file = document.getElementById('strava-file').files[0];
  const startDate = document.getElementById('strava-start-date').value;
  const endDate = document.getElementById('strava-end-date').value;
  const summary = document.getElementById('strava-summary');
  const error = document.getElementById('strava-error');
  const mapping = document.getElementById('strava-mapping');
  localStorage.setItem(
    `strava-import-range:${currentUser || 'anonymous'}`,
    JSON.stringify({ start: startDate, end: endDate }),
  );
  if (stravaPreviewController) stravaPreviewController.abort();
  stravaPreviewController = null;
  const requestId = ++stravaPreviewRequestId;
  stravaPreview = null;
  stravaPreviewKey = '';
  summary.innerHTML = '';
  mapping.innerHTML = '';
  error.style.display = 'none';
  document.getElementById('strava-import-btn').disabled = true;
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    error.textContent = 'CSV 檔案不可超過 10 MB';
    error.style.display = 'block';
    return;
  }
  summary.textContent = '正在分析 CSV…';
  const inputKey = stravaInputKey(file, startDate, endDate);
  const controller = new AbortController();
  stravaPreviewController = controller;
  try {
    const preview = await apiUpload(
      '/runs/import/strava/preview',
      file,
      { start_date: startDate, end_date: endDate },
      controller.signal,
    );
    if (requestId !== stravaPreviewRequestId) return;
    stravaPreview = preview;
    stravaPreviewKey = inputKey;
    const unknown = stravaPreview.gear_groups.filter(group => !group.suggested_shoe_id).length;
    summary.innerHTML = `找到 <strong>${stravaPreview.run_count}</strong> 筆跑步活動；` +
      `其中 ${stravaPreview.importable_count} 筆（${Number(stravaPreview.importable_km).toFixed(2)} km）可匯入，` +
      `已有 ${stravaPreview.duplicate_count} 筆重複。` +
      (unknown ? `有 ${unknown} 個鞋款需要手動配對或略過。` : '待匯入鞋款已全部自動配對。');
    const shoeOptions = allRunShoes().map(shoe => `<option value="${shoe.id}">${esc(shoe.brand)} ${esc(shoe.model)} · ${esc(shoe.date)}${shoe.is_retired ? ' · 已退役' : ''}</option>`).join('');
    mapping.innerHTML = stravaPreview.gear_groups.map((group, index) => `
      <div class="strava-group"><div><strong>${esc(group.gear || '未指定鞋款')}</strong><small>${group.count} 次 · ${Number(group.km).toFixed(2)} km</small></div>
        <select id="strava-map-${index}"><option value="">不匯入此鞋款</option>${shoeOptions}</select></div>`).join('');
    stravaPreview.gear_groups.forEach((group, index) => {
      if (group.suggested_shoe_id) document.getElementById(`strava-map-${index}`).value = String(group.suggested_shoe_id);
    });
    document.getElementById('strava-import-btn').disabled = stravaPreview.importable_count === 0;
  } catch (e) {
    if (e.name === 'AbortError' || requestId !== stravaPreviewRequestId) return;
    stravaPreview = null;
    stravaPreviewKey = '';
    summary.innerHTML = '';
    error.textContent = e.message || 'CSV 分析失敗';
    error.style.display = 'block';
  } finally {
    if (requestId === stravaPreviewRequestId) stravaPreviewController = null;
  }
}

async function importStrava() {
  if (!stravaPreview) return;
  const file = document.getElementById('strava-file').files[0];
  const mapping = {};
  const startDate = document.getElementById('strava-start-date').value;
  const endDate = document.getElementById('strava-end-date').value;
  const error = document.getElementById('strava-error');
  if (stravaPreviewKey !== stravaInputKey(file, startDate, endDate)) {
    error.textContent = '檔案或日期範圍已變更，請等待最新預覽完成。';
    error.style.display = 'block';
    await previewStravaFile();
    return;
  }
  stravaPreview.gear_groups.forEach((group, index) => {
    const value = document.getElementById(`strava-map-${index}`).value;
    mapping[group.gear] = value ? Number(value) : null;
  });
  const button = document.getElementById('strava-import-btn');
  button.disabled = true;
  try {
    const result = await apiUpload('/runs/import/strava', file, { mapping: JSON.stringify(mapping), start_date: startDate, end_date: endDate });
    closeStravaModal();
    alert(`已匯入 ${result.imported} 筆跑步紀錄${result.skipped_unmapped ? `，略過 ${result.skipped_unmapped} 筆未配對鞋款` : ''}${result.synced_mileage ? `，並同步 ${result.synced_mileage.toFixed(2)} km 至跑鞋與月跑量` : ''}。`);
    await loadData();
  } catch (e) {
    error.textContent = e.message || '匯入失敗';
    error.style.display = 'block';
    button.disabled = false;
  }
}

function renderRunLog() {
  const month = selectedRunMonth();
  const filtered = monthRuns();
  const total = filtered.reduce((sum, run) => sum + run.km, 0);
  const days = new Set(filtered.map(run => run.date)).size;
  const shoeStats = new Map();
  filtered.forEach(run => {
    const current = shoeStats.get(run.shoe_id) || { km: 0, count: 0 };
    shoeStats.set(run.shoe_id, { km: current.km + run.km, count: current.count + 1 });
  });
  const favoriteEntry = [...shoeStats.entries()].sort((a, b) => b[1].km - a[1].km)[0];
  const favorite = favoriteEntry ? runShoe(favoriteEntry[0]) : null;
  const monthLabel = `${parseInt(month.slice(5), 10)} 月`;
  document.getElementById('run-stats').innerHTML = [
    { label: '本月總里程', value: `${total.toFixed(2)} km`, sub: `${filtered.length} 次跑步` },
    { label: '跑步天數', value: `${days} 天`, sub: days ? `平均每天 ${(total / days).toFixed(2)} km` : '還沒有紀錄' },
    { label: '本月主力鞋', value: favorite ? esc(favorite.model) : '—', sub: favoriteEntry ? `${favoriteEntry[1].km.toFixed(2)} km` : '還沒有紀錄' },
  ].map(card => `<div class="card"><div class="card-label">${card.label}</div><div class="card-value">${card.value}</div><div class="card-sub">${card.sub}</div></div>`).join('');
  renderStravaStatus();

  document.getElementById('run-table-title').textContent = `${monthLabel}跑步紀錄`;
  document.getElementById('run-table').innerHTML = filtered.length ? filtered.map(run => {
    const shoe = runShoe(run.shoe_id);
    const color = shoe ? brandColor(shoe.brand, 0) : '#64748b';
    const shoeName = shoe ? `${esc(shoe.brand)} ${esc(shoe.model)}` : '鞋款已刪除';
    const source = run.strava_id ? '<span class="run-source strava">Strava</span>' : '<span class="run-source">手動</span>';
    return `<tr><td>${esc(run.date.replace(/-/g, '/'))}</td><td><strong>${run.km.toFixed(2)} km</strong></td><td><span class="run-shoe-label"><span class="brand-dot" style="background:${color}"></span>${shoeName}</span></td><td>${source}</td><td><button class="btn btn-sm btn-edit" onclick="openRunModal(${run.id})">編輯</button></td></tr>`;
  }).join('') : '<tr><td colspan="5" class="empty-state">這個月還沒有跑步紀錄。點月曆日期或從右上角記下第一跑吧！</td></tr>';

  renderRunCalendar(filtered, month);
  renderRunShoeChart(shoeStats);
  loadDashboardAnalytics(month);
}

async function loadDashboardAnalytics(month) {
  const target = document.getElementById('dashboard-insights');
  if (!target || !authToken) return;
  const cacheKey = `${localDateISO()}|${month}`;
  for (const key of dashboardAnalyticsCache.keys()) {
    if (!key.startsWith(`${localDateISO()}|`)) dashboardAnalyticsCache.delete(key);
  }
  if (dashboardAnalyticsCache.has(cacheKey)) {
    renderDashboardInsights(dashboardAnalyticsCache.get(cacheKey));
    return;
  }
  const requestId = ++dashboardAnalyticsRequest;
  target.innerHTML = '<div class="insight-card"><div class="insight-card-sub">分析載入中…</div></div>';
  try {
    const [year, monthNumber] = month.split('-').map(Number);
    const data = await apiGet(`/analytics/dashboard?year=${year}&month=${monthNumber}`);
    if (requestId !== dashboardAnalyticsRequest || selectedRunMonth() !== month) return;
    dashboardAnalyticsCache.set(cacheKey, data);
    renderDashboardInsights(data);
  } catch (error) {
    if (requestId !== dashboardAnalyticsRequest) return;
    target.innerHTML = `<div class="insight-alert warning">進階分析暫時無法載入：${esc(error.message || '未知錯誤')}</div>`;
  }
}

function renderDashboardInsights(data) {
  const target = document.getElementById('dashboard-insights');
  const goal = data.goal || {};
  const comparison = data.comparison || {};
  const delta = Number(comparison.delta_km ?? data.month_delta_km ?? 0);
  const recent = data.recent_7_days || {};
  const forecast = data.forecast || {};
  const goalSummary = dashboardGoalSummary(goal);
  const forecastSummary = forecast.state === 'current'
    ? ` · 月底預測 ${Number(forecast.projected_month_km || 0).toFixed(2)} km`
    : '';
  const cards = [
    { label: comparison.label || '與上月比較', value: comparison.label === '尚未開始' ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(2)} km`, sub: comparison.label === '尚未開始' ? '所選月份尚未開始' : `上月${comparison.through_day ? `前 ${comparison.through_day} 天` : ''} ${Number(comparison.previous_km ?? data.previous_month?.km ?? 0).toFixed(2)} km` },
    { label: '近 7 天趨勢', value: recent.state === 'future' ? '—' : `${Number(recent.km || 0).toFixed(2)} km`, sub: recent.state === 'future' ? '所選月份尚未開始' : `較前 7 天 ${Number(recent.delta_km || 0) >= 0 ? '+' : ''}${Number(recent.delta_km || 0).toFixed(2)} km` },
    { label: '月目標', value: goal.active ? `${Number(goal.month_achievement_percent || 0).toFixed(1)}%` : '尚未啟用', sub: `${goalSummary}${forecastSummary}` },
  ];
  const alerts = (data.alerts || []).map(alert => `<div class="insight-alert ${esc(alert.severity || '')}">${esc(alert.message)}</div>`).join('');
  target.innerHTML = `
    <div class="insight-grid">${cards.map(card => `<div class="insight-card"><div class="insight-card-label">${card.label}</div><div class="insight-card-value">${card.value}</div><div class="insight-card-sub">${card.sub}</div></div>`).join('')}</div>
    ${alerts ? `<div class="insight-alerts">${alerts}</div>` : ''}`;
}

function dashboardGoalSummary(goal) {
  if (!goal.active) return `從 ${goal.start_year || '—'} 年開始`;
  if (goal.month_state === 'future') return '尚未開始';
  if (goal.month_state === 'past') {
    const remainingKm = Number(goal.month_remaining_km || 0);
    if (remainingKm > 0) return `月底結算，未達目標 ${remainingKm.toFixed(2)} km`;
    const overKm = Math.max(0, Number(goal.month_km || 0) - Number(goal.monthly_km || 0));
    return `已達成目標，超過 ${overKm.toFixed(2)} km`;
  }
  if (goal.month_state === 'before_goal') return `從 ${goal.start_year || '—'} 年開始`;

  const paceDelta = Number(goal.pace_delta_km || 0);
  const parts = [
    `${paceDelta >= 0 ? '超前' : '落後'} ${Math.abs(paceDelta).toFixed(2)} km`,
    `剩 ${Number(goal.remaining_days || 0)} 天`,
  ];
  if (goal.required_daily_km !== null && goal.required_daily_km !== undefined) {
    parts.push(`每天需 ${Number(goal.required_daily_km).toFixed(2)} km`);
  }
  return parts.join(' · ');
}

function renderStravaStatus() {
  const target = document.getElementById('strava-last');
  const last = stravaImports[0];
  if (!last) { target.textContent = '尚未匯入'; return; }
  const when = new Date(last.imported_at).toLocaleString('zh-TW', { month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit' });
  target.textContent = `上次 ${when} · 新增 ${last.imported_count} 筆`;
}

function selectRunCalendarDate(date, event) {
  if (event.target.closest('.calendar-run')) return;
  document.getElementById('run-date').value = date;
  document.getElementById('run-month').value = date.slice(0, 7);
  document.getElementById('run-km').focus();
}

function renderRunCalendar(filtered, month) {
  const target = document.getElementById('run-calendar');
  const [year, monthNumber] = month.split('-').map(Number);
  const daysInMonth = new Date(year, monthNumber, 0).getDate();
  const firstWeekday = (new Date(year, monthNumber - 1, 1).getDay() + 6) % 7;
  const byDay = new Map();
  filtered.forEach(run => {
    const day = Number(run.date.slice(8));
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(run);
  });
  const weekdays = ['一','二','三','四','五','六','日'].map(day => `<div class="calendar-weekday">${day}</div>`);
  const blanks = Array.from({length:firstWeekday}, () => '<div class="calendar-day outside"></div>');
  const today = localDateISO();
  const cells = Array.from({length:daysInMonth}, (_, index) => {
    const day = index + 1;
    const date = `${month}-${String(day).padStart(2,'0')}`;
    const dayRuns = byDay.get(day) || [];
    const total = dayRuns.reduce((sum, run) => sum + run.km, 0);
    const intensity = total ? Math.min(.18 + total / 25, .68) : 0;
    const items = dayRuns.map(run => {
      const shoe = runShoe(run.shoe_id);
      return `<button class="calendar-run" onclick="event.stopPropagation();openRunModal(${run.id})">${esc(shoe?.model || '跑鞋')}</button>`;
    }).join('');
    return `<div class="calendar-day${date === today ? ' today' : ''}" style="background:rgba(34,197,94,${intensity})" onclick="selectRunCalendarDate('${date}',event)"><div class="calendar-number">${day}</div>${total ? `<div class="calendar-total">${total.toFixed(2)} km</div>` : ''}${items}</div>`;
  });
  target.innerHTML = [...weekdays, ...blanks, ...cells].join('');
}

function getThemeColor(varName, fallback) {
  const val = getComputedStyle(document.body).getPropertyValue(varName).trim();
  return val || fallback;
}

function renderRunShoeChart(shoeStats) {
  const entries = [...shoeStats.entries()].sort((a, b) => b[1].km - a[1].km);
  const shoeList = entries.map(([id]) => runShoe(id));
  const colors = shoeList.map((shoe, i) => shoe ? brandColor(shoe.brand, i) : '#64748b');
  const total = entries.reduce((sum, [, stats]) => sum + stats.km, 0);
  const legend = document.getElementById('run-shoe-legend');
  legend.innerHTML = entries.length ? entries.map(([, stats], index) => {
    const shoe = shoeList[index];
    const name = shoe ? `${shoe.brand} ${shoe.model}` : '鞋款已刪除';
    const percentage = total > 0 ? stats.km / total * 100 : 0;
    return `<div class="run-shoe-legend-row"><div class="run-shoe-legend-name"><span class="run-shoe-legend-dot" style="background:${colors[index]}"></span><span>${esc(name)}</span></div><span class="run-shoe-legend-pct">${percentage.toFixed(1)}%</span><span class="run-shoe-legend-km">${stats.km.toFixed(2)} km</span><span class="run-shoe-legend-count">${stats.count} 次</span></div>`;
  }).join('') : '<div class="empty-state">這個月還沒有鞋款里程。</div>';
  if (typeof Chart === 'undefined') return;
  if (chartInstances.runShoes) chartInstances.runShoes.destroy();
  const cardBg = getThemeColor('--card', '#1a1d2e');
  chartInstances.runShoes = new Chart(document.getElementById('chart-run-shoes'), {
    type: 'doughnut',
    data: {
      labels: shoeList.map(shoe => shoe ? `${shoe.brand} ${shoe.model}` : '鞋款已刪除'),
      datasets: [{ data: entries.map(([, stats]) => stats.km), backgroundColor: colors, borderColor: cardBg, borderWidth: 3 }],
    },
    options: { maintainAspectRatio: false, cutout: '60%', plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${total > 0 ? (ctx.raw / total * 100).toFixed(1) : '0.0'}% / ${ctx.raw.toFixed(2)} km / ${entries[ctx.dataIndex][1].count} 次` } } } }
  });
}

async function openShoeAnalytics(shoeId) {
  const modal = document.getElementById('shoe-analysis-modal');
  const content = document.getElementById('shoe-analysis-content');
  const requestId = ++shoeAnalyticsRequestId;
  modal.classList.add('active');
  content.innerHTML = '<div class="empty-state">載入跑鞋分析…</div>';
  try {
    const data = await apiGet(`/shoes/${shoeId}/analytics`);
    if (requestId !== shoeAnalyticsRequestId || !modal.classList.contains('active')) return;
    renderShoeAnalytics(data);
  } catch (error) {
    if (requestId !== shoeAnalyticsRequestId || !modal.classList.contains('active')) return;
    content.innerHTML = `<div class="insight-alert warning">分析載入失敗：${esc(error.message || '未知錯誤')}</div>`;
  }
}

function closeShoeAnalytics() {
  shoeAnalyticsRequestId += 1;
  document.getElementById('shoe-analysis-modal').classList.remove('active');
  if (chartInstances.shoeAnalytics) {
    chartInstances.shoeAnalytics.destroy();
    delete chartInstances.shoeAnalytics;
  }
}

function renderShoeAnalytics(data) {
  const shoe = data.shoe;
  const life = data.lifecycle;
  const usage = data.usage;
  document.getElementById('shoe-analysis-title').textContent = `${shoe.brand} ${shoe.model}`;
  document.getElementById('shoe-analysis-sub').textContent = `${shoe.is_retired ? '已退役' : '使用中'} · ${shoe.categories.join(' / ') || '未分類'} · 購入 ${shoe.purchase_date.replace(/-/g, '/')}`;
  const forecast = life.forecast_retirement_date
    ? life.forecast_retirement_date.replace(/-/g, '/')
    : '無法預估';
  const source = life.forecast_source === 'recent_90_days' ? '依近 90 天實際使用' : '依計畫月跑量';
  const cards = [
    { label: '總里程', value: `${Number(life.total_mileage_km).toFixed(2)} km`, sub: '' },
    { label: '穿著次數', value: `${usage.count} 次`, sub: usage.count ? '已納入逐筆日誌' : '尚無日誌紀錄' },
    { label: '近 30／90 天', value: `${Number(usage.km_30_days).toFixed(1)} / ${Number(usage.km_90_days).toFixed(1)} km`, sub: `實際月均 ${Number(usage.actual_monthly_km_90_days).toFixed(1)} km` },
    { label: '最後使用', value: usage.last_run_date ? usage.last_run_date.replace(/-/g, '/') : '—', sub: usage.first_run_date ? `首次紀錄 ${usage.first_run_date.replace(/-/g, '/')}` : '尚無日誌紀錄' },
    { label: '壽命進度', value: life.usage_percent === null ? '—' : `${Number(life.usage_percent).toFixed(1)}%`, sub: `剩餘 ${Number(life.remaining_mileage_km).toFixed(2)} km` },
    { label: '預估退役', value: forecast, sub: `${source} · ${Number(life.forecast_monthly_km).toFixed(1)} km／月` },
  ];
  const recentRows = data.recent_runs.length ? data.recent_runs.map(run => `
    <tr><td>${run.date.replace(/-/g, '/')}</td><td>${Number(run.km).toFixed(2)} km</td></tr>`).join('')
    : '<tr><td colspan="2" class="empty-state">尚無逐筆跑步紀錄。</td></tr>';
  document.getElementById('shoe-analysis-content').innerHTML = `<div class="shoe-analysis-grid">${cards.map(card => `<div class="insight-card"><div class="insight-card-label">${card.label}</div><div class="insight-card-value">${card.value}</div>${card.sub ? `<div class="insight-card-sub">${card.sub}</div>` : ''}</div>`).join('')}</div>
    <div class="shoe-analysis-section"><h3>近 12 個月使用趨勢</h3><div class="shoe-analysis-chart"><canvas id="chart-shoe-analytics"></canvas></div></div>
    <div class="shoe-analysis-section"><h3>最近跑步</h3><div class="table-wrap" tabindex="0" role="region" aria-label="跑鞋最近跑步"><table><thead><tr><th>日期</th><th>距離</th></tr></thead><tbody>${recentRows}</tbody></table></div></div>`;
  if (typeof Chart === 'undefined') return;
  if (chartInstances.shoeAnalytics) chartInstances.shoeAnalytics.destroy();
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#334155');
  chartInstances.shoeAnalytics = new Chart(document.getElementById('chart-shoe-analytics'), {
    type: 'bar',
    data: {
      labels: data.monthly_history.map(item => `${item.year}/${item.month}`),
      datasets: [{ label: '里程', data: data.monthly_history.map(item => item.km), backgroundColor: '#22c55e', borderRadius: 4 }],
    },
    options: { maintainAspectRatio:false, plugins:{ legend:{display:false}, tooltip:{callbacks:{label:ctx => `${Number(ctx.raw).toFixed(2)} km · ${data.monthly_history[ctx.dataIndex].count} 次`}}}, scales:{x:{grid:{display:false},ticks:{color:textColor}},y:{beginAtZero:true,grid:{color:gridColor},ticks:{color:textColor,callback:value => value + ' km'}}} },
  });
}

