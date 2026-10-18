// Shared browser state, authentication, API helpers, and data loading.
// ====== HTML Escape (XSS protection) ======
// String-based replacement — faster than creating DOM nodes each call
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ====== API Base ======
const API_BASE = window.location.origin + '/api';

// The HTML includes a tiny legacy-bundle poll for PWA cache upgrades. The
// current bundle owns the loading screen from this point onward.
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

// ====== Auth State ======
let authToken = localStorage.getItem('token');
let currentUser = localStorage.getItem('username');

const AUTH_INPUT_IDS = [
  'login-username', 'login-password',
  'reg-username', 'reg-password', 'reg-password2',
  'change-username', 'change-old-password', 'change-new-password', 'change-new-password2',
];

function resetAuthInputs() {
  AUTH_INPUT_IDS.forEach(id => {
    const input = document.getElementById(id);
    if (input) input.value = '';
  });
}

function setAuth(token, username) {
  authToken = token;
  currentUser = username;
  localStorage.setItem('token', token);
  localStorage.setItem('username', username);
}

function clearAuth() {
  shoes = []; retiredShoes = []; monthlyMileages = [];
  monthlySpending = []; runs = []; stravaImports = [];
  yearlyRunsCache.clear();
  runListRequestId += 1;
  stackedRunsRequestId += 1;
  runningGoal = { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 };
  dataLoadGeneration += 1;
  reportLoadRequestId += 1;
  reportLoadController?.abort();
  reportLoadController = null;
  reportGenerationRequestId += 1;
  reportGenerationController?.abort();
  reportGenerationController = null;
  setReportControlsDisabled(false);
  const reportButton = document.getElementById('generate-report-btn');
  if (reportButton) {
    reportButton.disabled = false;
    reportButton.textContent = '產生報告';
  }
  authToken = null;
  currentUser = null;
  localStorage.removeItem('token');
  localStorage.removeItem('username');
  resetAuthInputs();
}

function authHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (authToken) h['Authorization'] = 'Bearer ' + authToken;
  return h;
}

function showLoginView() {
  document.getElementById('auth-view').style.display = '';
  document.getElementById('app-view').style.display = 'none';
  showLoginForm();
  hideAppBoot();
}

function showAppView({ keepBoot = false } = {}) {
  document.getElementById('auth-view').style.display = 'none';
  document.getElementById('app-view').style.display = '';
  document.getElementById('user-label').textContent = currentUser || '';
  render();
  if (!keepBoot) hideAppBoot();
}

// 只在「從登入頁進入」時呼叫：清掉上一位使用者切到 AI 助手時留下的 inline 樣式，
// 並把分頁拉回跑步日誌。F5 (init 用 stored token) 不會走這條路，所以不會被強制跳頁。
function resetAppLayout() {
  const appView = document.getElementById('app-view');
  appView.style.height = '';
  appView.style.overflow = '';
  appView.style.flexDirection = '';
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'runs'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.panel === 'runs'));
}

// ====== Brand Colors ======
const BRAND_COLORS = {
  'Mizuno':        ['#38BDF8', '#7DD3FC', '#0EA5E9'],
  'New Balance':   ['#F87171', '#FCA5A5', '#EF4444'],
  'Adidas':        ['#FACC15', '#FDE047', '#EAB308'],
  'PUMA':          ['#4ADE80', '#86EFAC', '#22C55E'],
  'Nike':          ['#FB923C', '#FDBA74', '#F97316'],
  'Asics':         ['#A78BFA', '#C4B5FD', '#8B5CF6'],
  'Saucony':       ['#F472B6', '#F9A8D4', '#EC4899'],
  'Hoka':          ['#2DD4BF', '#5EEAD4', '#14B8A6'],
  'FILA':          ['#FB7185', '#FDA4AF', '#F43F5E'],
  'On':            ['#C084FC', '#D8B4FE', '#A855F7'],
  'Brooks':        ['#34D399', '#6EE7B7', '#10B981'],
  'Skechers':      ['#FBBF24', '#FDE68A', '#F59E0B'],
  'Under Armour':  ['#94A3B8', '#CBD5E1', '#64748B'],
  'Salomon':       ['#F97316', '#FDBA74', '#EA580C'],
};

const byDate = (a, b) => new Date(a.date) - new Date(b.date);

// ====== API Calls (with auth) ======
async function apiGet(url) {
  const res = await fetch(API_BASE + url, { headers: authHeaders() });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) throw new Error('GET ' + url + ' failed: ' + res.status);
  return res.json();
}

async function apiPost(url, body) {
  const res = await fetch(API_BASE + url, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || ('POST ' + url + ' failed: ' + res.status));
  }
  return res.json();
}

async function apiPut(url, body) {
  const res = await fetch(API_BASE + url, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify(body),
  });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : '儲存失敗：' + res.status);
  }
  return res.json();
}

async function apiDelete(url) {
  const res = await fetch(API_BASE + url, { method: 'DELETE', headers: authHeaders() });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || ('DELETE ' + url + ' failed: ' + res.status));
  }
  return res.json();
}

async function apiUpload(url, file, fields = {}, signal = undefined) {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  const headers = {};
  if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
  const res = await fetch(API_BASE + url, { method: 'POST', headers, body: form, signal });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = Array.isArray(err.detail)
      ? err.detail.map(item => item.msg || JSON.stringify(item)).join('；')
      : (typeof err.detail === 'string' ? err.detail : '');
    throw new Error(detail || ('POST ' + url + ' failed: ' + res.status));
  }
  return res.json();
}

// ====== Auth Handlers ======
function showLoginForm() {
  document.getElementById('login-form').style.display = '';
  document.getElementById('register-form').style.display = 'none';
  document.getElementById('change-form').style.display = 'none';
  hideAuthError();
}

function showRegisterForm() {
  document.getElementById('login-form').style.display = 'none';
  document.getElementById('register-form').style.display = '';
  document.getElementById('change-form').style.display = 'none';
  hideRegError();
}

function showChangeForm() {
  document.getElementById('login-form').style.display = 'none';
  document.getElementById('register-form').style.display = 'none';
  document.getElementById('change-form').style.display = '';
  hideChangeError();
}

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  el.textContent = msg;
  el.style.display = 'block';
}

function hideAuthError() {
  document.getElementById('auth-error').style.display = 'none';
}

function showRegError(msg) {
  const el = document.getElementById('reg-error');
  el.textContent = msg;
  el.style.display = 'block';
}

function hideRegError() {
  document.getElementById('reg-error').style.display = 'none';
}

function showChangeError(msg) {
  const el = document.getElementById('change-error');
  el.textContent = msg;
  el.style.display = 'block';
}

function hideChangeError() {
  document.getElementById('change-error').style.display = 'none';
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.panel === name));
  localStorage.setItem('activeTab', name);  // 記住當前 tab，F5 後可還原
  if (name === 'monthly') {
    // Re-render charts after the panel becomes visible — Chart.js needs
    // real dimensions to size correctly (initial render runs while the
    // panel is display:none, leaving canvases at 0x0).
    requestAnimationFrame(() => renderMonthlyCharts());
  }
  if (name === 'spending') {
    requestAnimationFrame(() => renderSpendingCharts());
  }
  if (name === 'runs') {
    requestAnimationFrame(() => renderRunLog());
  }
  if (name === 'report' && authToken) {
    // Layout 回歸測試在無後端的假 origin 執行（authToken 為 null），
    // 必須先確認已登入才發出 API 請求。
    loadReportHistory();
    loadSavedReport();
  }
  // Agent tab: fill viewport height; other tabs: natural scroll
  const appView = document.getElementById('app-view');
  if (name === 'agent') {
    appView.style.height = 'max(100dvh, 680px)';
    appView.style.overflow = 'hidden';
    appView.style.display = 'flex';
    appView.style.flexDirection = 'column';
  } else {
    appView.style.height = '';
    appView.style.overflow = '';
    appView.style.display = '';
    appView.style.flexDirection = '';
  }
}

const ERROR_ZH = {
  'User not found': '帳號不存在',
  'Incorrect password': '密碼不正確',
  'Username already registered': '帳號已被註冊',
  'Password must be at least 4 characters': '密碼至少 4 個字元',
  'Shoe not found': '跑鞋不存在',
};
function translateError(detail) {
  return ERROR_ZH[detail] || detail;
}

async function handleLogin() {
  hideAuthError();
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  if (!username || !password) { showAuthError('請輸入帳號和密碼'); return; }
  showAppBoot('正在登入並載入資料…');
  try {
    const res = await fetch(API_BASE + '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      let msg = '登入失敗';
      try { const err = await res.json(); msg = translateError(err.detail) || msg; } catch {}
      if (res.status === 500) msg = '伺服器錯誤，請稍後再試';
      throw new Error(msg);
    }
    const data = await res.json();
    setAuth(data.access_token, username);
    resetAuthInputs();
    resetAgentChat();  // 保險：確保進入時對話是乾淨的，不殘留上一位使用者
    resetAppLayout();  // 清掉上一位使用者切到 AI 助手留下的 inline 樣式，並回到跑步日誌
    showAppView({ keepBoot: true });
    loadAgentModels();
    await loadData();
    hideAppBoot();
  } catch (e) {
    document.getElementById('login-password').value = '';
    hideAppBoot();
    showAuthError(e.message);
  }
}

async function handleRegister() {
  hideRegError();
  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value;
  const password2 = document.getElementById('reg-password2').value;
  if (!username || !password) { showRegError('請輸入帳號和密碼'); return; }
  if (password.length < 4) { showRegError('密碼至少 4 個字元'); return; }
  if (password !== password2) { showRegError('兩次密碼不一致'); return; }
  showAppBoot('正在建立帳號並載入資料…');
  try {
    const regRes = await fetch(API_BASE + '/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!regRes.ok) {
      let msg = '註冊失敗';
      try { const err = await regRes.json(); msg = translateError(err.detail) || msg; } catch {}
      if (regRes.status === 500) msg = '伺服器錯誤，請稍後再試';
      throw new Error(msg);
    }
    // Auto-login after registration
    const loginRes = await fetch(API_BASE + '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!loginRes.ok) {
      hideAppBoot();
      showLoginForm();
      showAuthError('註冊成功！請登入');
      return;
    }
    const data = await loginRes.json();
    setAuth(data.access_token, username);
    resetAuthInputs();
    resetAppLayout();  // 清掉殘留 inline 樣式並回到跑步日誌
    showAppView({ keepBoot: true });
    loadAgentModels();
    await loadData();
    hideAppBoot();
  } catch (e) {
    hideAppBoot();
    showRegError(e.message);
  }
}

function handleLogout() {
  clearAuth();
  resetAgentChat();
  showLoginView();
}

async function handleChangePassword() {
  hideChangeError();
  const username = document.getElementById('change-username').value.trim();
  const oldPassword = document.getElementById('change-old-password').value;
  const password = document.getElementById('change-new-password').value;
  const password2 = document.getElementById('change-new-password2').value;
  if (!username) { showChangeError('請輸入帳號'); return; }
  if (!oldPassword) { showChangeError('請輸入舊密碼'); return; }
  if (!password) { showChangeError('請輸入新密碼'); return; }
  if (password.length < 4) { showChangeError('密碼至少 4 個字元'); return; }
  if (password !== password2) { showChangeError('兩次密碼不一致'); return; }
  try {
    const res = await fetch(API_BASE + '/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, old_password: oldPassword, new_password: password }),
    });
    if (!res.ok) {
      let msg = '重設失敗';
      try { const err = await res.json(); msg = translateError(err.detail) || msg; } catch {}
      throw new Error(msg);
    }
    showLoginForm();
    showAuthError('密碼已重設，請重新登入');
  } catch (e) {
    showChangeError(e.message);
  }
}

// ====== Data State ======
let shoes = [];
let retiredShoes = [];
let monthlyMileages = [];
let monthlySpending = [];
let runs = [];
const yearlyRunsCache = new Map();
let runListRequestId = 0;
let stackedRunsRequestId = 0;
let stravaImports = [];
let runningGoal = { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 };
let stravaPreview = null;
let stravaPreviewKey = '';
let stravaPreviewRequestId = 0;
let stravaPreviewController = null;
let selectedYear = null;
let selectedGoalMonth = null;
let selectedSpendingYear = null;
let dashboardAnalyticsCache = new Map();
let dashboardAnalyticsRequest = 0;
let reportLoadRequestId = 0;
let reportLoadController = null;
let reportGenerationRequestId = 0;
let reportGenerationController = null;
let currentTheme = localStorage.getItem('theme') || 'dark';

function applyTheme(theme) {
  currentTheme = theme;
  localStorage.setItem('theme', theme);
  const btn = document.getElementById('theme-toggle-btn');
  if (theme === 'light') {
    document.body.classList.add('light-theme');
    if (btn) btn.textContent = '🌙 暗色模式';
  } else {
    document.body.classList.remove('light-theme');
    if (btn) btn.textContent = '☀️ 亮色模式';
  }
}

function toggleTheme() {
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
  applyTheme(newTheme);
  // Re-render active tab's charts to update grid/text colors
  const activeTab = document.querySelector('.tab.active')?.dataset?.tab || 'runs';
  if (activeTab === 'shoes') renderCharts();
  else if (activeTab === 'monthly') renderMonthlyCharts();
  else if (activeTab === 'spending') renderSpendingCharts();
  else if (activeTab === 'runs') renderRunLog();
}

// Initialize theme immediately on script load
applyTheme(currentTheme);

let dataLoadGeneration = 0;
async function loadData() {
  const generation = ++dataLoadGeneration;
  const token = authToken;
  const requestedRunMonth = selectedRunMonth();
  const error = document.getElementById('data-load-error');
  try {
    const [runYear, runMonth] = requestedRunMonth.split('-').map(Number);
    const [active, retired, monthly, spending, runData, importHistory, goal] = await Promise.all([
      apiGet('/shoes/active'),
      apiGet('/shoes/retired'),
      apiGet('/monthly-mileage'),
      apiGet('/spending/monthly'),
      fetchRunPages({ year: runYear, month: runMonth }),
      apiGet('/runs/import/strava/history').catch(error => {
        console.warn('載入 Strava 匯入歷史失敗:', error);
        return [];
      }),
      apiGet('/running-goal'),
    ]);
    if (
      generation !== dataLoadGeneration
      || token !== authToken
      || requestedRunMonth !== selectedRunMonth()
    ) return;
    error.hidden = true;
    shoes = active;
    retiredShoes = retired;
    monthlyMileages = monthly;
    monthlySpending = spending;
    runs = runData;
    stravaImports = importHistory;
    runningGoal = goal;
    yearlyRunsCache.clear();
    if (typeof dashboardAnalyticsCache !== 'undefined') dashboardAnalyticsCache.clear();
  } catch (e) {
    console.error('載入資料失敗:', e);
    if (
      generation !== dataLoadGeneration
      || token !== authToken
      || requestedRunMonth !== selectedRunMonth()
    ) return;
    error.hidden = false;
    return;
  }
  // Default selected year to the most recent year present
  if (monthlyMileages.length > 0) {
    const years = [...new Set(monthlyMileages.map(m => m.year))].sort((a, b) => b - a);
    if (!selectedYear || !years.includes(selectedYear)) {
      selectedYear = years[0];
    }
  } else {
    selectedYear = new Date().getFullYear();
  }
  render();
}

// ====== Calculations ======
