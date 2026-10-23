// Monthly mileage table, inline forms, and edit snapshot.
registerFeatureReset('monthly-editor', () => {
  closeMonthlyModal();
  monthlySaving = false;
  document.getElementById('add-monthly-btn').disabled = false;
  document.getElementById('add-km').value = '';
  document.getElementById('add-error').style.display = 'none';
});
function renderMonthlyTable() {
  if (preserveInlineTable('monthly-table')) return;
  const tbody = document.getElementById('monthly-table');
  inlineTableRows.set('monthly-table', monthlyMileages.map(entry => ({ ...entry })));
  if (monthlyMileages.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:24px;">尚無月跑量紀錄，使用上方表單新增</td></tr>';
    return;
  }
  tbody.innerHTML = monthlyMileages.map((m, i) => `
    <tr>
      <td class="numeric">${m.year}</td>
      <td class="numeric">${m.month}</td>
      <td class="numeric">${(m.km - (m.adjustment_km || 0)).toFixed(2)} km</td>
      <td class="numeric">${(m.adjustment_km || 0).toFixed(2)} km</td>
      <td class="editable numeric" ondblclick="inlineEditMonthly(${i},'km',this)"><strong>${m.km.toFixed(2)}</strong></td>
      <td>
        <button class="btn btn-sm btn-edit" onclick="editMonthlyMileage(${i})">編輯</button>
        <button class="btn btn-sm btn-delete" onclick="deleteMonthlyMileage(${i})">刪除</button>
      </td>
    </tr>
  `).join('');
}

async function inlineEditMonthly(idx, field, el) {
  if (el.querySelector('.inline-input')) return;
  const operations = getFormOperations('monthly');
  const operation = operations.capture();
  const entry = { ...(inlineTableRows.get('monthly-table') || monthlyMileages)[idx] };
  const current = entry[field];
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'inline-input';
  input.step = '0.01';
  input.min = '0';
  input.value = current;
  let committed = false;
  const editor = beginInlineEdit('monthly-table', () => { committed = true; }, { kind: 'monthly', base: entry, field, input });
  const commit = async () => {
    if (committed || !operations.current(operation)) return;
    committed = true;
    finishInlineEdit(editor);
    input.disabled = true;
    const val = parseFloat(input.value);
    if (Number.isFinite(val) && val >= 0) {
      try {
        await apiPut('/monthly-mileage/' + entry.id, {
          km: val,
          expected_version: entry.version || 0,
        });
        if (operations.current(operation) && typeof discardWorkspaceEditor === 'function') discardWorkspaceEditor('monthly', entry.id);
        if (operations.current(operation) && typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
      } catch (e) {
        if (operations.current(operation) && e.name !== 'AbortError') alert(e.message || '更新失敗');
      }
    }
    if (operations.current(operation)) {
      await loadData({ mutation: 'monthly' });
      render('monthly');
    }
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') commit();
    if (e.key === 'Escape') { committed = true; finishInlineEdit(editor); render('monthly'); }
  });
  el.innerHTML = '';
  el.appendChild(input);
  input.focus();
}

async function deleteMonthlyMileage(idx) {
  const operations = getFormOperations('monthly');
  const operation = operations.capture();
  const m = { ...(inlineTableRows.get('monthly-table') || monthlyMileages)[idx] };
  if (!confirm(`確定要刪除 ${m.year} 年 ${m.month} 月的紀錄？`)) return;
  try {
    await apiDelete('/monthly-mileage/' + m.id + '?expected_version=' + (m.version || 0));
  } catch (e) {
    if (!operations.current(operation) || e.name === 'AbortError') return;
    console.error('刪除失敗:', e);
    alert(e.message || '刪除失敗');
    return;
  }
  if (operations.current(operation)) await loadData({ mutation: 'monthly' });
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
  const operations = getFormOperations('monthly');
  if (monthlySaving) return;
  const form = readForm(['add-year', 'add-month', 'add-km']);
  const year = Number(form['add-year']), month = Number(form['add-month']);
  const km = parseFloat(form['add-km']);
  const errEl = document.getElementById('add-error');
  errEl.style.display = 'none';
  if (!Number.isFinite(km) || km < 0) {
    errEl.textContent = '請輸入有效的非負跑量；若要記錄零，請明確輸入 0。';
    errEl.style.display = 'block';
    return;
  }
  const operation = operations.begin('create', form);
  if (!operation) return;
  const button = document.getElementById('add-monthly-btn');
  try {
    monthlySaving = true;
    button.disabled = true;
    await apiPost('/monthly-mileage', { year, month, km });
    if (!operations.owns('create', operation)) return;
    if (matchesForm(operation.form)) document.getElementById('add-km').value = '';
    if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
    await loadData({ mutation: 'monthly' });
  } catch (e) {
    if (!operations.owns('create', operation) || e.name === 'AbortError' || !matchesForm(operation.form)) return;
    errEl.textContent = translateError(e.message) || '儲存失敗';
    errEl.style.display = 'block';
  } finally {
    if (operations.finish('create', operation)) {
      monthlySaving = false;
      button.disabled = false;
    }
  }
}

// ====== Monthly Mileage: edit modal ======
let editingMonthly = null;

function editMonthlyMileage(idx) {
  const m = (inlineTableRows.get('monthly-table') || monthlyMileages)[idx];
  if (!m) return;
  editingMonthly = { ...m, ...getFormOperations('monthly').capture() };
  document.getElementById('save-monthly-btn').disabled = false;
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
  editingMonthly = null;
}

async function saveMonthlyMileage() {
  if (!editingMonthly || editingMonthly.saving) return;
  const snapshot = editingMonthly;
  if (!isCurrentAuthSession(snapshot.session)) return;
  const draft = readForm(['m-year', 'm-month', 'm-km']);
  const year = parseInt(document.getElementById('m-year').value, 10);
  const month = parseInt(document.getElementById('m-month').value, 10);
  const rawKm = parseFloat(document.getElementById('m-km').value);
  const errEl = document.getElementById('monthly-error');
  errEl.style.display = 'none';
  if (!Number.isFinite(rawKm) || rawKm < 0) {
    errEl.textContent = '請輸入有效的非負跑量；若要清零，請明確輸入 0。';
    errEl.style.display = 'block';
    return;
  }
  const km = rawKm;

  const button = document.getElementById('save-monthly-btn');
  try {
    snapshot.saving = true;
    button.disabled = true;
    const saved = await apiPut('/monthly-mileage/' + snapshot.id, {
      year, month, km, expected_version: snapshot.version || 0,
    });
    if (editingMonthly === snapshot && isCurrentAuthSession(snapshot.session) && saved?.version !== undefined) snapshot.version = saved.version;
  } catch (e) {
    if (editingMonthly !== snapshot || !isCurrentAuthSession(snapshot.session) || e.name === 'AbortError') return;
    errEl.textContent = translateError(e.message) || '儲存失敗';
    errEl.style.display = 'block';
    return;
  } finally {
    snapshot.saving = false;
    if (editingMonthly === snapshot) button.disabled = false;
  }
  if (!isCurrentAuthSession(snapshot.session)) return;
  if (editingMonthly === snapshot && matchesForm(draft)) {
    if (typeof discardWorkspaceEditor === 'function') discardWorkspaceEditor('monthly', snapshot.id);
    closeMonthlyModal();
  }
  if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
  await loadData({ mutation: 'monthly' });
}

