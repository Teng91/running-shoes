// Strava CSV preview, mapping, and import UI.
let stravaController = null;
// SPEC-134: the last date range is remembered per account ID (SPEC-129), not per name.
function stravaRangeKey() {
  const account = captureAuthSession().account;
  return account ? `strava-import-range:aid:${account}` : null;
}

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
  try {
    applyCoreResource('strava-history', result.value);
  } catch (error) {
    console.warn('Strava 匯入歷史格式不正確:', error);
    return;
  }
  renderStravaStatus();
  if (document.getElementById('strava-modal').classList.contains('active')) renderStravaImportHistory();
}

function openStravaModal() {
  refreshDateLimits();
  stravaController.open();
  document.getElementById('strava-file').value = '';
  document.getElementById('strava-summary').innerHTML = '';
  document.getElementById('strava-mapping').innerHTML = '';
  document.getElementById('strava-conflicts').innerHTML = '';
  document.getElementById('strava-error').style.display = 'none';
  document.getElementById('strava-import-btn').disabled = true;
  // SPEC-097: hikes and walks are opt-in for every new import window.
  const includeWalks = document.getElementById('strava-include-walks');
  if (includeWalks) includeWalks.checked = false;
  const walkHike = document.getElementById('strava-walk-hike');
  if (walkHike) walkHike.hidden = true;
  renderStravaImportHistory();
  const rangeKey = stravaRangeKey();
  let savedRange = null;
  try { savedRange = rangeKey ? JSON.parse(readStoredValue(rangeKey)) : null; } catch {}
  // Calendar arithmetic on the service's date (SPEC-093), not the device's zone.
  const calendar = appCalendarDate();
  const defaultStart = new Date(calendar.year, calendar.month - 1 - 13, 1);
  const defaultEnd = new Date(calendar.year, calendar.month - 1, 0);
  const formatDate = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const lastEnd = coreData.stravaImports[0]?.end_date;
  let nextStart = '';
  const today = localDateISO();
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
  const last = coreData.stravaImports[0];
  if (!last) { target.textContent = '目前沒有 Strava 匯入紀錄。'; return; }
  const when = new Date(last.imported_at).toLocaleString('zh-TW');
  const range = last.start_date || last.end_date ? `${last.start_date || '不限'} ～ ${last.end_date || '不限'}` : '未限制日期';
  target.innerHTML = `<strong>上次成功匯入</strong><br>${esc(when)} · ${esc(range)}<br>新增 ${last.imported_count} 筆／${Number(last.imported_km).toFixed(2)} km · 重複 ${last.duplicate_count} 筆 · 未配對 ${last.unmapped_count} 筆 · 格式略過 ${last.invalid_count} 筆`;
}

function closeStravaModal() {
  stravaController.close();
  document.getElementById('strava-modal').classList.remove('active');
}

function stravaInputKey(file, startDate, endDate, includeWalks = false) {
  if (!file) return '';
  const key = [file.name, file.size, file.lastModified, startDate, endDate].join('|');
  return includeWalks ? `${key}|walks` : key;
}

function stravaIncludesWalks() {
  return document.getElementById('strava-include-walks')?.checked === true;
}

// SPEC-097: before SPEC-096 hikes and walks were never imported, so their kilometres
// may already be on the shoe by hand. They stay out unless the user ticks the box.
function renderStravaWalkHike(preview) {
  const box = document.getElementById('strava-walk-hike');
  const note = document.getElementById('strava-walk-hike-note');
  if (!box || !note) return;
  const count = Number(preview?.walk_hike_count || 0);
  box.hidden = !count;
  if (!count) { note.textContent = ''; return; }
  const km = Number(preview.walk_hike_km || 0).toFixed(2);
  note.textContent = preview.walk_hike_included
    ? `已包含 ${count} 筆健行／步行（${km} km），只計入鞋子里程。如果這些里程已經手動加在鞋子上，請取消勾選，避免重複計算。`
    : `這段期間有 ${count} 筆健行／步行（${km} km）未匯入。勾選後只計入鞋子里程；如果已經手動加在鞋子上，請不要勾選，避免重複計算。`;
}

async function previewStravaFile() {
  const file = document.getElementById('strava-file').files[0];
  const startDate = document.getElementById('strava-start-date').value;
  const endDate = document.getElementById('strava-end-date').value;
  const includeWalks = stravaIncludesWalks();
  const summary = document.getElementById('strava-summary');
  const error = document.getElementById('strava-error');
  const mapping = document.getElementById('strava-mapping');
  const rangeKey = stravaRangeKey();
  if (rangeKey) writeStoredValue(rangeKey, JSON.stringify({ start: startDate, end: endDate }));
  const operation = stravaController.beginPreview();
  summary.innerHTML = '';
  mapping.innerHTML = '';
  document.getElementById('strava-conflicts').innerHTML = '';
  error.style.display = 'none';
  document.getElementById('strava-import-btn').disabled = true;
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    error.textContent = 'CSV 檔案不可超過 10 MB';
    error.style.display = 'block';
    return;
  }
  summary.textContent = '正在分析 CSV…';
  const inputKey = stravaInputKey(file, startDate, endDate, includeWalks);
  try {
    const fields = { start_date: startDate, end_date: endDate };
    if (includeWalks) fields.include_walks_hikes = 'true';
    const preview = await stravaController.preview(operation, file, fields);
    if (!stravaController.acceptPreview(operation, preview, inputKey)) return;
    renderStravaWalkHike(preview);
    const unknown = stravaController.state.preview.gear_groups.filter(group => !group.suggested_shoe_id).length;
    summary.innerHTML = `找到 <strong>${stravaController.state.preview.run_count}</strong> 筆${includeWalks ? '活動' : '跑步活動'}；` +
      `其中 ${stravaController.state.preview.importable_count} 筆（${Number(stravaController.state.preview.importable_km).toFixed(2)} km）可匯入，` +
      `已有 ${stravaController.state.preview.duplicate_count} 筆重複。` +
      stravaDeletedText(stravaController.state.preview) +
      stravaDateCorrectionText(stravaController.state.preview) +
      stravaDurationBackfillText(stravaController.state.preview) +
      stravaManualMatchText(stravaController.state.preview) +
      (unknown ? `有 ${unknown} 個鞋款需要手動配對或略過。` : '待匯入鞋款已全部自動配對。');
    const shoeOptions = allRunShoes().map(shoe => `<option value="${shoe.id}">${esc(shoeLabel(shoe))}</option>`).join('');
    mapping.innerHTML = stravaController.state.preview.gear_groups.map((group, index) => `
      <div class="strava-group"><div><strong>${esc(group.gear || '未指定鞋款')}</strong><small>${group.count} 次 · ${Number(group.km).toFixed(2)} km${group.conflict_count ? ` · 另有 ${group.conflict_count} 筆待選擇的重複活動` : ''}</small>
        <small class="strava-date-warning" id="strava-warn-${index}" role="status" hidden></small></div>
        <select id="strava-map-${index}" data-change="strava-date-warning" data-index="${index}"><option value="">不匯入此鞋款</option>${shoeOptions}</select></div>`).join('');
    stravaController.state.preview.gear_groups.forEach((group, index) => {
      if (group.suggested_shoe_id) document.getElementById(`strava-map-${index}`).value = String(group.suggested_shoe_id);
      updateStravaDateWarning(index);
    });
    document.getElementById('strava-conflicts').innerHTML = stravaConflictsHtml(stravaController.state.preview);
    setStravaMappingDisabled(stravaController.importing());
    updateStravaImportButton();
  } catch (e) {
    if (e.name === 'AbortError' || !stravaController.current(operation)) return;
    summary.innerHTML = '';
    error.textContent = e.message || 'CSV 分析失敗';
    error.style.display = 'block';
  } finally {
    stravaController.finishPreview(operation);
  }
}

// SPEC-047: Strava exports UTC times; older imports stored the UTC date, which a re-import corrects.
// Activities whose runs were deleted stay deleted (SPEC-055); history recovery restores one.
function stravaDeletedText(preview) {
  const count = Number(preview?.deleted_count || 0);
  return count ? `另有 ${count} 筆先前刪除過的活動不會重新匯入（可從異動歷史復原）。` : '';
}

function stravaDateCorrectionText(preview) {
  const count = Number(preview?.date_correction_count || 0);
  if (!count) return '';
  const sample = preview.date_correction_samples?.[0];
  const example = sample ? `（例如 ${String(sample.from_date).replace(/-/g, '/')} → ${String(sample.to_date).replace(/-/g, '/')}）` : '';
  return `另有 ${count} 筆既有紀錄的日期會依台灣時間修正${example}。`;
}

// SPEC-060: re-importing an earlier CSV fills the moving time of runs that have none yet.
function stravaDurationBackfillText(preview) {
  const count = Number(preview?.duration_backfill_count || 0);
  return count ? `另有 ${count} 筆既有紀錄會補上跑步時間，用來計算配速。` : '';
}

// SPEC-062: activities already entered by hand are linked to that run, never imported again.
function stravaManualMatchText(preview) {
  const linked = Number(preview?.manual_link_count || 0);
  const timed = Number(preview?.manual_link_duration_count || 0);
  const conflicts = Number(preview?.manual_conflict_count || 0);
  let text = '';
  if (linked) text += `另有 ${linked} 筆和手動輸入的紀錄相符，不會重複新增，會改為連結 Strava${timed ? `，並補上 ${timed} 筆跑步時間` : ''}。`;
  if (conflicts) {
    const samples = (preview.manual_conflict_samples || [])
      .map(item => `${String(item.date).replace(/-/g, '/')} ${Number(item.km).toFixed(2)} km`).join('、');
    text += `另有 ${conflicts} 筆活動當天已有手動紀錄但無法確定是同一次${samples ? `（例如 ${samples}）` : ''}，請在下方選擇略過、連結到手動紀錄或匯入為新紀錄（預設略過）。`;
  }
  return text;
}

// SPEC-091: each same-day conflict offers skip (default), a link to one of that day's
// manual runs, or importing it as a new run. The backend re-checks every choice.
function stravaConflictLabel(item) {
  const time = item.duration_seconds ? ` · ${formatRunDuration(item.duration_seconds)}` : '';
  return `${Number(item.km).toFixed(2)} km${time}`;
}

function stravaConflictsHtml(preview) {
  const conflicts = preview?.manual_conflicts || [];
  if (!conflicts.length) return '';
  return '<p class="strava-conflicts-title">當天已有手動紀錄的活動</p>' + conflicts.map((conflict, index) => {
    const links = (conflict.candidates || []).map(run => `<option value="${run.run_id}">連結到手動紀錄：${esc(stravaConflictLabel(run))}${run.shoe_name ? ` · ${esc(run.shoe_name)}` : ''}</option>`).join('');
    return `<div class="strava-group"><div><strong>${esc(String(conflict.date).replace(/-/g, '/'))} Strava ${esc(stravaConflictLabel(conflict))}</strong><small>${esc(conflict.gear || '未指定鞋款')}</small></div>
      <select id="strava-conflict-${index}" data-change="strava-conflict-choice" aria-label="${esc(String(conflict.date))} 的 Strava 活動要如何處理"><option value="skip">略過（不匯入）</option>${links}<option value="import">匯入為新紀錄</option></select></div>`;
  }).join('') + '<p id="strava-conflict-status" class="strava-conflicts-status" role="status" aria-live="polite"></p>';
}

function stravaConflictChoices(preview) {
  const choices = {};
  (preview?.manual_conflicts || []).forEach((conflict, index) => {
    const value = document.getElementById(`strava-conflict-${index}`)?.value || 'skip';
    if (value !== 'skip') choices[conflict.strava_id] = value === 'import' ? 'import' : Number(value);
  });
  return choices;
}

// SPEC-092: one manual run can take only one activity; the choice summary follows the selects.
function stravaConflictProblem(choices) {
  const runs = Object.values(choices).filter(value => value !== 'import');
  return new Set(runs).size === runs.length ? '' : '同一筆手動紀錄只能連結一個 Strava 活動，請改選其中一筆。';
}

function stravaConflictSummary(choices) {
  const values = Object.values(choices);
  const imports = values.filter(value => value === 'import').length;
  const links = values.length - imports;
  if (!values.length) return '';
  return `已選擇：${links ? `連結 ${links} 筆` : ''}${links && imports ? '、' : ''}${imports ? `匯入 ${imports} 筆新紀錄（需要上方的鞋款配對）` : ''}。`;
}

function updateStravaImportButton() {
  const preview = stravaController.state.preview;
  const choices = stravaConflictChoices(preview);
  const problem = stravaConflictProblem(choices);
  const status = document.getElementById('strava-conflict-status');
  if (status) {
    status.textContent = problem || stravaConflictSummary(choices);
    status.classList?.toggle('strava-date-warning', Boolean(problem));
  }
  document.getElementById('strava-import-btn').disabled = stravaController.importing() || !preview || Boolean(problem)
    || (!stravaHasChanges(preview) && !Object.keys(choices).length);
}

function stravaHasChanges(preview) {
  return Number(preview?.importable_count || 0) > 0 || Number(preview?.date_correction_count || 0) > 0
    || Number(preview?.duration_backfill_count || 0) > 0 || Number(preview?.manual_link_count || 0) > 0;
}

// SPEC-046: flag a mapping whose earliest activity predates the chosen shoe's purchase.
function updateStravaDateWarning(index) {
  const group = stravaController.state.preview?.gear_groups[index];
  const target = document.getElementById(`strava-warn-${index}`);
  if (!group || !target) return;
  const shoe = runShoe(parseInt(document.getElementById(`strava-map-${index}`).value, 10));
  target.textContent = group.first_date && shoe?.date && group.first_date < shoe.date
    ? `最早一筆 ${group.first_date.replace(/-/g, '/')} 早於這雙鞋的購買日 ${shoe.date.replace(/-/g, '/')}，請確認配對。` : '';
  target.hidden = !target.textContent;
}

async function importStrava() {
  if (!stravaController.state.preview) return;
  const file = document.getElementById('strava-file').files[0];
  const mapping = {};
  const startDate = document.getElementById('strava-start-date').value;
  const endDate = document.getElementById('strava-end-date').value;
  const includeWalks = stravaIncludesWalks();
  const error = document.getElementById('strava-error');
  if (stravaController.state.key !== stravaInputKey(file, startDate, endDate, includeWalks)) {
    error.textContent = '檔案或日期範圍已變更，請等待最新預覽完成。';
    error.style.display = 'block';
    await previewStravaFile();
    return;
  }
  stravaController.state.preview.gear_groups.forEach((group, index) => {
    const value = document.getElementById(`strava-map-${index}`).value;
    mapping[group.gear] = value ? Number(value) : null;
  });
  const operation = stravaController.beginImport(stravaInputKey(file, startDate, endDate, includeWalks));
  if (!operation) return;
  const button = document.getElementById('strava-import-btn');
  button.disabled = true;
  setStravaMappingDisabled(true);
  try {
    const fields = {
      mapping: JSON.stringify(mapping), start_date: startDate, end_date: endDate,
      conflicts: JSON.stringify(stravaConflictChoices(stravaController.state.preview)),
    };
    if (includeWalks) fields.include_walks_hikes = 'true';
    const result = await stravaController.import(operation, file, fields);
    if (!stravaController.sessionCurrent(operation)) return;
    resourceStore.invalidate(['strava-history']);
    if (stravaController.ownsImport(operation)) {
      closeStravaModal();
      alert(`已匯入 ${result.imported} 筆跑步紀錄${result.skipped_unmapped ? `，略過 ${result.skipped_unmapped} 筆未配對鞋款` : ''}${result.skipped_deleted ? `，略過 ${result.skipped_deleted} 筆先前刪除的活動` : ''}${result.synced_mileage ? `，並同步 ${result.synced_mileage.toFixed(2)} km 至跑鞋與月跑量` : ''}${result.corrected_dates ? `，修正 ${result.corrected_dates} 筆跑步日期為台灣時間` : ''}${result.backfilled_durations ? `，補上 ${result.backfilled_durations} 筆跑步時間` : ''}${result.linked_manual ? `，連結 ${result.linked_manual} 筆手動紀錄` : ''}${result.skipped_manual_conflict ? `，略過 ${result.skipped_manual_conflict} 筆可能和手動紀錄重複的活動` : ''}${result.skipped_walk_hike ? `，未匯入 ${result.skipped_walk_hike} 筆健行／步行` : ''}。`);
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
      updateStravaImportButton();
    }
  }
}

function setStravaMappingDisabled(disabled) {
  document.querySelectorAll('#strava-mapping select, #strava-conflicts select').forEach(select => { select.disabled = disabled; });
}

// SPEC-101: a dashboard load that refreshes history reloads the Strava import list.
registerDataHooks({ history: () => loadStravaHistory() });

// SPEC-135: Escape closes this dialog through the shared registry (app-lifecycle.js).
registerDialog('strava-modal', { close: closeStravaModal });

// SPEC-113: this feature's delegated UI actions; markup names them with data-click and the like.
registerUiActions({
  click: {
    'open-strava': () => openStravaModal(),
    'close-strava': () => closeStravaModal(),
    'import-strava': () => importStrava(),
  },
  change: {
    'preview-strava': () => previewStravaFile(),
    'strava-date-warning': element => updateStravaDateWarning(Number(element.dataset.index)),
    'strava-conflict-choice': () => updateStravaImportButton(),
  },
});
