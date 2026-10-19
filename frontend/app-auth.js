// Authentication state, forms, and account transitions.
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

function resetAppLayout() {
  const appView = document.getElementById('app-view');
  appView.style.height = '';
  appView.style.overflow = '';
  appView.style.flexDirection = '';
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'runs'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.panel === 'runs'));
}

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

function showAuthError(msg) { const el = document.getElementById('auth-error'); el.textContent = msg; el.style.display = 'block'; }
function hideAuthError() { document.getElementById('auth-error').style.display = 'none'; }
function showRegError(msg) { const el = document.getElementById('reg-error'); el.textContent = msg; el.style.display = 'block'; }
function hideRegError() { document.getElementById('reg-error').style.display = 'none'; }
function showChangeError(msg) { const el = document.getElementById('change-error'); el.textContent = msg; el.style.display = 'block'; }
function hideChangeError() { document.getElementById('change-error').style.display = 'none'; }

const ERROR_ZH = {
  'User not found': '帳號不存在', 'Incorrect password': '密碼不正確',
  'Username already registered': '帳號已被註冊',
  'Password must be at least 4 characters': '密碼至少 4 個字元',
  'Shoe not found': '跑鞋不存在',
};
function translateError(detail) { return ERROR_ZH[detail] || detail; }

async function handleLogin() {
  hideAuthError();
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  if (!username || !password) { showAuthError('請輸入帳號和密碼'); return; }
  showAppBoot('正在登入並載入資料…');
  try {
    const res = await fetch(API_BASE + '/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
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
    resetAgentChat();
    resetAppLayout();
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
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!regRes.ok) {
      let msg = '註冊失敗';
      try { const err = await regRes.json(); msg = translateError(err.detail) || msg; } catch {}
      if (regRes.status === 500) msg = '伺服器錯誤，請稍後再試';
      throw new Error(msg);
    }
    const loginRes = await fetch(API_BASE + '/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!loginRes.ok) {
      hideAppBoot(); showLoginForm(); showAuthError('註冊成功！請登入'); return;
    }
    const data = await loginRes.json();
    setAuth(data.access_token, username);
    resetAuthInputs();
    resetAppLayout();
    showAppView({ keepBoot: true });
    loadAgentModels();
    await loadData();
    hideAppBoot();
  } catch (e) {
    hideAppBoot();
    showRegError(e.message);
  }
}

function handleLogout() { clearAuth(); resetAgentChat(); showLoginView(); }

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
      method: 'POST', headers: { 'Content-Type': 'application/json' },
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
