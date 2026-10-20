// Monthly mileage table, inline forms, and edit snapshot.
function renderMonthlyTable() {
  const tbody = document.getElementById('monthly-table');
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
let editingMonthly = null;

function editMonthlyMileage(idx) {
  const m = monthlyMileages[idx];
  if (!m) return;
  editingMonthly = { ...m, session: captureAuthSession() };
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
  const year = parseInt(document.getElementById('m-year').value, 10);
  const month = parseInt(document.getElementById('m-month').value, 10);
  const rawKm = parseFloat(document.getElementById('m-km').value);
  const km = Number.isFinite(rawKm) ? rawKm : 0;
  const errEl = document.getElementById('monthly-error');
  errEl.style.display = 'none';

  const button = document.getElementById('save-monthly-btn');
  try {
    snapshot.saving = true;
    button.disabled = true;
    await apiPut('/monthly-mileage/' + snapshot.id, {
      year, month, km, expected_version: snapshot.version || 0,
    });
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
  if (editingMonthly === snapshot) closeMonthlyModal();
  await loadData();
}

