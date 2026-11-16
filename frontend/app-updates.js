// Installed-PWA updates (SPEC-049, SPEC-059): look for new deployments while the app stays open
// and switch to the new version by itself at a moment the user cannot lose anything: while the
// app is in the background, before any input since it came back to the foreground, or after five
// idle minutes. Work in progress (an AI answer, a report, an open dialog, a pending request or
// unsent text) postpones it; until then the prompt lets the user update right away.
const APP_UPDATE_ATTEMPT_KEY = 'app-update-attempt';

function initializeAppUpdates() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  document.getElementById('app-version').textContent = 'v' + version;
  if (!('serviceWorker' in navigator)) return;
  const CHECK_EVERY_MS = 30 * 60 * 1000;
  // Focus, visibility and reconnect often fire together; one worker check covers them all.
  const MIN_CHECK_GAP_MS = 60 * 1000;
  const IDLE_BEFORE_UPDATE_MS = 5 * 60 * 1000;
  const RETRY_UPDATE_MS = 60 * 1000;
  // Reaching the new version ends a previous automatic attempt.
  if (readAppUpdateAttempt() === version) writeAppUpdateAttempt(null);
  let pendingVersion = null, retryTimer = null;
  let lastInputAt = -Infinity, visibleSince = Date.now();
  const markInput = () => { lastInputAt = Date.now(); };
  document.addEventListener('pointerdown', markInput, true);
  document.addEventListener('keydown', markInput, true);
  const tryApplyUpdate = () => {
    if (!pendingVersion) return;
    clearTimeout(retryTimer);
    retryTimer = null;
    const unattended = document.visibilityState === 'hidden'
      || lastInputAt < visibleSince || Date.now() - lastInputAt >= IDLE_BEFORE_UPDATE_MS;
    // A reload that still opened the old shell must not loop; the prompt remains.
    if (readAppUpdateAttempt() === pendingVersion) return;
    if (unattended && !appUpdateBusy()) {
      writeAppUpdateAttempt(pendingVersion);
      applyAppUpdate();
      return;
    }
    retryTimer = setTimeout(tryApplyUpdate, RETRY_UPDATE_MS);
  };
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    // A first install merely takes control; only an actually different shell is an update.
    navigator.serviceWorker.controller?.postMessage({ type: 'GET_SHELL_VERSION' });
  });
  navigator.serviceWorker.addEventListener('message', event => {
    if (event.data?.type !== 'SHELL_VERSION' || event.data.version === version) return;
    pendingVersion = event.data.version;
    showAppUpdate(pendingVersion);
    tryApplyUpdate();
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
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'hidden') visibleSince = Date.now();
    tryApplyUpdate();
    checkForUpdate();
  });
  window.addEventListener('focus', checkForUpdate);
  window.addEventListener('online', checkForUpdate);
  // A document restored from the back/forward cache may predate the active worker.
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    visibleSince = Date.now();
    navigator.serviceWorker.controller?.postMessage({ type: 'GET_SHELL_VERSION' });
  });
  setInterval(checkForUpdate, CHECK_EVERY_MS);
}

// SPEC-059: never reload over work that the reload would interrupt or lose. Form drafts and
// completed AI turns survive a reload; a streaming answer, an open dialog or typed text do not.
function appUpdateBusy() {
  if (typeof agentController !== 'undefined' && agentController) return true;
  if (typeof reportGenerationController !== 'undefined' && reportGenerationController) return true;
  if (typeof activeHttpRequests !== 'undefined' && activeHttpRequests.size) return true;
  if (typeof inlineEditors !== 'undefined' && inlineEditors.size) return true;
  if (document.querySelector('.modal-overlay.active')) return true;
  if (document.getElementById('agent-input')?.value.trim()) return true;
  const auth = document.getElementById('auth-view');
  return Boolean(auth && auth.style.display !== 'none'
    && [...auth.querySelectorAll('input')].some(input => input.value));
}

function readAppUpdateAttempt() {
  try { return sessionStorage.getItem(APP_UPDATE_ATTEMPT_KEY); } catch { return null; }
}

function writeAppUpdateAttempt(value) {
  try {
    if (value) sessionStorage.setItem(APP_UPDATE_ATTEMPT_KEY, value);
    else sessionStorage.removeItem(APP_UPDATE_ATTEMPT_KEY);
  } catch {}
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
