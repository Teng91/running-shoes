// Run CRUD, paging, and shoe selection.
let editingRunId = null;

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
    await apiPost('/runs', { date, km, shoe_id: shoeId });
    document.getElementById('run-km').value = '';
    document.getElementById('run-month').value = date.slice(0, 7);
    await loadData();
  } catch (errorMessage) {
    error.textContent = errorMessage.message || '新增失敗，請稍後再試。';
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
    error.textContent = '請完整填寫紀錄。'; error.style.display = 'block'; return;
  }
  if (payload.date > localDateISO()) {
    error.textContent = '跑步日期不可晚於今天。'; error.style.display = 'block'; return;
  }
  try {
    await apiPut('/runs/' + editingRunId, payload);
    closeRunModal();
    document.getElementById('run-month').value = payload.date.slice(0, 7);
    await loadData();
  } catch (saveError) {
    error.textContent = saveError.message || '儲存失敗。';
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
  } catch (error) { alert(error.message || '刪除失敗'); }
}
