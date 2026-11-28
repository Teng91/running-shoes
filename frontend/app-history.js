// History reads use resource tickets; each restore button retains its retry identity.
const workspaceHistory = { cursor: null, request: 0 };
async function loadWorkspaceHistory(more = false) {
  const session = captureAuthSession(), request = ++workspaceHistory.request;
  const cursor = more ? workspaceHistory.cursor : null;
  const target = document.getElementById('workspace-history');
  if (!more) target.textContent = '載入異動紀錄…';
  try {
    const result = await resourceStore.read('history', { key: String(cursor || ''),
      loader: () => apiGet('/history?limit=30' + (cursor ? '&before=' + cursor : '')) });
    if (!resourceStore.current(result) || !isCurrentAuthSession(session) || request !== workspaceHistory.request) return;
    if (result.status === 'rejected') throw result.error;
    if (!more) target.replaceChildren();
    workspaceHistory.cursor = result.value.next_cursor;
    document.getElementById('history-more').hidden = !workspaceHistory.cursor;
    for (const event of result.value.rows) {
      const row = document.createElement('div'); row.className = 'workspace-item';
      const text = document.createElement('p');
      const labels = { shoes: '鞋款', runs: '跑步', monthly_mileages: '月跑量', running_goals: '目標', race_goals: '目標賽事' };
      const actions = { insert: '新增', update: '更新', delete: '刪除' };
      const changes = Object.keys(event.after || {}).filter(key => !['id', 'version'].includes(key)
        && JSON.stringify(event.before?.[key]) !== JSON.stringify(event.after[key]));
      text.textContent = `${formatLocalTimestamp(event.created_at)} · ${labels[event.entity]} #${event.entity_id} · ${actions[event.action]} · ${event.reason}` +
        (changes.length ? ' · ' + changes.map(key => `${key}: ${JSON.stringify(event.before?.[key] ?? '—')} → ${JSON.stringify(event.after[key])}`).join('；') : '') +
        (event.imported ? '（備份歷史，唯讀）' : event.restored ? '（已復原）' : '');
      row.append(text);
      if (event.can_restore) {
        const button = document.createElement('button'); button.className = 'btn btn-edit'; button.textContent = '復原誤刪';
        const operationId = newOperationKey();
        let committed = false;
        button.onclick = async () => {
          if (!isCurrentAuthSession(session)) return;
          button.disabled = true;
          try {
            if (!committed) {
              await apiPost('/operations', { operation_id: operationId, kind: 'history.restore', entity_id: event.id });
              committed = true;
            }
            if (!isCurrentAuthSession(session)) return;
            // SPEC-128: a recovered target race is read by race preparation, not the core data.
            if (event.entity === 'race_goals') invalidateDataResources(['race-readiness', 'pace-analysis']);
            await refreshCoreData();
            if (!isCurrentAuthSession(session)) return;
            await loadWorkspaceHistory();
          } catch (error) {
            if (!isCurrentAuthSession(session) || error.name === 'AbortError') return;
            text.textContent += committed ? ' · 已復原，但畫面更新失敗，請重新載入資料。' : ' · ' + error.message;
            button.textContent = committed ? '重新載入資料' : '復原誤刪';
            button.disabled = false;
          }
        };
        row.append(button);
      }
      target.append(row);
    }
    if (!target.children.length) target.textContent = '尚無異動紀錄。';
  } catch (error) {
    if (isCurrentAuthSession(session) && request === workspaceHistory.request && error.name !== 'AbortError') target.textContent = '載入異動失敗：' + error.message;
  }
}
registerFeatureReset('workspace-history', () => {
  workspaceHistory.request++; workspaceHistory.cursor = null;
  document.getElementById('workspace-history').replaceChildren();
});

// SPEC-113: this feature's delegated UI actions; markup names them with data-click and the like.
registerUiActions({
  click: {
    'load-history': element => loadWorkspaceHistory(element.dataset.more === 'true'),
  },
});

// SPEC-145: the history loads whenever the settings modal opens, and again after an account
// restore (app-account-restore.js) reports new history through refreshPanels.
onWorkspaceModalOpen(() => { void loadWorkspaceHistory(); });
registerDataHooks({ refreshed: resource => { if (resource === 'account-history') void loadWorkspaceHistory(); } });
