// ====== Inline Edit (double-click) ======
// 現役與退役共用的表格內即時編輯：差別只在操作哪個陣列（arr）
async function inlineEditRow(arr, idx, field, el) {
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'inline-input';
  input.value = arr[idx][field];
  const shoe = { ...arr[idx] };
  let committed = false;
  const commit = async () => {
    if (committed) return;
    committed = true;
    const val = parseFloat(input.value);
    if (Number.isFinite(val) && val >= 0) {
      try {
        await apiPut('/shoes/' + shoe.id, { [field]: val, expected_version: shoe.version });
        await loadData();
      } catch (e) {
        alert(e.message || '更新失敗');
      }
    }
    render();
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { committed = true; render(); } });
  el.innerHTML = '';
  el.appendChild(input);
  input.focus();
}

// ====== Shoe Category Helpers ======
function getSelectedCategories() {
  const checked = document.querySelectorAll('#f-category-group input[type="checkbox"]:checked');
  return Array.from(checked).map(cb => cb.value);
}

// ====== Modal (Shoe) ======
class ShoeModal {
  constructor() {
    this.el = document.getElementById('modal');
    this.formIds = {
      brand: 'f-brand', model: 'f-model', date: 'f-date', size: 'f-size',
      price: 'f-price', orig: 'f-orig', mileage: 'f-mileage',
      expected: 'f-expected', monthly: 'f-monthly'
    };
    this.btnDelete = document.getElementById('btn-delete');
    this.btnMove = document.getElementById('btn-move');
    this.titleEl = document.getElementById('modal-title');
    this.monthlyRow = document.getElementById('f-monthly').parentElement;

    // 綁定一次
    this.el.querySelector('.btn-primary').onclick = () => this.submit();
    this.btnDelete.onclick = () => this.delete();
    this.btnMove.onclick = () => this.move();
    this.el.onclick = e => { if (e.target === this.el) this.close(); };
  }

  // ── 公開 API ──────────────────────────────────────────────
  openForCreate() {
    this.mode = 'create';
    this.shoe = null;
    this.context = { mode: this.mode, shoe: null, session: captureAuthSession(), saving: false };
    this._resetForm();
    this._updateUI({ title: '新增跑鞋', showDelete: false, showMove: false, monthly: 60, monthlyVisible: true });
    this._show();
  }

  openForEdit(shoe, isRetired) {
    this.mode = isRetired ? 'editRetired' : 'editActive';
    this.shoe = { ...shoe };
    this.context = { mode: this.mode, shoe: this.shoe, session: captureAuthSession(), saving: false };
    this._fillForm(shoe);
    this._updateUI({
      title: isRetired ? '編輯退役跑鞋' : '編輯跑鞋',
      showDelete: true,
      showMove: true,
      moveText: isRetired ? '移至現役' : '移至退役',
      monthly: isRetired ? 0 : shoe.monthly_km,
      monthlyVisible: !isRetired
    });
    this._show();
  }

  // ── 內部邏輯 ──────────────────────────────────────────────
  _resetForm() {
    Object.values(this.formIds).forEach(id => document.getElementById(id).value = '');
    document.getElementById('f-date').value = localDateISO();
    document.getElementById('f-expected').value = 800;
    // Reset category checkboxes — default to "Daily" checked
    document.querySelectorAll('#f-category-group input[type="checkbox"]')
      .forEach(cb => cb.checked = cb.value === 'Daily');
  }

  _fillForm(s) {
    Object.entries(this.formIds).forEach(([k, id]) => {
      const field = k === 'orig' ? 'orig_price' : k === 'expected' ? 'expected_mileage' : k;
      document.getElementById(id).value = s[field] ?? '';
    });
    // Check category checkboxes based on the shoe's categories
    const cats = shoeCategories(s);
    document.querySelectorAll('#f-category-group input[type="checkbox"]')
      .forEach(cb => cb.checked = cats.includes(cb.value));
  }

  _updateUI({ title, showDelete, showMove, moveText, monthly, monthlyVisible }) {
    this.titleEl.textContent = title;
    this.btnDelete.style.display = showDelete ? 'inline-block' : 'none';
    this.btnMove.style.display = showMove ? 'inline-block' : 'none';
    this.btnMove.textContent = moveText || '';
    this.monthlyRow.style.display = monthlyVisible ? '' : 'none';
    document.getElementById('f-monthly').value = monthly;
  }

  _setBusy(busy) {
    this.saving = busy;
    this.el.querySelector('.btn-primary').disabled = busy;
    this.btnDelete.disabled = busy;
    this.btnMove.disabled = busy;
  }

  _show() { this._setBusy(false); this.el.classList.add('active'); }
  close() { this.context = null; this._setBusy(false); this.el.classList.remove('active'); this.shoe = null; }

  _canSubmit(context) {
    return context && !context.saving && isCurrentAuthSession(context.session);
  }

  async _mutate(context, request, errorMessage) {
    context.saving = true;
    this._setBusy(true);
    try {
      await request();
      if (!isCurrentAuthSession(context.session)) return;
      if (this.context === context) this.close();
      await loadData();
    } catch (error) {
      if (this.context === context && isCurrentAuthSession(context.session) && error.name !== 'AbortError') {
        alert(error.message || errorMessage);
      }
    } finally {
      context.saving = false;
      if (this.context === context) this._setBusy(false);
    }
  }

  _payload() {
    const get = id => document.getElementById(id).value;
    const num = id => parseFloat(get(id)) || 0;
    return {
      brand: get('f-brand').trim(),
      model: get('f-model').trim(),
      date: get('f-date'),
      size: get('f-size').trim(),
      price: num('f-price'),
      orig_price: num('f-orig'),
      mileage: num('f-mileage'),
      expected_mileage: num('f-expected'),
      monthly_km: num('f-monthly'),
      categories: getSelectedCategories(),
      is_retired: this.mode === 'editRetired'
    };
  }

  async submit() {
    const context = this.context;
    if (!this._canSubmit(context)) return;
    const data = this._payload();
    if (!data.brand || !data.model || !data.date) return alert('請填寫品牌、鞋款、日期');
    return this._mutate(context, () => {
      if (context.mode === 'create') return apiPost('/shoes', data);
      const changes = Object.fromEntries(Object.entries(data).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(context.shoe[key])));
      return apiPut('/shoes/' + context.shoe.id, { ...changes, expected_version: context.shoe.version });
    }, '儲存失敗');
  }

  async delete() {
    const context = this.context;
    if (!this._canSubmit(context) || !context.shoe) return;
    const shoe = context.shoe;
    if (!confirm(`確定刪除 ${shoe.brand} ${shoe.model}？跑步紀錄會保留，但鞋款無法復原。`)) return;
    return this._mutate(context, () => apiDelete('/shoes/' + shoe.id + '?expected_version=' + (shoe.version || 0)), '刪除失敗');
  }

  async move() {
    const context = this.context;
    if (!this._canSubmit(context) || !context.shoe) return;
    const shoe = context.shoe;
    const targetRetired = context.mode === 'editActive';
    if (!confirm(`確定要移至${targetRetired ? '退役' : '現役'}？`)) return;
    const payload = { is_retired: targetRetired, expected_version: shoe.version, monthly_km: shoe.monthly_km };
    if (targetRetired) {
      payload.monthly_km = 0;
    } else if (!payload.monthly_km) {
      // 退役時月跑量被歸零，回到現役時用其他現役鞋的平均月跑量當起始參考。
      const activeKm = shoes
        .filter(s => s.id !== shoe.id && !s.is_retired && s.monthly_km > 0)
        .map(s => s.monthly_km);
      payload.monthly_km = activeKm.length
        ? Math.round(activeKm.reduce((a, b) => a + b, 0) / activeKm.length * 10) / 10
        : 60;
    }
    return this._mutate(context, () => apiPut('/shoes/' + shoe.id, payload), '移動失敗');
  }
}

// 初始化一次
const shoeModal = new ShoeModal();

// 給舊呼叫處用的精簡 wrapper
function openAddModal()      { shoeModal.openForCreate(); }
function openEditModal(i)    { shoeModal.openForEdit(shoes[i], false); }
function openRetiredEditModal(i) { shoeModal.openForEdit(retiredShoes[i], true); }
function closeModal()        { shoeModal.close(); }

