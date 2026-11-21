// DOM bridge for the injected account workspace; persistent records never contain auth tokens.
const localWorkspace = { controller: null, session: null, account: null, activating: null,
  runDraftId: null, consumedRunDraftId: null, fresh: new Set(), edited: new Set(), editors: {}, restoring: false, error: '', ready: false, syncing: null, syncRefreshRequested: false, channel: null };
const workspaceForms = {
  run: ['run-date', 'run-km', 'run-duration', 'run-shoe'],
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
      committed: notifyWorkspaceCommit,
    });
    if (typeof BroadcastChannel !== 'undefined') {
      try {
        localWorkspace.channel = new BroadcastChannel('running-shoes-workspace');
        localWorkspace.channel.onmessage = event => receiveWorkspaceCommit(event.data);
      } catch { localWorkspace.channel = null; }
    }
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
  window.addEventListener('focus', () => { void syncWorkspace({ refresh: true }); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void syncWorkspace({ refresh: true });
  });
  setInterval(() => { if (document.visibilityState === 'visible') void syncWorkspace(); }, 30000);
}

function notifyWorkspaceCommit(account) {
  try { localWorkspace.channel?.postMessage({ type: 'run-committed', account }); }
  catch { /* Manual/foreground sync also reloads cloud data. */ }
}

function receiveWorkspaceCommit(message) {
  if (message?.type !== 'run-committed' || !authToken || !navigator.onLine ||
      !localWorkspace.controller?.account || message.account !== localWorkspace.controller.account) return;
  void syncWorkspace({ refresh: true });
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
              if (name === 'goal') { prepareGoalForm(); setGoalField(id, String(values[id])); }
              else document.getElementById(id).value = String(values[id]);
            }
          }
        }
        const select = document.getElementById('run-shoe');
        if (draft.forms?.run?.['run-shoe'] && !select.value) select.dataset.requiresSelection = 'true';
        // Monthly record editing was removed in SPEC-039; drafts saved by older versions are dropped.
        const editors = Object.entries(draft.editors || {}).filter(([, editor]) => editor.kind !== 'monthly');
        localWorkspace.editors = { ...Object.fromEntries(editors), ...localWorkspace.editors };
      }
    } finally { localWorkspace.restoring = false; }
    await renderWorkspaceQueue();
    void syncWorkspace();
  })().catch(error => { localWorkspace.error = '恢復本機資料失敗：' + error.message; void renderWorkspaceQueue(); });
  return localWorkspace.activating;
}

function applyLocalResource(resource, value) {
  if (localWorkspace.fresh.has(resource)) return false;
  if (resource === 'shoes' || resource === 'monthly' || resource === 'goal') applyCoreResource(resource, value);
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
    const { id, version, date, km, shoe_id, duration_seconds = null } = runController.editor;
    return { kind: 'run', base: { id, version, date, km, shoe_id, duration_seconds },
      values: readForm(['edit-run-date', 'edit-run-km', 'edit-run-duration', 'edit-run-shoe']) };
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
    document.getElementById('edit-run-duration').value = formatRunDuration(draft.base.duration_seconds);
    populateRunShoeSelects(draft.base.shoe_id);
    document.getElementById('run-modal').classList.add('active');
  } else return;
  for (const [id, value] of Object.entries(draft.values || {})) document.getElementById(id).value = value;
  if (draft.inline) {
    const fields = { mileage: 'f-mileage', expected_mileage: 'f-expected', monthly_km: 'f-monthly' };
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
  if (busy) button.textContent = '處理中…';
}

async function syncWorkspace({ manual = false, refresh = false } = {}) {
  const unavailable = !authToken ? '請先登入，再同步此帳號的跑步紀錄。'
    : !navigator.onLine ? '目前離線；待送跑步會保留在這台裝置，連線後自動送出。'
    : !localWorkspace.controller?.account ? localWorkspace.error || '本機工作區尚未就緒，請稍後重試；若持續發生，請重新整理頁面。' : '';
  if (unavailable) {
    if (manual) setWorkspaceSyncState(unavailable);
    return;
  }
  localWorkspace.syncRefreshRequested ||= manual || refresh;
  if (localWorkspace.syncing) return localWorkspace.syncing;
  const pending = performWorkspaceSync(captureAuthSession());
  localWorkspace.syncing = pending;
  try { await pending; }
  finally {
    if (localWorkspace.syncing === pending) {
      localWorkspace.syncing = null;
      void renderWorkspaceQueue();
    }
  }
}

async function performWorkspaceSync(session) {
  setWorkspaceSyncState('正在處理待送跑步並更新雲端資料…', true);
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
      : synced ? `已同步 ${synced} 筆跑步紀錄，沒有待送跑步。`
        : '沒有待送跑步；新增成功的紀錄會直接存到雲端。';
    if (synced || localWorkspace.syncRefreshRequested) {
      try {
        do {
          localWorkspace.syncRefreshRequested = false;
          await refreshCoreData({ mutation: 'run' });
        } while (isCurrentAuthSession(session) && localWorkspace.syncRefreshRequested);
        if (!synced) message += ' 已重新載入雲端資料。';
      } catch {
        message += synced ? ' 紀錄已送出，但畫面更新失敗，請重新整理頁面。' : ' 雲端資料載入失敗，請按「更新雲端資料」重試。';
      }
    }
    if (isCurrentAuthSession(session)) setWorkspaceSyncState(message);
  } catch (error) {
    if (isCurrentAuthSession(session)) setWorkspaceSyncState('同步未完成，請重試：' + error.message);
  }
}

async function renderWorkspaceQueue() {
  const status = document.getElementById('workspace-status');
  if (!status) return;
  const session = captureAuthSession();
  let queue;
  try { queue = await localWorkspace.controller?.read('queue') || []; }
  catch (error) {
    if (!authToken || !isCurrentAuthSession(session)) return;
    localWorkspace.error = '本機儲存讀取失敗：' + error.message;
    status.textContent = localWorkspace.error;
    const button = document.getElementById('workspace-sync');
    if (button && !localWorkspace.syncing) { button.disabled = true; button.textContent = '本機儲存不可用'; }
    return;
  }
  if (!authToken || !isCurrentAuthSession(session)) return;
  status.textContent = localWorkspace.error || (queue.length
    ? navigator.onLine ? `${queue.length} 筆跑步只存在這台裝置，尚未送到雲端` : `${queue.length} 筆跑步留在這台裝置，等待連線後送到雲端`
    : navigator.onLine ? '已連線；新增成功的跑步會直接存到雲端' : '離線：新增的跑步會暫存在這台裝置，連線後送出');
  const button = document.getElementById('workspace-sync');
  if (button && !localWorkspace.syncing) {
    button.disabled = !navigator.onLine;
    button.textContent = !navigator.onLine ? '等待網路連線'
      : queue.length ? `同步待送跑步（${queue.length}）` : '更新雲端資料';
  }
  const target = document.getElementById('workspace-queue');
  if (!target) return;
  target.replaceChildren();
  if (!queue.length) {
    const empty = document.createElement('p'); empty.className = 'workspace-help';
    empty.textContent = navigator.onLine ? '沒有待送出的跑步。新增成功的紀錄會直接存到雲端。'
      : '目前沒有待送出的跑步；離線新增的跑步會留在這台裝置，連線後送出。'; target.append(empty);
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
    button.textContent = `繼續編輯 ${ { shoe: '鞋款', run: '跑步' }[draft.kind] } ${draft.base?.id || '新增草稿'}`;
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
  if (typeof renderEmailSection === 'function') void renderEmailSection();
}
function closeWorkspaceModal() {
  document.getElementById('workspace-modal').classList.remove('active');
  resetAccountRestore();
}

async function clearLocalWorkspace() {
  if (!confirm('清除此帳號在這個裝置的草稿、快取與尚未同步紀錄？伺服器資料不會刪除。')) return;
  const owner = getFormOperations('workspace-clear');
  const forms = Object.fromEntries(Object.entries(workspaceForms).map(([name, ids]) => [name, readForm(ids)]));
  const operation = owner.begin('clear', { forms, editors: localWorkspace.editors });
  if (!operation) return;
  try {
    await localWorkspace.controller.clear();
    if (!owner.owns('clear', operation)) return;
    let newerInput = false;
    for (const [name, ids] of Object.entries(workspaceForms)) {
      if (!formSnapshotMatches(operation.form.forms[name], readForm(ids))) { newerInput = true; continue; }
      if (name === 'goal') { getFormDraft('goal').reset(); prepareGoalForm(); }
      else {
        document.getElementById('run-km').value = '';
        document.getElementById('run-duration').value = '';
      }
    }
    for (const [key, draft] of Object.entries(operation.form.editors)) {
      if (JSON.stringify(localWorkspace.editors[key]) === JSON.stringify(draft)) delete localWorkspace.editors[key];
    }
    if (newerInput || Object.keys(localWorkspace.editors).length) persistWorkspaceDrafts();
    void renderWorkspaceQueue();
  }
  catch (error) { if (owner.owns('clear', operation)) workspaceStorageError(error); }
  finally { owner.finish('clear', operation); }
}

registerFeatureReset('local-workspace', () => {
  persistWorkspaceDrafts();
  localWorkspace.controller?.detach();
  localWorkspace.runDraftId = null; localWorkspace.consumedRunDraftId = null;
  localWorkspace.session = null; localWorkspace.account = null; localWorkspace.editors = {};
  localWorkspace.syncing = null; localWorkspace.syncRefreshRequested = false;
  setWorkspaceSyncState('');
  localWorkspace.fresh.clear();
  document.getElementById('workspace-modal').classList.remove('active');
  document.getElementById('workspace-status').textContent = '';
  document.getElementById('workspace-queue').replaceChildren();
  document.getElementById('workspace-drafts').replaceChildren();
});
