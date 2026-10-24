// DOM bridge for the injected account workspace; persistent records never contain auth tokens.
const localWorkspace = { controller: null, session: null, account: null, activating: null,
  runDraftId: null, consumedRunDraftId: null, fresh: new Set(), edited: new Set(), editors: {}, restoring: false, error: '', ready: false, syncing: null };
const workspaceForms = {
  run: ['run-date', 'run-km', 'run-shoe'], monthly: ['add-year', 'add-month', 'add-km'],
  goal: ['goal-start-year', 'goal-monthly-km'],
};

async function initializeLocalWorkspace() {
  try {
    const version = document.querySelector('meta[name="app-asset-version"]').content;
    const { createWorkspaceController } = await import('./runtime/workspace-controller.mjs?v=' + encodeURIComponent(version));
    const storage = await openLocalWorkspaceStore();
    localWorkspace.controller = createWorkspaceController({ storage,
      session: { capture: captureAuthSession, current: isCurrentAuthSession },
      clock: () => Date.now(), newKey: newOperationKey,
      send: operation => apiPost('/runs', operation.payload, { idempotencyKey: operation.operation_id }),
      changed: () => { void renderWorkspaceQueue(); },
    });
    localWorkspace.ready = true;
  } catch (error) {
    localWorkspace.error = '本機儲存不可用，離線記錄與草稿恢復暫停：' + error.message;
  }
  document.addEventListener('input', persistWorkspaceDrafts);
  document.addEventListener('change', persistWorkspaceDrafts);
  window.addEventListener('pagehide', persistWorkspaceDrafts);
  window.addEventListener('online', () => { void syncWorkspace(); });
  window.addEventListener('offline', () => { void renderWorkspaceQueue(); });
  // Leases left by a closed tab are recovered on foreground or the next bounded tick.
  window.addEventListener('focus', () => { void syncWorkspace(); });
  setInterval(() => { if (document.visibilityState === 'visible') void syncWorkspace(); }, 30000);
}

function activateLocalWorkspace() {
  if (!localWorkspace.ready || !authToken || !currentUser) return Promise.resolve();
  const session = captureAuthSession();
  if (localWorkspace.session && isCurrentAuthSession(localWorkspace.session)) return localWorkspace.activating || Promise.resolve();
  localWorkspace.session = session;
  localWorkspace.account = `${window.location.origin}|${currentUser}`;
  localWorkspace.fresh.clear(); localWorkspace.edited.clear(); localWorkspace.editors = {};
  localWorkspace.activating = (async () => {
    const records = await localWorkspace.controller.attach(localWorkspace.account);
    if (!isCurrentAuthSession(session)) return;
    localWorkspace.restoring = true;
    try {
      for (const row of records.filter(row => row.key[1] === 'resource')) {
        if (applyLocalResource(row.key[2], row.value)) render(row.key[2]);
      }
      const draft = records.find(row => row.key[1] === 'drafts')?.value;
      if (draft) {
        if (![...localWorkspace.edited].some(id => workspaceForms.run.includes(id))) localWorkspace.runDraftId = draft.runDraftId || newOperationKey();
        for (const [name, values] of Object.entries(draft.forms || {})) {
          if (!workspaceForms[name]) continue;
          for (const id of workspaceForms[name]) {
            if (Object.hasOwn(values, id) && !localWorkspace.edited.has(id)) {
              if (name === 'goal') prepareGoalForm();
              document.getElementById(id).value = String(values[id]);
            }
          }
        }
        const select = document.getElementById('run-shoe');
        if (draft.forms?.run?.['run-shoe'] && !select.value) select.dataset.requiresSelection = 'true';
        localWorkspace.editors = { ...draft.editors, ...localWorkspace.editors };
      }
    } finally { localWorkspace.restoring = false; }
    await renderWorkspaceQueue();
    void syncWorkspace();
  })().catch(error => { localWorkspace.error = '恢復本機資料失敗：' + error.message; void renderWorkspaceQueue(); });
  return localWorkspace.activating;
}

function applyLocalResource(resource, value) {
  if (localWorkspace.fresh.has(resource)) return false;
  if (resource === 'shoes') [shoes, retiredShoes] = value;
  if (resource === 'monthly') monthlyMileages = value;
  if (resource === 'goal') runningGoal = value;
  if (resource === 'runs' && value.month === selectedRunMonth()) {
    Object.assign(runController.state, { rows: value.rows, summary: value.summary, hasMore: value.hasMore, offset: 0 });
  }
  return true;
}

function workspaceDataArrived(resource, value) {
  localWorkspace.fresh.add(resource);
  if (!localWorkspace.controller?.account || !authToken) return;
  if (resource === 'runs') value = { month: selectedRunMonth(), rows: value.page.rows,
    summary: value.summary, hasMore: value.page.hasMore };
  void localWorkspace.controller.save('resource', resource, value).catch(workspaceStorageError);
}

function workspaceStorageError(error) {
  localWorkspace.error = '本機儲存失敗，請保留目前輸入內容：' + error.message;
  void renderWorkspaceQueue();
}

function captureWorkspaceEditor() {
  const active = id => document.getElementById(id).classList.contains('active');
  if (active('modal') && shoeModal.context) {
    return { kind: 'shoe', base: shoeModal.mode === 'create' ? null : shoeModal.context.shoe, mode: shoeModal.mode,
      values: readForm(Object.values(shoeModal.formIds)), categories: getSelectedCategories() };
  }
  if (active('run-modal') && runController.editor) {
    const { id, version, date, km, shoe_id } = runController.editor;
    return { kind: 'run', base: { id, version, date, km, shoe_id },
      values: readForm(['edit-run-date', 'edit-run-km', 'edit-run-shoe']) };
  }
  if (active('monthly-modal') && editingMonthly) {
    const { id, version, year, month, km } = editingMonthly;
    return { kind: 'monthly', base: { id, version, year, month, km },
      values: readForm(['m-year', 'm-month', 'm-km']) };
  }
  for (const editor of inlineEditors.values()) {
    if (editor.draft) return { kind: editor.draft.kind, base: editor.draft.base,
      inline: { field: editor.draft.field, value: editor.draft.input.value } };
  }
  return null;
}

function persistWorkspaceDrafts(event = null) {
  if (event?.target?.id) {
    localWorkspace.edited.add(event.target.id);
    if (workspaceForms.run.includes(event.target.id)) localWorkspace.runDraftId = newOperationKey();
  }
  if (!localWorkspace.controller?.account || localWorkspace.restoring) return;
  const forms = {};
  if (!localWorkspace.runDraftId) localWorkspace.runDraftId = newOperationKey();
  if (document.getElementById('run-km').value && localWorkspace.runDraftId !== localWorkspace.consumedRunDraftId) forms.run = readForm(workspaceForms.run);
  if (document.getElementById('add-km').value) forms.monthly = readForm(workspaceForms.monthly);
  const goal = readForm(workspaceForms.goal);
  if (goal['goal-monthly-km'] && !formSnapshotMatches(goal, goalFormValues(runningGoal))) forms.goal = goal;
  const editor = captureWorkspaceEditor();
  if (editor) localWorkspace.editors[`${editor.kind}:${editor.base?.id || 'new'}`] = editor;
  const snapshot = { forms, runDraftId: localWorkspace.runDraftId, editors: structuredClone(localWorkspace.editors) };
  void localWorkspace.controller.save('drafts', 'forms', snapshot).catch(workspaceStorageError);
}

function discardWorkspaceEditor(kind, id) {
  delete localWorkspace.editors[`${kind}:${id || 'new'}`];
}

function resumeWorkspaceEditor(key) {
  const draft = localWorkspace.editors[key];
  if (!draft) return;
  closeWorkspaceModal();
  if (draft.kind === 'shoe') {
    if (draft.base) shoeModal.openForEdit(draft.base, draft.base.is_retired);
    else shoeModal.openForCreate();
    if (draft.categories) document.querySelectorAll('#f-category-group input').forEach(input => { input.checked = draft.categories.includes(input.value); });
  } else if (draft.kind === 'run') {
    runController.openEditor(draft.base);
    document.getElementById('edit-run-date').value = draft.base.date;
    document.getElementById('edit-run-km').value = draft.base.km;
    populateRunShoeSelects(draft.base.shoe_id);
    document.getElementById('run-modal').classList.add('active');
  } else {
    editingMonthly = { ...draft.base, ...getFormOperations('monthly').capture() };
    populateMonthlyEditSelects(draft.base.year, draft.base.month);
    document.getElementById('m-km').value = draft.base.km;
    document.getElementById('monthly-error').style.display = 'none';
    document.getElementById('monthly-modal').classList.add('active');
  }
  for (const [id, value] of Object.entries(draft.values || {})) document.getElementById(id).value = value;
  if (draft.inline) {
    const fields = { mileage: 'f-mileage', expected_mileage: 'f-expected', monthly_km: 'f-monthly', km: 'm-km' };
    document.getElementById(fields[draft.inline.field]).value = draft.inline.value;
  }
}

async function submitWorkspaceRun(url, payload, options) {
  const session = captureAuthSession();
  if (!localWorkspace.ready) {
    if (!navigator.onLine) throw Error('本機儲存不可用，請保留草稿並連線後重試');
    return apiPost(url, payload, options);
  }
  await activateLocalWorkspace();
  requireAuthSession(session);
  const draftId = localWorkspace.runDraftId || newOperationKey();
  await localWorkspace.controller.enqueue(payload, options.idempotencyKey, draftId);
  localWorkspace.consumedRunDraftId = draftId;
  requireAuthSession(session);
  if (navigator.onLine) await localWorkspace.controller.flush();
  const remaining = await localWorkspace.controller.read('queue');
  const queued = remaining.some(row => row.operation.operation_id === options.idempotencyKey);
  void renderWorkspaceQueue();
  return { queued };
}

function setWorkspaceSyncState(message, busy = false) {
  document.getElementById('workspace-sync-status').textContent = message;
  const button = document.getElementById('workspace-sync');
  button.disabled = busy;
  button.textContent = busy ? '同步中…' : '立即同步';
}

async function syncWorkspace({ manual = false } = {}) {
  const unavailable = !authToken ? '請先登入，再同步此帳號的跑步紀錄。'
    : !navigator.onLine ? '目前離線，尚未送出的跑步紀錄會保留在此裝置；請連線後再按立即同步。'
    : !localWorkspace.controller?.account ? localWorkspace.error || '本機工作區尚未就緒，請稍後重試；若持續發生，請重新整理頁面。' : '';
  if (unavailable) {
    if (manual) setWorkspaceSyncState(unavailable);
    return;
  }
  if (localWorkspace.syncing) return localWorkspace.syncing;
  const pending = performWorkspaceSync(captureAuthSession());
  localWorkspace.syncing = pending;
  try { await pending; }
  finally { if (localWorkspace.syncing === pending) localWorkspace.syncing = null; }
}

async function performWorkspaceSync(session) {
  setWorkspaceSyncState('正在檢查並送出此裝置的待同步跑步紀錄…', true);
  try {
    const { synced } = await localWorkspace.controller.flush();
    if (!isCurrentAuthSession(session)) return;
    const queue = await localWorkspace.controller.read('queue');
    if (!isCurrentAuthSession(session)) return;
    const blocked = queue.filter(row => row.status === 'blocked').length;
    let message = queue.length
      ? `本次已同步 ${synced} 筆跑步紀錄；仍有 ${queue.length} 筆留在此裝置。` +
        (blocked ? `${blocked} 筆需要處理，請查看下方原因並重新配對或移除。` : '') +
        (queue.length > blocked ? '其餘紀錄等待重試，請確認網路與登入狀態；其他分頁正在同步時請稍候。' : '')
      : synced ? `已同步 ${synced} 筆跑步紀錄，目前沒有待同步資料。`
        : '目前沒有待同步的跑步紀錄。已儲存的資料不需要再按同步。';
    if (synced) {
      try { await loadData({ mutation: 'run' }); }
      catch { message += ' 紀錄已送出，但畫面更新失敗，請重新整理頁面。'; }
    }
    if (isCurrentAuthSession(session)) setWorkspaceSyncState(message);
  } catch (error) {
    if (isCurrentAuthSession(session)) setWorkspaceSyncState('同步未完成，請重試：' + error.message);
  } finally {
    if (isCurrentAuthSession(session)) {
      const button = document.getElementById('workspace-sync');
      button.disabled = false; button.textContent = '立即同步';
    }
  }
}

async function renderWorkspaceQueue() {
  const status = document.getElementById('workspace-status');
  if (!status) return;
  const session = captureAuthSession();
  const queue = await localWorkspace.controller?.read('queue') || [];
  if (!authToken || !isCurrentAuthSession(session)) return;
  status.textContent = localWorkspace.error || (queue.length ? `${queue.length} 筆跑步已存本機，等待同步或處理` : navigator.onLine ? '本機草稿自動保存' : '離線：可新增跑步，連線後同步');
  const target = document.getElementById('workspace-queue');
  if (!target) return;
  target.replaceChildren();
  if (!queue.length) {
    const empty = document.createElement('p'); empty.className = 'workspace-help';
    empty.textContent = '目前沒有待同步的跑步紀錄。'; target.append(empty);
  }
  for (const row of queue) {
    const card = document.createElement('div'); card.className = 'workspace-item';
    const text = document.createElement('p');
    text.textContent = `${row.operation.payload.date} · ${row.operation.payload.km} km · ${row.status === 'blocked' ? '需要處理' : '等待同步'}${row.message ? '：' + row.message : ''}`;
    card.append(text);
    if (row.status === 'blocked') {
      const select = document.createElement('select'); select.setAttribute('aria-label', '重新配對鞋款');
      select.innerHTML = '<option value="">請明確選擇鞋款</option>' + allRunShoes().map(shoe => `<option value="${shoe.id}">${esc(shoeLabel(shoe))}</option>`).join('');
      const retry = document.createElement('button'); retry.className = 'btn btn-edit'; retry.textContent = '重新配對並重試';
      retry.onclick = async () => {
        if (!select.value) return;
        try { await localWorkspace.controller.resolve(row.operation.operation_id, Number(select.value)); await syncWorkspace(); }
        catch (error) { workspaceStorageError(error); }
      };
      card.append(select, retry);
    }
    const remove = document.createElement('button'); remove.className = 'btn btn-delete'; remove.textContent = '移除本機待送出紀錄';
    remove.onclick = async () => {
      if (!confirm('只移除此裝置的待送出紀錄，不會撤銷伺服器已成功儲存的紀錄。確定移除？')) return;
      try { await localWorkspace.controller.remove(row.operation.operation_id); } catch (error) { workspaceStorageError(error); }
    };
    card.append(remove); target.append(card);
  }
  const drafts = document.getElementById('workspace-drafts'); drafts.replaceChildren();
  for (const [key, draft] of Object.entries(localWorkspace.editors)) {
    const row = document.createElement('div'); row.className = 'workspace-item';
    const button = document.createElement('button'); button.className = 'btn btn-edit';
    button.textContent = `繼續編輯 ${ { shoe: '鞋款', run: '跑步', monthly: '月份' }[draft.kind] } ${draft.base?.id || '新增草稿'}`;
    button.onclick = () => resumeWorkspaceEditor(key);
    const discard = document.createElement('button'); discard.className = 'btn btn-cancel'; discard.textContent = '捨棄草稿';
    discard.onclick = () => { delete localWorkspace.editors[key]; persistWorkspaceDrafts(); void renderWorkspaceQueue(); };
    row.append(button, discard); drafts.append(row);
  }
}

function openWorkspaceModal() {
  document.getElementById('workspace-owner').textContent = '目前網站：' + window.location.origin + '；目前帳號：' + currentUser + '。匯入只寫入這個網站的此帳號。';
  document.getElementById('workspace-modal').classList.add('active');
  void renderWorkspaceQueue(); void loadWorkspaceHistory();
}
function closeWorkspaceModal() {
  document.getElementById('workspace-modal').classList.remove('active');
  resetAccountRestore();
}

async function clearLocalWorkspace() {
  if (!confirm('清除此帳號在這個裝置的草稿、快取與尚未同步紀錄？伺服器資料不會刪除。')) return;
  try {
    await localWorkspace.controller.clear(); localWorkspace.editors = {};
    document.getElementById('run-km').value = ''; document.getElementById('add-km').value = '';
    getFormDraft('goal').reset(); prepareGoalForm();
    void renderWorkspaceQueue();
  }
  catch (error) { workspaceStorageError(error); }
}

registerFeatureReset('local-workspace', () => {
  persistWorkspaceDrafts();
  localWorkspace.controller?.detach();
  localWorkspace.runDraftId = null; localWorkspace.consumedRunDraftId = null;
  localWorkspace.session = null; localWorkspace.account = null; localWorkspace.editors = {};
  localWorkspace.syncing = null;
  setWorkspaceSyncState('');
  localWorkspace.fresh.clear();
  document.getElementById('workspace-modal').classList.remove('active');
  document.getElementById('workspace-status').textContent = '';
  document.getElementById('workspace-queue').replaceChildren();
  document.getElementById('workspace-drafts').replaceChildren();
});
