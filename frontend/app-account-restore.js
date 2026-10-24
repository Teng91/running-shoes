// Account restore preview owns its file revision and window/session operation.
let accountRestore = null;
async function initializeAccountRestoreFeature() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  const { createAccountRestoreController } = await import('./runtime/account-restore-controller.mjs?v=' + encodeURIComponent(version));
  accountRestore = createAccountRestoreController({ session: { capture: captureAuthSession, current: isCurrentAuthSession },
    newKey: newOperationKey, transport: {
      preview: (raw, mode) => jsonRequest('/account-restore/preview?mode=' + encodeURIComponent(mode), { method: 'POST', headers: authHeaders(), body: raw }),
      apply: (token, operationId) => apiPost('/account-restore/apply', { token }, { idempotencyKey: operationId }),
      discard: token => apiDelete('/account-restore/preview/' + encodeURIComponent(token)),
    } });
}
function resetAccountRestore() {
  accountRestore?.reset();
  document.getElementById('restore-file').value = '';
  document.getElementById('restore-file').disabled = false;
  document.getElementById('restore-mode').disabled = false;
  document.getElementById('restore-mode').value = 'merge';
  document.getElementById('restore-preview').textContent = '';
  document.getElementById('restore-apply').disabled = true;
}

async function previewAccountRestore() {
  const operation = accountRestore?.beginPreview();
  if (!operation) return;
  const file = document.getElementById('restore-file').files[0];
  const mode = document.getElementById('restore-mode').value || 'merge';
  const text = document.getElementById('restore-preview');
  document.getElementById('restore-apply').disabled = true;
  if (!file) { text.textContent = ''; return; }
  if (file.size > 20 * 1024 * 1024) { text.textContent = '備份不可超過 20 MB'; return; }
  text.textContent = '正在驗證備份…';
  try {
    const raw = await file.text();
    if (!accountRestore.current(operation)) return;
    const preview = await accountRestore.preview(operation, raw, mode);
    if (!preview) return;
    const summary = preview.summary;
    const source = `來源帳號：${summary.source_username}；匯出時間：${summary.exported_at}。接收網站：${window.location.origin}；接收帳號：${currentUser}。`;
    const updates = mode === 'update' ? `將更新 ${summary.updated_shoes} 雙鞋、${summary.updated_runs} 筆跑步、${summary.updated_months} 個月份調整、${summary.updated_reports} 份月報${summary.updated_goal ? '及跑量目標' : ''}。` : '';
    text.textContent = source + `預計新增 ${summary.new_shoes} 雙鞋、${summary.new_runs} 筆跑步。` + updates + `${summary.policy}。` +
      `另有 ${summary.monthly_records} 個月份、${summary.reports} 份月報、${summary.history_records} 筆唯讀歷史；匯入摘要新增 ${summary.new_import_summaries} 筆、略過 ${summary.skipped_import_summaries} 筆（保留既有摘要及容量限制）。` +
      (summary.legacy ? ' 此為舊版備份，只保證相同檔案重複匯入不重建。' : ' 相同來源紀錄再次匯入不重建。');
    document.getElementById('restore-apply').disabled = false;
  } catch (error) {
    if (accountRestore.current(operation) && error.name !== 'AbortError') text.textContent = error.message;
  }
}

async function applyAccountRestore() {
  if (!accountRestore?.state.preview || accountRestore.state.pending) return;
  const preview = accountRestore.state.preview;
  const updating = preview.summary?.mode === 'update';
  if (updating && !confirm(`將把檔案資料匯入 ${window.location.origin} 的帳號「${currentUser}」，並覆寫同來源紀錄、檔案內月份調整、目標及月報。額外資料保留。請確認已下載接收帳號的備份。確定繼續？`)) return;
  const operation = accountRestore.beginApply();
  if (!operation) return;
  const button = document.getElementById('restore-apply');
  button.disabled = true;
  document.getElementById('restore-file').disabled = true;
  document.getElementById('restore-mode').disabled = true;
  try {
    if (!await accountRestore.apply(operation) || !accountRestore.sessionCurrent(operation)) return;
    if (accountRestore.ownsApply(operation)) {
      document.getElementById('restore-preview').textContent = updating ? '資料匯入完成，同來源資料已更新，額外資料已保留。' : '合併還原完成，現有內容已保留。';
    }
    await loadData();
    if (accountRestore.ownsApply(operation)) void loadWorkspaceHistory();
  } catch (error) {
    if (!accountRestore.ownsApply(operation) || error.name === 'AbortError') return;
    document.getElementById('restore-preview').textContent = error.message + '；連線中斷可重試同一操作，資料變動請重新預覽。';
    button.disabled = false;
  } finally {
    const owned = accountRestore.ownsApply(operation);
    accountRestore.finishApply(operation);
    if (owned) {
      document.getElementById('restore-file').disabled = false;
      document.getElementById('restore-mode').disabled = false;
    }
  }
}
registerFeatureReset('account-restore', resetAccountRestore);
