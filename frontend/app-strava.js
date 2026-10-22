// Strava CSV preview, mapping, and import UI.
registerFeatureReset('strava-import', () => {
  stravaPreviewController?.abort();
  stravaPreviewController = null;
  stravaPreviewRequestId += 1;
  stravaPreview = null;
  stravaPreviewKey = '';
  closeStravaModal();
});
async function loadStravaHistory() {
  const session = captureAuthSession();
  try {
    const history = await apiGet('/runs/import/strava/history');
    if (!isCurrentAuthSession(session)) return;
    stravaImports = history;
    renderStravaStatus();
    if (document.getElementById('strava-modal').classList.contains('active')) renderStravaImportHistory();
  } catch (error) {
    if (error.name !== 'AbortError' && isCurrentAuthSession(session)) console.warn('載入 Strava 匯入歷史失敗:', error);
  }
}

function openStravaModal() {
  refreshDateLimits();
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
      '/runs/import/strava/preview', file,
      { start_date: startDate, end_date: endDate }, controller.signal,
    );
    if (requestId !== stravaPreviewRequestId) return;
    stravaPreview = preview;
    stravaPreviewKey = inputKey;
    const unknown = stravaPreview.gear_groups.filter(group => !group.suggested_shoe_id).length;
    summary.innerHTML = `找到 <strong>${stravaPreview.run_count}</strong> 筆跑步活動；` +
      `其中 ${stravaPreview.importable_count} 筆（${Number(stravaPreview.importable_km).toFixed(2)} km）可匯入，` +
      `已有 ${stravaPreview.duplicate_count} 筆重複。` +
      (unknown ? `有 ${unknown} 個鞋款需要手動配對或略過。` : '待匯入鞋款已全部自動配對。');
    const shoeOptions = allRunShoes().map(shoe => `<option value="${shoe.id}">${esc(shoeLabel(shoe))}</option>`).join('');
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
    const result = await apiUpload('/runs/import/strava', file, {
      mapping: JSON.stringify(mapping), start_date: startDate, end_date: endDate,
    });
    closeStravaModal();
    alert(`已匯入 ${result.imported} 筆跑步紀錄${result.skipped_unmapped ? `，略過 ${result.skipped_unmapped} 筆未配對鞋款` : ''}${result.synced_mileage ? `，並同步 ${result.synced_mileage.toFixed(2)} km 至跑鞋與月跑量` : ''}。`);
    await loadData({ mutation: 'strava' });
  } catch (e) {
    error.textContent = e.message || '匯入失敗';
    error.style.display = 'block';
    button.disabled = false;
  }
}
