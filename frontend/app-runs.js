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
  document.getElementById('run-error').textContent = '';
  document.getElementById('run-load-error').hidden = true;
  document.getElementById('run-month').value = localDateISO().slice(0, 7);
  document.getElementById('run-date').value = localDateISO();
  const select = document.getElementById('run-shoe');
  select.value = '';
  delete select.dataset.requiresSelection;
});

function localDateISO(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function allRunShoes() { return [...shoes, ...retiredShoes]; }
function runShoe(shoeId) { return allRunShoes().find(shoe => shoe.id === shoeId); }

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
}

function selectedRunMonth() {
  const value = document.getElementById('run-month').value;
  return /^\d{4}-\d{2}$/.test(value) ? value : localDateISO().slice(0, 7);
}

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

function monthRuns() {
  const month = selectedRunMonth();
  return runController.state.rows.filter(run => run.date.slice(0, 7) === month);
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
  const payload = { date, km, shoe_id: shoeId };
  const form = {
    date: document.getElementById('run-date').value,
    km: document.getElementById('run-km').value,
    shoe: document.getElementById('run-shoe').value,
    month: document.getElementById('run-month').value,
  };
  const operation = runController.beginCreate(payload, form);
  if (!operation) return;
  try {
    document.getElementById('add-run-btn').disabled = true;
    if (!await runController.submitCreate(operation, payload)) return;
    const unchanged = matchesForm(Object.fromEntries(
      ['date', 'km', 'shoe'].map(key => ['run-' + key, form[key]])));
    if (unchanged) document.getElementById('run-km').value = '';
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
  const draft = readForm(['edit-run-date', 'edit-run-km', 'edit-run-shoe']);
  const payload = {
    date: document.getElementById('edit-run-date').value,
    km: parseFloat(document.getElementById('edit-run-km').value),
    shoe_id: parseInt(document.getElementById('edit-run-shoe').value, 10),
    expected_version: snapshot.version || 0,
  };
  if (!payload.date || !Number.isFinite(payload.km) || payload.km <= 0 || !payload.shoe_id) {
    error.textContent = '請完整填寫紀錄。'; error.style.display = 'block'; return;
  }
  if (payload.date > localDateISO()) {
    error.textContent = '跑步日期不可晚於今天。'; error.style.display = 'block'; return;
  }
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
