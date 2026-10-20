// Application bootstrap and global dialog event wiring.
document.getElementById('monthly-modal').addEventListener('click', e => {
  if (e.target.id === 'monthly-modal') closeMonthlyModal();
});
document.getElementById('export-modal').addEventListener('click', e => {
  if (e.target.id === 'export-modal') closeExportModal();
});
document.getElementById('run-modal').addEventListener('click', e => {
  if (e.target.id === 'run-modal') closeRunModal();
});
document.getElementById('shoe-analysis-modal').addEventListener('click', e => {
  if (e.target.id === 'shoe-analysis-modal') closeShoeAnalytics();
});

// Check stored token on load
async function init() {
  // Every new document starts at the home page, regardless of legacy saved tabs.
  resetAppLayout();
  populateAddSelects();
  const today = localDateISO();
  document.getElementById('run-date').value = today;
  document.getElementById('run-date').max = today;
  document.getElementById('edit-run-date').max = today;
  document.getElementById('strava-start-date').max = today;
  document.getElementById('strava-end-date').max = today;
  document.getElementById('run-month').value = localDateISO().slice(0, 7);
  document.getElementById('report-month').value = previousMonthValue();
  if (authToken) {
    const session = captureAuthSession();
    try {
      const response = await authenticatedFetch(API_BASE + '/auth/me', { headers: authHeaders() });
      if (!response.ok) throw new Error('驗證服務暫時無法使用');
      showAppView({ keepBoot: true });
      loadAgentModels();
      await loadData();
      hideAppBoot();
    } catch (error) {
      if (error.name === 'AbortError' || !isCurrentAuthSession(session)) return;
      // 離線或伺服器暫時無法連線時保留 token，避免 PWA 被迫重新登入。
      console.warn('無法驗證登入狀態，保留目前工作階段:', error);
      showAppView({ keepBoot: true });
      loadAgentModels();
      await loadData();
      hideAppBoot();
    }
  } else {
    showLoginView();
  }
}

init().catch(error => {
  console.error('應用程式初始化失敗:', error);
  showAppBootError();
});

// Back/forward cache restores a live document without running init again.
window.addEventListener('pageshow', event => {
  if (!event.persisted) return;
  resetAppLayout();
  if (authToken) renderActivePanel();
});

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js')
      .catch(error => console.warn('Service Worker 註冊失敗:', error));
  });
}
