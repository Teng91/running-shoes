// Run CRUD, paging, and shoe selection.
let runController = null;

async function initializeRunFeature() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  const { createRunController } = await import('./runtime/run-controller.mjs?v=' + encodeURIComponent(version));
  runController = createRunController({
    transport: { post: submitWorkspaceRun, put: apiPut, delete: apiDelete },
    session: { capture: captureAuthSession, current: isCurrentAuthSession },
    newKey: () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}-${Math.random()}`,
  });
}

registerFeatureReset('run-editor', () => {
  closeRunModal();
  runController.reset();
  document.getElementById('add-run-btn').disabled = false;
  document.getElementById('run-km').value = '';
  document.getElementById('run-duration').value = '';
  document.getElementById('run-activity').value = 'road';
  updateRunActivityHint('run');
  updateRunPacePreview('run');
  document.getElementById('run-error').textContent = '';
  document.getElementById('run-load-error').hidden = true;
  document.getElementById('run-month').value = localDateISO().slice(0, 7);
  document.getElementById('run-date').value = localDateISO();
  const select = document.getElementById('run-shoe');
  select.value = '';
  delete select.dataset.requiresSelection;
});

// SPEC-060: a run's moving time is typed as "32:15", "1:05:30" or whole minutes ("45").
// Returns seconds, null for an empty field, or NaN for text that is not a duration.
function parseRunDuration(text) {
  const value = String(text ?? '').trim();
  if (!value) return null;
  if (/^\d{1,4}$/.test(value)) return Number(value) > 0 ? Number(value) * 60 : NaN;
  const match = value.match(/^(?:(\d{1,3}):)?(\d{1,4}):(\d{2})$/);
  if (!match) return NaN;
  const [, hours, minutes, seconds] = match;
  if (Number(seconds) > 59 || (hours !== undefined && Number(minutes) > 59)) return NaN;
  const total = Number(hours || 0) * 3600 + Number(minutes) * 60 + Number(seconds);
  return total > 0 ? total : NaN;
}

// Phone number pads have no colon key: typed digits are grouped from the right,
// so 5200 reads 52:00 and 15959 reads 1:59:59. One or two digits stay whole minutes.
function groupDurationDigits(text) {
  const value = String(text ?? '');
  if (!/^[\d:]*$/.test(value)) return value;
  const digits = value.replace(/:/g, '');
  if (digits.length <= 2 || digits.length > 6) return digits.length > 6 ? value : digits;
  const seconds = digits.slice(-2);
  const rest = digits.slice(0, -2);
  if (rest.length <= 2) return `${rest}:${seconds}`;
  return `${rest.slice(0, -2)}:${rest.slice(-2)}:${seconds}`;
}

function formatDurationInput(element) {
  if (!element) return;
  const grouped = groupDurationDigits(element.value);
  if (grouped === element.value) return;
  element.value = grouped;
  element.setSelectionRange?.(grouped.length, grouped.length);
}

function formatRunDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = String(total % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

// Pace comes from the backend (pace_seconds_per_km); this only formats it.
function formatPace(secondsPerKm) {
  if (!Number.isFinite(secondsPerKm) || secondsPerKm <= 0) return '—';
  const total = Math.round(secondsPerKm);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')} /km`;
}

function plausibleRunPace(seconds, km) {
  if (!Number.isFinite(seconds) || !Number.isFinite(km) || km <= 0) return false;
  const pace = seconds / km;
  return pace >= RUN_PACE_MIN_SECONDS && pace <= RUN_PACE_MAX_SECONDS;
}

// Live hint under the duration field; the saved pace is always the backend's.
function updateRunPacePreview(prefix) {
  formatDurationInput(document.getElementById(`${prefix}-duration`));
  const target = document.getElementById(`${prefix}-pace-preview`);
  if (!target) return;
  const seconds = parseRunDuration(document.getElementById(`${prefix}-duration`)?.value);
  const km = parseFloat(document.getElementById(`${prefix}-km`).value);
  if (seconds === null) target.textContent = '填寫後會自動計算配速';
  else if (Number.isNaN(seconds)) target.textContent = '格式例如 32:15、1:05:30 或 45（分鐘）';
  else if (!Number.isFinite(km) || km <= 0) target.textContent = '填寫距離後會顯示配速';
  else if (!plausibleRunPace(seconds, km)) target.textContent = '配速不合理（每公里 1:00–60:00），請確認時間與距離';
  else target.textContent = `配速 ${formatPace(seconds / km)}`;
}

// Validates the duration field for a submit: { seconds } or { error }.
function readRunDuration(prefix, km) {
  const seconds = parseRunDuration(document.getElementById(`${prefix}-duration`)?.value);
  if (seconds === null) return { seconds: null };
  if (Number.isNaN(seconds)) return { error: '跑步時間格式例如 32:15、1:05:30 或 45（分鐘）。' };
  if (!plausibleRunPace(seconds, km)) return { error: '跑步時間換算的配速不合理（每公里 1:00–60:00），請確認時間與距離。' };
  return { seconds };
}

function allRunShoes() { return [...coreData.shoes, ...coreData.retiredShoes]; }
function runShoe(shoeId) { return allRunShoes().find(shoe => shoe.id === shoeId); }

// A run dated before the shoe's purchase date is usually the wrong shoe (SPEC-046).
// It stays a reminder: saving is still allowed (try-on runs, late-entered dates).
function prePurchaseWarning(runDate, shoe) {
  if (!shoe?.date || !/^\d{4}-\d{2}-\d{2}$/.test(runDate || '') || runDate >= shoe.date) return '';
  return `這天早於這雙鞋的購買日（${shoe.date.replace(/-/g, '/')}），確定是穿這雙嗎？仍可儲存。`;
}

function updateRunDateWarning(prefix) {
  const target = document.getElementById(`${prefix}-date-warning`);
  if (!target) return;
  const shoe = runShoe(parseInt(document.getElementById(`${prefix}-shoe`).value, 10));
  target.textContent = prePurchaseWarning(document.getElementById(`${prefix}-date`).value, shoe);
  target.hidden = !target.textContent;
}

// SPEC-096: a new run starts with the type the chosen shoe was last used for among the
// loaded runs (a trail pair is usually worn on trails), and road when it has none.
function lastActivityTypeForShoe(shoeId, rows) {
  const latest = (rows || []).filter(run => run.shoe_id === shoeId && RUN_ACTIVITY_TYPES.includes(run.activity_type))
    .reduce((best, run) => (!best || run.date > best.date || (run.date === best.date && run.id > best.id) ? run : best), null);
  return latest ? latest.activity_type : 'road';
}

function runActivityLabel(type) {
  return RUN_ACTIVITY_LABELS[type] || RUN_ACTIVITY_LABELS.road;
}

function updateRunActivityHint(prefix) {
  const target = document.getElementById(`${prefix}-activity-hint`);
  if (!target) return;
  const type = document.getElementById(`${prefix}-activity`)?.value || 'road';
  if (!RUN_TRAINING_ACTIVITY_TYPES.includes(type)) target.textContent = '只計入鞋子里程，不計入跑量、目標與配速';
  else if (!RUN_PACE_ACTIVITY_TYPES.includes(type)) target.textContent = '計入鞋子里程與跑量，不計入配速分析';
  else target.textContent = '';
}

function onRunShoeChange(prefix) {
  updateRunDateWarning(prefix);
  if (prefix !== 'run') return;
  const shoeId = parseInt(document.getElementById('run-shoe').value, 10);
  if (!shoeId) return;
  document.getElementById('run-activity').value = lastActivityTypeForShoe(shoeId, runController.state.rows);
  updateRunActivityHint('run');
}

function populateRunShoeSelects(selectedId = null) {
  const shoeList = allRunShoes();
  const options = shoeList.map(shoe =>
    `<option value="${shoe.id}">${esc(shoeLabel(shoe))}</option>`
  ).join('');
  ['run-shoe', 'edit-run-shoe'].forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;
    const previous = id === 'edit-run-shoe' && selectedId !== null
      ? selectedId : parseInt(select.value, 10);
    const requiresSelection = select.dataset.requiresSelection === 'true';
    select.innerHTML = options || '<option value="">請先新增跑鞋</option>';
    if (previous && shoeList.some(shoe => shoe.id === previous)) {
      select.value = String(previous);
      delete select.dataset.requiresSelection;
    } else if (id === 'edit-run-shoe' || previous || requiresSelection) {
      select.dataset.requiresSelection = 'true';
      select.insertAdjacentHTML(
        'afterbegin',
        '<option value="" selected disabled>原鞋款已刪除，請重新選擇</option>',
      );
    }
  });
  updateRunDateWarning('run');
  updateRunDateWarning('edit-run');
}

function selectedRunMonth() {
  const value = document.getElementById('run-month').value;
  return /^\d{4}-\d{2}$/.test(value) ? value : localDateISO().slice(0, 7);
}

// SPEC-101: the shown month's runs are one of the dashboard resources that loadData() reads.
// A page loaded for a month the user has since left is not applied, nor one an older request loaded.
function runsResourceReader() {
  return {
    scope: () => selectedRunMonth(),
    read(month) {
      const [year, monthNumber] = month.split('-').map(Number);
      const requestId = ++runController.state.listRequest;
      return Promise.all([fetchRunPage({ year, month: monthNumber }),
        apiGet(`/runs/summary?year=${year}&month=${monthNumber}`)])
        .then(([page, summary]) => ({ page, summary, requestId }));
    },
    current: month => month === selectedRunMonth(),
    apply({ page, summary, requestId }) {
      if (requestId !== runController.state.listRequest) return;
      Object.assign(runController.state, { rows: page.rows, summary, offset: 0, hasMore: page.hasMore, day: null });
      document.getElementById('run-load-error').hidden = true;
    },
  };
}

registerResourceReader('runs', runsResourceReader());
registerPanel('runs', { key: () => selectedRunMonth(), render: () => populateRunShoeSelects() });
// A full redraw also drops an in-flight read of the annual run totals.
registerDataHooks({ invalidated: () => { runController.state.annualRequest += 1; } });

const RUN_PAGE_SIZE = 200;

async function fetchRunPage({ year, month, offset = 0, day = null }) {
  const params = new URLSearchParams({ year, month, offset, limit: RUN_PAGE_SIZE + 1 });
  if (day !== null) params.set('day', String(day));
  const rows = await apiGet('/runs?' + params);
  return { rows: rows.slice(0, RUN_PAGE_SIZE), hasMore: rows.length > RUN_PAGE_SIZE };
}

async function fetchRunPages({ year, month = null }) {
  const rows = [];
  for (let offset = 0; ; offset += RUN_PAGE_SIZE) {
    const params = new URLSearchParams({
      year: String(year), limit: String(RUN_PAGE_SIZE), offset: String(offset),
    });
    if (month !== null) params.set('month', String(month));
    const page = await apiGet('/runs?' + params.toString());
    rows.push(...page);
    if (page.length < RUN_PAGE_SIZE) return rows;
  }
}

async function loadRunsForSelectedMonth({ offset = 0, day = null } = {}) {
  const requestId = ++runController.state.listRequest;
  runController.state.retryOptions = { offset, day };
  const [year, month] = selectedRunMonth().split('-').map(Number);
  try {
    const [page, summary] = await Promise.all([
      fetchRunPage({ year, month, offset, day }),
      apiGet(`/runs/summary?year=${year}&month=${month}`),
    ]);
    if (requestId !== runController.state.listRequest) return;
    runController.state.rows = page.rows;
    runController.state.summary = summary;
    runController.state.offset = offset;
    runController.state.hasMore = page.hasMore;
    runController.state.day = day;
    document.getElementById('run-load-error').hidden = true;
    renderedPanels.delete('runs');
    renderActivePanel();
  } catch (error) {
    if (requestId !== runController.state.listRequest) return;
    console.error('載入跑步紀錄失敗:', error);
    document.getElementById('run-load-error').hidden = false;
  }
}

function changeRunPage(direction) {
  return loadRunsForSelectedMonth({ offset: Math.max(0, runController.state.offset + direction * RUN_PAGE_SIZE), day: runController.state.day });
}

function filterRunDay(date) {
  return loadRunsForSelectedMonth({ day: Number(date.slice(8)) });
}

async function addRun() {
  refreshDateLimits();
  if (runController.saving) return;
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
  const duration = readRunDuration('run', km);
  if (duration.error) {
    error.textContent = duration.error;
    return;
  }
  const activityType = document.getElementById('run-activity').value || 'road';
  const payload = { date, km, shoe_id: shoeId, activity_type: activityType };
  if (duration.seconds !== null) payload.duration_seconds = duration.seconds;
  const form = {
    date: document.getElementById('run-date').value,
    km: document.getElementById('run-km').value,
    activity: document.getElementById('run-activity').value,
    duration: document.getElementById('run-duration').value,
    shoe: document.getElementById('run-shoe').value,
    month: document.getElementById('run-month').value,
  };
  const operation = runController.beginCreate(payload, form);
  if (!operation) return;
  try {
    document.getElementById('add-run-btn').disabled = true;
    if (!await runController.submitCreate(operation, payload)) return;
    const unchanged = matchesForm(Object.fromEntries(
      ['date', 'km', 'activity', 'duration', 'shoe'].map(key => ['run-' + key, form[key]])));
    if (unchanged) {
      document.getElementById('run-km').value = '';
      document.getElementById('run-duration').value = '';
      updateRunPacePreview('run');
    }
    if (unchanged && document.getElementById('run-month').value === form.month) {
      document.getElementById('run-month').value = date.slice(0, 7);
    }
    if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
    if (!runController.state.lastCreateResult?.queued) await loadData({ mutation: 'run' });
  } catch (errorMessage) {
    if (errorMessage.name === 'AbortError' || !runController.isCurrentCreate(operation)) return;
    error.textContent = errorMessage.message || '新增失敗，請稍後再試。';
  } finally {
    if (runController.finishCreate(operation)) {
      document.getElementById('add-run-btn').disabled = false;
    }
  }
}

function openRunModal(runId) {
  refreshDateLimits();
  const run = runController.state.rows.find(item => item.id === runId);
  if (!run) return;
  runController.openEditor(run);
  document.getElementById('edit-run-date').value = run.date;
  document.getElementById('edit-run-km').value = run.km;
  document.getElementById('edit-run-duration').value = formatRunDuration(run.duration_seconds);
  document.getElementById('edit-run-activity').value = run.activity_type || 'road';
  updateRunActivityHint('edit-run');
  updateRunPacePreview('edit-run');
  populateRunShoeSelects(run.shoe_id);
  document.getElementById('edit-run-error').style.display = 'none';
  document.getElementById('run-modal').classList.add('active');
}

function closeRunModal() {
  runController.closeEditor();
  document.getElementById('run-modal').classList.remove('active');
}

async function saveRun() {
  if (!runController.editor || runController.editor.saving) return;
  const snapshot = runController.editor;
  const error = document.getElementById('edit-run-error');
  if (!isCurrentAuthSession(snapshot.session)) return;
  const draft = readForm(['edit-run-date', 'edit-run-km', 'edit-run-activity', 'edit-run-duration', 'edit-run-shoe']);
  const payload = {
    date: document.getElementById('edit-run-date').value,
    km: parseFloat(document.getElementById('edit-run-km').value),
    shoe_id: parseInt(document.getElementById('edit-run-shoe').value, 10),
    activity_type: document.getElementById('edit-run-activity').value || 'road',
    expected_version: snapshot.version || 0,
  };
  if (!payload.date || !Number.isFinite(payload.km) || payload.km <= 0 || !payload.shoe_id) {
    error.textContent = '請完整填寫紀錄。'; error.style.display = 'block'; return;
  }
  if (payload.date > localDateISO()) {
    error.textContent = '跑步日期不可晚於今天。'; error.style.display = 'block'; return;
  }
  const duration = readRunDuration('edit-run', payload.km);
  if (duration.error) {
    error.textContent = duration.error; error.style.display = 'block'; return;
  }
  // An empty field clears a stored time (SPEC-060); the backend accepts null only here.
  payload.duration_seconds = duration.seconds;
  try {
    snapshot.saving = true;
    if (!await runController.saveEditor(snapshot, payload)) return;
    if (runController.editor === snapshot && matchesForm(draft)) {
      if (typeof discardWorkspaceEditor === 'function') discardWorkspaceEditor('run', snapshot.id);
      closeRunModal();
      document.getElementById('run-month').value = payload.date.slice(0, 7);
    }
    if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
    await loadData({ mutation: 'run' });
  } catch (saveError) {
    if (runController.editor !== snapshot || !isCurrentAuthSession(snapshot.session) || saveError.name === 'AbortError') return;
    error.textContent = saveError.message || '儲存失敗。';
    error.style.display = 'block';
  } finally {
    snapshot.saving = false;
  }
}

async function deleteEditingRun() {
  const run = runController.editor;
  if (run?.saving || (run && !isCurrentAuthSession(run.session))) return;
  if (!run || !confirm(`確定刪除 ${run.date.replace(/-/g, '/')} 的 ${run.km} km 紀錄？`)) return;
  try {
    run.saving = true;
    if (!await runController.deleteEditor(run)) return;
    if (runController.editor === run) {
      if (typeof discardWorkspaceEditor === 'function') discardWorkspaceEditor('run', run.id);
      closeRunModal();
    }
    if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
    await loadData({ mutation: 'run' });
  } catch (error) {
    if (runController.editor === run && isCurrentAuthSession(run.session) && error.name !== 'AbortError') alert(error.message || '刪除失敗');
  } finally { run.saving = false; }
}

// SPEC-108: the workspace reaches run state only through what this feature registers.
registerWorkspaceRuns({
  month: () => selectedRunMonth(),
  applyCachedPage: value => {
    Object.assign(runController.state, { rows: value.rows, summary: value.summary, hasMore: value.hasMore, offset: 0 });
  },
  shoes: () => allRunShoes(),
  formRestored: () => updateRunActivityHint('run'),
});

// SPEC-108: an open run editor is a workspace draft and can be resumed later.
registerWorkspaceEditor('run', {
  capture: () => {
    if (!document.getElementById('run-modal').classList.contains('active') || !runController.editor) return null;
    const { id, version, date, km, shoe_id, duration_seconds = null, activity_type = 'road' } = runController.editor;
    return { kind: 'run', base: { id, version, date, km, shoe_id, duration_seconds, activity_type },
      values: readForm(['edit-run-date', 'edit-run-km', 'edit-run-activity', 'edit-run-duration', 'edit-run-shoe']) };
  },
  resume: draft => {
    runController.openEditor(draft.base);
    document.getElementById('edit-run-date').value = draft.base.date;
    document.getElementById('edit-run-km').value = draft.base.km;
    document.getElementById('edit-run-duration').value = formatRunDuration(draft.base.duration_seconds);
    document.getElementById('edit-run-activity').value = draft.base.activity_type || 'road';
    populateRunShoeSelects(draft.base.shoe_id);
    document.getElementById('run-modal').classList.add('active');
  },
  restored: () => updateRunActivityHint('edit-run'),
});

// SPEC-113: this feature's delegated UI actions; markup names them with data-click and the like.
registerUiActions({
  click: {
    'retry-runs': () => loadRunsForSelectedMonth(runController.state.retryOptions),
    'load-runs': () => loadRunsForSelectedMonth(),
    'run-page': element => changeRunPage(Number(element.dataset.step)),
    'open-run': element => openRunModal(Number(element.dataset.runId)),
    'close-run-modal': () => closeRunModal(),
    'delete-editing-run': () => deleteEditingRun(),
    'filter-run-day': element => filterRunDay(element.dataset.date),
  },
  change: {
    'run-date-warning': element => updateRunDateWarning(element.dataset.form),
    'run-shoe': element => onRunShoeChange(element.dataset.form),
    'run-activity-hint': element => updateRunActivityHint(element.dataset.form),
    'load-runs': () => loadRunsForSelectedMonth(),
  },
  input: {
    'run-pace-preview': element => updateRunPacePreview(element.dataset.form),
    'duration-digits': element => formatDurationInput(element),
  },
  submit: {
    'add-run': () => addRun(),
    'save-run': () => saveRun(),
  },
});
