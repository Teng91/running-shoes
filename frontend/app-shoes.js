// ====== Inline Edit (double-click) ======
// 現役與退役共用的表格內即時編輯：差別只在操作哪個陣列（arr）
async function inlineEditRow(arr, idx, field, el) {
  if (el.querySelector('.inline-input')) return;
  const operations = getFormOperations('shoes');
  const operation = operations.capture();
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'inline-input';
  input.value = arr[idx][field];
  const shoe = { ...arr[idx] };
  let committed = false;
  const editor = beginInlineEdit(el.closest('tbody').id, () => { committed = true; }, { kind: 'shoe', base: shoe, field, input });
  const commit = async () => {
    if (committed || !operations.current(operation)) return;
    committed = true;
    finishInlineEdit(editor);
    input.disabled = true;
    const val = parseFloat(input.value);
    if (Number.isFinite(val) && val >= 0) {
      try {
        await apiPut('/shoes/' + shoe.id, { [field]: val, expected_version: shoe.version });
        if (operations.current(operation)) {
          if (typeof discardWorkspaceEditor === 'function') discardWorkspaceEditor('shoe', shoe.id);
          if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
          await loadData({ mutation: 'shoe' });
        }
      } catch (e) {
        if (operations.current(operation) && e.name !== 'AbortError') alert(e.message || '更新失敗');
      }
    }
    if (operations.current(operation)) refreshPanels('shoes');
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') commit();
    if (e.key === 'Escape') { committed = true; finishInlineEdit(editor); refreshPanels('shoes'); }
  });
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
      nickname: 'f-nickname', brand: 'f-brand', model: 'f-model', date: 'f-date', size: 'f-size',
      price: 'f-price', orig: 'f-orig', mileage: 'f-mileage',
      expected: 'f-expected', monthly: 'f-monthly'
    };
    this.btnDelete = document.getElementById('btn-delete');
    this.btnMove = document.getElementById('btn-move');
    this.titleEl = document.getElementById('modal-title');
    this.monthlyRow = document.getElementById('f-monthly').parentElement;
    // SPEC-137: saving, deleting, moving and closing go through registerUiActions and
    // registerDialog below, like every other dialog.
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
    this.context.draftBase = this._payload();
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
      const field = k === 'orig' ? 'orig_price' : k === 'expected' ? 'expected_mileage' : k === 'monthly' ? 'monthly_km' : k;
      document.getElementById(id).value = s[field] ?? '';
    });
    // Check category checkboxes based on the shoe's categories
    const cats = shoeCategories(s);
    document.querySelectorAll('#f-category-group input[type="checkbox"]')
      .forEach(cb => cb.checked = cats.includes(cb.value));
  }

  _updateUI({ title, showDelete, showMove, moveText, monthly, monthlyVisible }) {
    this.titleEl.textContent = title;
    this.btnDelete.hidden = !showDelete;
    this.btnMove.hidden = !showMove;
    document.getElementById('shoe-secondary-actions').hidden = !showDelete && !showMove;
    this.btnMove.textContent = moveText || '';
    this.monthlyRow.hidden = !monthlyVisible;
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

  async _mutate(context, request, errorMessage, acknowledged = null) {
    const operations = getFormOperations('shoes');
    const operation = operations.begin(context, this._formSnapshot());
    if (!operation) return;
    context.saving = true;
    this._setBusy(true);
    try {
      const saved = await request();
      if (!operations.owns(context, operation)) return;
      const baseline = acknowledged || operation.form;
      if (this.context === context && matchesForm(baseline.fields)
          && JSON.stringify(getSelectedCategories()) === baseline.categories) {
        if (typeof discardWorkspaceEditor === 'function') discardWorkspaceEditor('shoe', context.mode === 'create' ? null : context.shoe?.id);
        this.close();
      }
      if (this.context === context && saved?.version !== undefined) {
        this._rebase(context, saved, baseline);
      }
      if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
      await loadData({ mutation: 'shoe' });
    } catch (error) {
      if (this.context === context && operations.owns(context, operation) && error.name !== 'AbortError') {
        alert(error.message || errorMessage);
      }
    } finally {
      context.saving = false;
      if (operations.finish(context, operation) && this.context === context) this._setBusy(false);
    }
  }

  _rebase(context, saved, submitted) {
    const draft = this._formSnapshot();
    const dirtyFields = Object.keys(draft.fields).filter(id => draft.fields[id] !== submitted.fields[id]);
    const dirtyCategories = draft.categories !== submitted.categories;
    context.shoe = this.shoe = { ...saved };
    // A create form retained for the next shoe remains a create form.
    if (context.mode === 'create') return;
    const retired = Boolean(saved.is_retired);
    context.mode = this.mode = retired ? 'editRetired' : 'editActive';
    this._fillForm(saved);
    this._updateUI({ title: retired ? '編輯退役跑鞋' : '編輯跑鞋', showDelete: true, showMove: true,
      moveText: retired ? '移至現役' : '移至退役', monthly: saved.monthly_km, monthlyVisible: !retired });
    context.draftBase = this._payload();
    for (const id of dirtyFields) document.getElementById(id).value = draft.fields[id];
    if (dirtyCategories) {
      const categories = JSON.parse(draft.categories);
      document.querySelectorAll('#f-category-group input[type="checkbox"]')
        .forEach(checkbox => checkbox.checked = categories.includes(checkbox.value));
    }
  }

  _formSnapshot() {
    return { fields: readForm(Object.values(this.formIds)), categories: JSON.stringify(getSelectedCategories()) };
  }

  _payload() {
    const get = id => document.getElementById(id).value;
    const num = id => parseFloat(get(id)) || 0;
    return {
      nickname: get('f-nickname').trim(),
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
      const changes = Object.fromEntries(Object.entries(data).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify((context.draftBase || context.shoe)[key])));
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
      const activeKm = coreData.shoes
        .filter(s => s.id !== shoe.id && !s.is_retired && s.monthly_km > 0)
        .map(s => s.monthly_km);
      payload.monthly_km = activeKm.length
        ? Math.round(activeKm.reduce((a, b) => a + b, 0) / activeKm.length * 10) / 10
        : 60;
    }
    // Movement acknowledges only lifecycle fields; unsaved descriptive fields retain
    // their original baseline, including edits made before clicking Move.
    const baseline = this._formSnapshot();
    for (const [name, id] of Object.entries(this.formIds)) {
      const key = ({ orig: 'orig_price', expected: 'expected_mileage', monthly: 'monthly_km' })[name] || name;
      if (key !== 'monthly_km') baseline.fields[id] = String(context.draftBase[key] ?? '');
    }
    baseline.categories = JSON.stringify(context.draftBase.categories);
    return this._mutate(context, () => apiPut('/shoes/' + shoe.id, payload), '移動失敗', baseline);
  }
}

// 初始化一次
const shoeModal = new ShoeModal();
registerFeatureReset('shoe-editor', () => shoeModal.close());

// 給舊呼叫處用的精簡 wrapper
function openAddModal()      { shoeModal.openForCreate(); }
function openEditModal(i)    { shoeModal.openForEdit((inlineTableRows.get('shoe-table') || coreData.shoes)[i], false); }
function openRetiredEditModal(i) { shoeModal.openForEdit((inlineTableRows.get('retired-table') || coreData.retiredShoes)[i], true); }
function closeModal()        { shoeModal.close(); }

// SPEC-107: an open shoe form is saved as a workspace draft and can be resumed later.
registerWorkspaceEditor('shoe', {
  capture: () => {
    if (!document.getElementById('modal').classList.contains('active') || !shoeModal.context) return null;
    return { kind: 'shoe', base: shoeModal.mode === 'create' ? null : shoeModal.context.shoe, mode: shoeModal.mode,
      values: readForm(Object.values(shoeModal.formIds)), categories: getSelectedCategories() };
  },
  resume: draft => {
    if (draft.base) shoeModal.openForEdit(draft.base, draft.base.is_retired);
    else shoeModal.openForCreate();
    if (draft.categories) document.querySelectorAll('#f-category-group input').forEach(input => { input.checked = draft.categories.includes(input.value); });
  },
});

// SPEC-135: Escape closes this dialog through the shared registry (app-lifecycle.js).
// SPEC-137: a backdrop click closes it too, as its own click handler used to.
registerDialog('modal', { close: closeModal, backdrop: true });

// SPEC-113: this feature's delegated UI actions; markup names them with data-click and the like.
registerUiActions({
  click: {
    'add-shoe': () => openAddModal(),
    'edit-shoe': element => openEditModal(Number(element.dataset.index)),
    'edit-retired-shoe': element => openRetiredEditModal(Number(element.dataset.index)),
    'close-shoe-modal': () => closeModal(),
    'delete-shoe': () => shoeModal.delete(),
    'move-shoe': () => shoeModal.move(),
  },
  submit: {
    'save-shoe': () => shoeModal.submit(),
  },
  dblclick: {
    'inline-edit': element => inlineEditRow(
      inlineTableRows.get(element.dataset.table), Number(element.dataset.index), element.dataset.field, element,
    ),
  },
});
