// Installed-PWA updates (SPEC-049): look for new deployments while the app stays open, then
// let the user choose when to switch. Detection never reloads by itself, so an open form or
// AI conversation is never cut off; the next launch always opens the newest installed shell.
function initializeAppUpdates() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  document.getElementById('app-version').textContent = 'v' + version;
  if (!('serviceWorker' in navigator)) return;
  const CHECK_EVERY_MS = 30 * 60 * 1000;
  // Focus, visibility and reconnect often fire together; one worker check covers them all.
  const MIN_CHECK_GAP_MS = 60 * 1000;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    // A first install merely takes control; only an actually different shell is an update.
    navigator.serviceWorker.controller?.postMessage({ type: 'GET_SHELL_VERSION' });
  });
  navigator.serviceWorker.addEventListener('message', event => {
    if (event.data?.type !== 'SHELL_VERSION' || event.data.version === version) return;
    showAppUpdate(event.data.version);
  });
  navigator.serviceWorker.controller?.postMessage({ type: 'GET_SHELL_VERSION' });
  let registration = null, lastCheck = 0;
  const checkForUpdate = () => {
    if (!registration || document.visibilityState === 'hidden' || navigator.onLine === false) return;
    if (Date.now() - lastCheck < MIN_CHECK_GAP_MS) return;
    lastCheck = Date.now();
    // The worker installs a complete new shell first; offline or a broken deployment keeps
    // the current one, so a failed check needs no handling here.
    registration.update().catch(() => {});
  };
  const register = async () => {
    try {
      registration = await navigator.serviceWorker.register('/service-worker.js');
      lastCheck = Date.now(); // registering already checked for a newer worker
    } catch (error) { console.warn('Service Worker 註冊失敗:', error); }
  };
  if (document.readyState === 'complete') register();
  else window.addEventListener('load', register, { once: true });
  document.addEventListener('visibilitychange', checkForUpdate);
  window.addEventListener('focus', checkForUpdate);
  window.addEventListener('online', checkForUpdate);
  setInterval(checkForUpdate, CHECK_EVERY_MS);
}

function showAppUpdate(nextVersion) {
  document.getElementById('app-update-title').textContent = `有新版本 v${nextVersion}`;
  document.getElementById('app-update-notice').hidden = false;
}

function applyAppUpdate() {
  const button = document.getElementById('app-update-apply');
  if (button.disabled) return;
  button.disabled = true;
  window.location.reload();
}

function dismissAppUpdate() {
  document.getElementById('app-update-notice').hidden = true;
}
