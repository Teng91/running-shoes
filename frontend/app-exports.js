// Authenticated shoe export and account backup downloads.
// ====== Export Modal Functions ======
function openExportModal() {
  document.getElementById('export-error').textContent = '';
  document.getElementById('export-mode').value = 'active';
  document.getElementById('export-format').value = 'xlsx';
  document.getElementById('export-modal').classList.add('active');
}

function closeExportModal() {
  document.getElementById('export-modal').classList.remove('active');
}

async function doExport() {
  const format = document.getElementById('export-format').value;
  const mode = document.getElementById('export-mode').value;
  const backendMode = mode === 'retired' ? 'retired' : (mode === 'all' ? 'all' : 'active');
  const displayMode = backendMode === 'retired' ? '退役' : (backendMode === 'all' ? '全部' : '現役');

  const btn = document.querySelector('#export-modal .btn-primary');
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '匯出中';

  try {
    const params = new URLSearchParams({
      format: format,
      mode: backendMode
    });

    const res = await authenticatedFetch(API_BASE + '/export?' + params.toString(), {
      headers: authHeaders()
    });

    if (!res.ok) {
      const err = await readAuthenticatedError(res);
      throw new Error(err.detail || `匯出失敗: ${res.status}`);
    }

    // Get filename from Content-Disposition header
    const disposition = res.headers.get('Content-Disposition');
    let filename = `running_shoes_${backendMode}_${new Date().toISOString().slice(0,10)}.${format}`;
    if (disposition) {
      const match = disposition.match(/filename="([^"]+)"/);
      if (match) filename = match[1];
    }

    // Download the file
    const blob = await readAuthenticatedBody(res, 'blob');
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);

    closeExportModal();

  } catch (e) {
    if (e.name === 'AbortError') return;
    console.error('匯出失敗:', e);
    document.getElementById('export-error').textContent = '匯出失敗：' + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

async function exportAccountData(fromWorkspace = false) {
  const error = document.getElementById(fromWorkspace ? 'workspace-export-status' : 'export-error');
  const button = fromWorkspace ? document.getElementById('workspace-export') : null;
  if (button?.disabled) return;
  const session = captureAuthSession();
  if (button) { button.disabled = true; button.textContent = '正在下載…'; }
  error.textContent = fromWorkspace ? '正在從目前網站下載此帳號的資料…' : '';
  try {
    const res = await authenticatedFetch(API_BASE + '/export/account', { headers: authHeaders() });
    if (!res.ok) throw new Error('完整備份失敗：' + res.status);
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const blob = await readAuthenticatedBody(res, 'blob');
    if (!isCurrentAuthSession(session)) return;
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = match ? match[1] : `running_shoes_account_${localDateISO()}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
    if (fromWorkspace) error.textContent = '資料檔案已交給瀏覽器，請查看下載項目。可在本機版登入後選擇此 JSON 匯入。';
    else closeExportModal();
  } catch (e) {
    if (e.name === 'AbortError' || !isCurrentAuthSession(session)) return;
    error.textContent = e.message || '完整備份失敗';
  } finally {
    if (button && isCurrentAuthSession(session)) { button.disabled = false; button.textContent = '下載目前帳號資料 JSON'; }
  }
}

registerFeatureReset('account-export', () => {
  document.getElementById('workspace-export-status').textContent = '';
  const button = document.getElementById('workspace-export');
  button.disabled = false; button.textContent = '下載目前帳號資料 JSON';
});
