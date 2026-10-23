// Strava CSV preview, mapping, and import UI.
let stravaController = null;
async function initializeStravaFeature() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  const { createStravaController } = await import('./runtime/strava-controller.mjs?v=' + encodeURIComponent(version));
  stravaController = createStravaController({ transport: { upload: apiUpload }, session: { capture: captureAuthSession, current: isCurrentAuthSession } });
}
registerFeatureReset('strava-import', () => {
  stravaController?.reset();
  document.getElementById('strava-modal').classList.remove('active');
});
async function loadStravaHistory() {
  const result = await resourceStore.read('strava-history', { loader: () => apiGet('/runs/import/strava/history') });
  const [accepted] = resourceStore.accept([result]);
  if (!accepted) return;
  document.getElementById('data-load-error').hidden = !resourceStore.hasErrors();
  if (result.status === 'rejected') {
    if (result.error.name !== 'AbortError') console.warn('載入 Strava 匯入歷史失敗:', result.error);
    return;
  }
  stravaImports = result.value;
  renderStravaStatus();
  if (document.getElementById('strava-modal').classList.contains('active')) renderStravaImportHistory();
}

function openStravaModal() {
  refreshDateLimits();
  stravaController.open();
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
  stravaController.close();
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
  const operation = stravaController.beginPreview();
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
  try {
    const preview = await stravaController.preview(operation, file, { start_date: startDate, end_date: endDate });
    if (!stravaController.acceptPreview(operation, preview, inputKey)) return;
    const unknown = stravaController.state.preview.gear_groups.filter(group => !group.suggested_shoe_id).length;
    summary.innerHTML = `找到 <strong>${stravaController.state.preview.run_count}</strong> 筆跑步活動；` +
      `其中 ${stravaController.state.preview.importable_count} 筆（${Number(stravaController.state.preview.importable_km).toFixed(2)} km）可匯入，` +
      `已有 ${stravaController.state.preview.duplicate_count} 筆重複。` +
      (unknown ? `有 ${unknown} 個鞋款需要手動配對或略過。` : '待匯入鞋款已全部自動配對。');
    const shoeOptions = allRunShoes().map(shoe => `<option value="${shoe.id}">${esc(shoeLabel(shoe))}</option>`).join('');
    mapping.innerHTML = stravaController.state.preview.gear_groups.map((group, index) => `
      <div class="strava-group"><div><strong>${esc(group.gear || '未指定鞋款')}</strong><small>${group.count} 次 · ${Number(group.km).toFixed(2)} km</small></div>
        <select id="strava-map-${index}"><option value="">不匯入此鞋款</option>${shoeOptions}</select></div>`).join('');
    stravaController.state.preview.gear_groups.forEach((group, index) => {
      if (group.suggested_shoe_id) document.getElementById(`strava-map-${index}`).value = String(group.suggested_shoe_id);
    });
    setStravaMappingDisabled(stravaController.importing());
    document.getElementById('strava-import-btn').disabled = stravaController.importing() || stravaController.state.preview.importable_count === 0;
  } catch (e) {
    if (e.name === 'AbortError' || !stravaController.current(operation)) return;
    summary.innerHTML = '';
    error.textContent = e.message || 'CSV 分析失敗';
    error.style.display = 'block';
  } finally {
    stravaController.finishPreview(operation);
  }
}

async function importStrava() {
  if (!stravaController.state.preview) return;
  const file = document.getElementById('strava-file').files[0];
  const mapping = {};
  const startDate = document.getElementById('strava-start-date').value;
  const endDate = document.getElementById('strava-end-date').value;
  const error = document.getElementById('strava-error');
  if (stravaController.state.key !== stravaInputKey(file, startDate, endDate)) {
    error.textContent = '檔案或日期範圍已變更，請等待最新預覽完成。';
    error.style.display = 'block';
    await previewStravaFile();
    return;
  }
  stravaController.state.preview.gear_groups.forEach((group, index) => {
    const value = document.getElementById(`strava-map-${index}`).value;
    mapping[group.gear] = value ? Number(value) : null;
  });
  const operation = stravaController.beginImport(stravaInputKey(file, startDate, endDate));
  if (!operation) return;
  const button = document.getElementById('strava-import-btn');
  button.disabled = true;
  setStravaMappingDisabled(true);
  try {
    const result = await stravaController.import(operation, file, {
      mapping: JSON.stringify(mapping), start_date: startDate, end_date: endDate,
    });
    if (!stravaController.sessionCurrent(operation)) return;
    resourceStore.invalidate(['strava-history']);
    if (stravaController.ownsImport(operation)) {
      closeStravaModal();
      alert(`已匯入 ${result.imported} 筆跑步紀錄${result.skipped_unmapped ? `，略過 ${result.skipped_unmapped} 筆未配對鞋款` : ''}${result.synced_mileage ? `，並同步 ${result.synced_mileage.toFixed(2)} km 至跑鞋與月跑量` : ''}。`);
    }
    await loadData({ mutation: 'strava' });
  } catch (e) {
    if (e.name === 'AbortError' || !stravaController.ownsImport(operation)) return;
    error.textContent = e.message || '匯入失敗';
    error.style.display = 'block';
    button.disabled = false;
  } finally {
    stravaController.finishImport(operation);
    if (stravaController.windowCurrent(operation) && !stravaController.importing() && stravaController.state.preview) {
      setStravaMappingDisabled(false);
      button.disabled = stravaController.state.preview.importable_count === 0;
    }
  }
}

function setStravaMappingDisabled(disabled) {
  document.querySelectorAll('#strava-mapping select').forEach(select => { select.disabled = disabled; });
}
