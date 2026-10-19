// Startup loading screen and stylesheet readiness watchdog.
window.clearInterval(window.__appBootLegacyPoll);
let appBootHideTimer = null;
let appBootWaitingForStyles = false;

function onAppStylesReady() {
  appBootWaitingForStyles = false;
  hideAppBoot();
}

function armAppBootWatchdog() {
  window.clearTimeout(window.__appBootWatchdog);
  window.__appBootWatchdog = window.setTimeout(() => {
    showAppBootError('載入時間比預期久，請檢查網路後重試。');
  }, 12000);
}

function showAppBoot(message = '正在準備應用程式…') {
  const boot = document.getElementById('app-boot');
  window.removeEventListener('appstylesready', onAppStylesReady);
  appBootWaitingForStyles = false;
  window.clearTimeout(appBootHideTimer);
  boot.hidden = false;
  boot.classList.remove('is-hidden');
  boot.setAttribute('aria-busy', 'true');
  document.getElementById('app-boot-message').textContent = message;
  document.getElementById('app-boot-retry').hidden = true;
  armAppBootWatchdog();
}

function hideAppBoot() {
  const boot = document.getElementById('app-boot');
  const styles = document.getElementById('app-styles');
  if (styles?.dataset.ready !== 'true') {
    if (!appBootWaitingForStyles) {
      appBootWaitingForStyles = true;
      window.addEventListener('appstylesready', onAppStylesReady, { once: true });
    }
    return;
  }
  window.clearTimeout(window.__appBootWatchdog);
  window.clearTimeout(appBootHideTimer);
  boot.setAttribute('aria-busy', 'false');
  boot.classList.add('is-hidden');
  appBootHideTimer = window.setTimeout(() => { boot.hidden = true; }, 180);
}

function showAppBootError(message = '應用程式載入失敗，請重新載入。') {
  const boot = document.getElementById('app-boot');
  window.removeEventListener('appstylesready', onAppStylesReady);
  appBootWaitingForStyles = false;
  window.clearTimeout(window.__appBootWatchdog);
  window.clearTimeout(appBootHideTimer);
  boot.hidden = false;
  boot.classList.remove('is-hidden');
  boot.setAttribute('aria-busy', 'false');
  document.getElementById('app-boot-message').textContent = message;
  document.getElementById('app-boot-retry').hidden = false;
}
