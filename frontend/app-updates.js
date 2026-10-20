// Installed-shell diagnostics and non-disruptive PWA update notification.
function initializeAppUpdates() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  document.getElementById('app-version').textContent = 'v' + version;
  if (!('serviceWorker' in navigator)) return;
  const banner = document.getElementById('app-update-notice');
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    // A first install merely takes control; only an actual different shell needs a reload.
    navigator.serviceWorker.controller?.postMessage({ type: 'GET_SHELL_VERSION' });
  });
  navigator.serviceWorker.addEventListener('message', event => {
    if (event.data?.type !== 'SHELL_VERSION' || event.data.version === version) return;
    banner.hidden = false;
  });
  navigator.serviceWorker.controller?.postMessage({ type: 'GET_SHELL_VERSION' });
  const register = async () => {
    try { await navigator.serviceWorker.register('/service-worker.js'); }
    catch (error) { console.warn('Service Worker 註冊失敗:', error); }
  };
  if (document.readyState === 'complete') register();
  else window.addEventListener('load', register, { once: true });
}

function applyAppUpdate() {
  if (!confirm('重新載入會清除尚未儲存的表單與對話內容。確定套用新版？')) return;
  window.location.reload();
}
