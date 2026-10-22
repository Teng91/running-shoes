// Run CRUD, paging, and shoe selection.
let editingRun = null;
let runLoadRetryOptions = {};

registerFeatureReset('run-editor', () => {
  closeRunModal();
  runSaveOperation = null;
  runCreationDraft = null;
  runLoadRetryOptions = {};
  runSaving = false;
  document.getElementById('add-run-btn').disabled = false;
  document.getElementById('run-km').value = '';
  document.getElementById('run-error').textContent = '';
  document.getElementById('run-load-error').hidden = true;
  document.getElementById('run-month').value = localDateISO().slice(0, 7);
  document.getElementById('run-date').value = localDateISO();
});

function localDateISO(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function allRunShoes() { return [...shoes, ...retiredShoes]; }
function runShoe(shoeId) { return allRunShoes().find(shoe => shoe.id === shoeId); }

function populateRunShoeSelects(selectedId = null) {
  const shoeList = allRunShoes();
  const options = shoeList.map(shoe =>
    `<option value="${shoe.id}">${esc(shoe.brand)} ${esc(shoe.model)}${shoe.is_retired ? ' · 已退役' : ''}</option>`
  ).join('');
  ['run-shoe', 'edit-run-shoe'].forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;
    const previous = id === 'edit-run-shoe' && selectedId !== null
      ? selectedId : parseInt(select.value, 10);
    select.innerHTML = options || '<option value="">請先新增跑鞋</option>';
    if (previous && shoeList.some(shoe => shoe.id === previous)) {
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
  const requestId = ++runListRequestId;
  runLoadRetryOptions = { offset, day };
  const [year, month] = selectedRunMonth().split('-').map(Number);
  try {
    const [page, summary] = await Promise.all([
      fetchRunPage({ year, month, offset, day }),
      apiGet(`/runs/summary?year=${year}&month=${month}`),
    ]);
    if (requestId !== runListRequestId) return;
    runs = page.rows;
    runSummary = summary;
    runPageOffset = offset;
    runPageHasMore = page.hasMore;
    runDayFilter = day;
    document.getElementById('run-load-error').hidden = true;
    renderedPanels.delete('runs');
    renderActivePanel();
  } catch (error) {
    if (requestId !== runListRequestId) return;
    console.error('載入跑步紀錄失敗:', error);
    document.getElementById('run-load-error').hidden = false;
  }
}

function changeRunPage(direction) {
  return loadRunsForSelectedMonth({ offset: Math.max(0, runPageOffset + direction * RUN_PAGE_SIZE), day: runDayFilter });
}

function filterRunDay(date) {
  return loadRunsForSelectedMonth({ day: Number(date.slice(8)) });
}

function monthRuns() {
  const month = selectedRunMonth();
  return runs.filter(run => run.date.slice(0, 7) === month);
}

let runSaving = false;
let runSaveOperation = null;
let runCreationDraft = null;
async function addRun() {
  refreshDateLimits();
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
  const payload = { date, km, shoe_id: shoeId };
  const fingerprint = JSON.stringify(payload);
  if (!runCreationDraft || runCreationDraft.fingerprint !== fingerprint) {
    runCreationDraft = {
      fingerprint,
      key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}-${Math.random()}`,
    };
  }
  const operation = { session: captureAuthSession(), draft: runCreationDraft };
  runSaveOperation = operation;
  try {
    runSaving = true;
    document.getElementById('add-run-btn').disabled = true;
    await apiPost('/runs', payload, { idempotencyKey: operation.draft.key });
    if (runSaveOperation !== operation || !isCurrentAuthSession(operation.session)) return;
    runCreationDraft = null;
    document.getElementById('run-km').value = '';
    document.getElementById('run-month').value = date.slice(0, 7);
    await loadData();
  } catch (errorMessage) {
    if (errorMessage.name === 'AbortError' || runSaveOperation !== operation || !isCurrentAuthSession(operation.session)) return;
    error.textContent = errorMessage.message || '新增失敗，請稍後再試。';
  } finally {
    if (runSaveOperation === operation) {
      runSaveOperation = null;
      runSaving = false;
      document.getElementById('add-run-btn').disabled = false;
    }
  }
}

function openRunModal(runId) {
  refreshDateLimits();
  const run = runs.find(item => item.id === runId);
  if (!run) return;
  editingRun = { ...run, session: captureAuthSession() };
  document.getElementById('edit-run-date').value = run.date;
  document.getElementById('edit-run-km').value = run.km;
  populateRunShoeSelects(run.shoe_id);
  document.getElementById('edit-run-error').style.display = 'none';
  document.getElementById('run-modal').classList.add('active');
}

function closeRunModal() {
  editingRun = null;
  document.getElementById('run-modal').classList.remove('active');
}

async function saveRun() {
  if (!editingRun || editingRun.saving) return;
  const snapshot = editingRun;
  const error = document.getElementById('edit-run-error');
  if (!isCurrentAuthSession(snapshot.session)) return;
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
    await apiPut('/runs/' + snapshot.id, payload);
    if (!isCurrentAuthSession(snapshot.session)) return;
    if (editingRun === snapshot) {
      closeRunModal();
      document.getElementById('run-month').value = payload.date.slice(0, 7);
    }
    await loadData();
  } catch (saveError) {
    if (editingRun !== snapshot || !isCurrentAuthSession(snapshot.session) || saveError.name === 'AbortError') return;
    error.textContent = saveError.message || '儲存失敗。';
    error.style.display = 'block';
  } finally {
    snapshot.saving = false;
  }
}

async function deleteEditingRun() {
  const run = editingRun;
  if (run?.saving || (run && !isCurrentAuthSession(run.session))) return;
  if (!run || !confirm(`確定刪除 ${run.date.replace(/-/g, '/')} 的 ${run.km} km 紀錄？`)) return;
  try {
    run.saving = true;
    await apiDelete('/runs/' + run.id + '?expected_version=' + (run.version || 0));
    if (!isCurrentAuthSession(run.session)) return;
    if (editingRun === run) closeRunModal();
    await loadData();
  } catch (error) {
    if (editingRun === run && isCurrentAuthSession(run.session) && error.name !== 'AbortError') alert(error.message || '刪除失敗');
  } finally { run.saving = false; }
}
