// Keep an installed PWA on the deployed shell without asking the user to reload.
function initializeAppUpdates() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  document.getElementById('app-version').textContent = 'v' + version;
  if (!('serviceWorker' in navigator)) return;
  let reloading = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    navigator.serviceWorker.controller?.postMessage({ type: 'GET_SHELL_VERSION' });
  });
  navigator.serviceWorker.addEventListener('message', event => {
    if (event.data?.type !== 'SHELL_VERSION' || event.data.version === version) return;
    if (reloading) return;
    reloading = true;
    window.location.reload();
  });
  navigator.serviceWorker.controller?.postMessage({ type: 'GET_SHELL_VERSION' });
  const register = async () => {
    try { await navigator.serviceWorker.register('/service-worker.js'); }
    catch (error) { console.warn('Service Worker 註冊失敗:', error); }
  };
  if (document.readyState === 'complete') register();
  else window.addEventListener('load', register, { once: true });
}
