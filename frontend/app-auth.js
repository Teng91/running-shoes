// Authentication state, forms, and account transitions.
let authToken = readStoredValue('token');
let currentUser = readStoredValue('username');
let authGeneration = 0;
let authOperation = null;

function setAuthControlsDisabled(disabled) {
  document.querySelectorAll('#auth-view button[type="submit"]').forEach(button => { button.disabled = disabled; });
}

function cancelAuthOperation() {
  const previous = authOperation;
  authOperation = null;
  previous?.controller.abort();
  setAuthControlsDisabled(false);
}

function beginAuthOperation() {
  if (authOperation) return null;
  const operation = { controller: new AbortController(), generation: authGeneration };
  authOperation = operation;
  setAuthControlsDisabled(true);
  return operation;
}

function isCurrentAuthOperation(operation) {
  return authOperation === operation && operation.generation === authGeneration && !operation.controller.signal.aborted;
}

function finishAuthOperation(operation) {
  if (authOperation !== operation) return;
  authOperation = null;
  setAuthControlsDisabled(false);
}

function captureAuthSession() {
  return { generation: authGeneration, token: authToken };
}

function isCurrentAuthSession(session) {
  return session.generation === authGeneration && session.token === authToken;
}

function requireAuthSession(session) {
  if (!isCurrentAuthSession(session)) throw new DOMException('登入工作階段已變更', 'AbortError');
}
// SPEC-075: 'invite', 'open' or 'closed'; null until the server answers.
let registrationMode = null;
const AUTH_INPUT_IDS = [
  'login-username', 'login-password',
  'reg-username', 'reg-password', 'reg-password2', 'reg-invite',
  'reset-identifier', 'reset-code', 'reset-new-password', 'reset-new-password2',
  'account-old-password', 'account-new-password', 'account-new-password2',
];

function resetAuthInputs() {
  AUTH_INPUT_IDS.forEach(id => {
    const input = document.getElementById(id);
    if (input) input.value = '';
  });
}

function setAuth(token, username) {
  clearAuth();
  authToken = token;
  currentUser = username;
  writeStoredValue('token', token);
  writeStoredValue('username', username);
}

function clearAuth({ persist = true } = {}) {
  cancelAuthOperation();
  if (typeof persistWorkspaceDrafts === 'function') persistWorkspaceDrafts();
  authGeneration += 1;
  resetFeatureLifecycles();
  authToken = null;
  currentUser = null;
  if (persist) {
    removeStoredValue('token');
    removeStoredValue('username');
  }
  resetAuthInputs();
}

function initializeAuthSync() {
  const invalidate = () => {
    clearAuth({ persist: false });
    showLoginView();
    showAuthError('其他分頁已變更登入狀態，請重新登入。');
  };
  window.addEventListener('storage', event => {
    if (isLocalStorageEvent(event) && [null, 'token', 'username'].includes(event.key)) invalidate();
  });
  if (readStoredValue('token') !== authToken || readStoredValue('username') !== currentUser) invalidate();
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
  if (typeof activateLocalWorkspace === 'function') void activateLocalWorkspace();
  if (typeof refreshAdminEntry === 'function') void refreshAdminEntry();
  if (!keepBoot) hideAppBoot();
}

function resetAppLayout() {
  setMobileMenu(false);
  document.getElementById('mobile-page-label').textContent = '跑步日誌';
  document.getElementById('app-workspace').classList.remove('agent-mode');
  document.querySelectorAll('.tab').forEach(tab => {
    const active = tab.dataset.tab === 'runs';
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.panel === 'runs'));
}

function showLoginForm() {
  cancelAuthOperation();
  hideAppBoot();
  document.getElementById('login-form').style.display = '';
  document.getElementById('register-form').style.display = 'none';
  const resetForm = document.getElementById('reset-form');
  if (resetForm) resetForm.style.display = 'none';
  hideAuthError();
}
function showRegisterForm() {
  cancelAuthOperation();
  hideAppBoot();
  document.getElementById('login-form').style.display = 'none';
  document.getElementById('register-form').style.display = '';
  const resetForm = document.getElementById('reset-form');
  if (resetForm) resetForm.style.display = 'none';
  hideRegError();
  if (typeof loadRegistrationMode === 'function') void loadRegistrationMode();
}

function showAuthError(msg) { const el = document.getElementById('auth-error'); el.textContent = msg; el.style.display = 'block'; }
function hideAuthError() { document.getElementById('auth-error').style.display = 'none'; }
function showRegError(msg) { const el = document.getElementById('reg-error'); el.textContent = msg; el.style.display = 'block'; }
function hideRegError() { document.getElementById('reg-error').style.display = 'none'; }

const ERROR_ZH = {
  'User not found': '帳號不存在', 'Incorrect password': '密碼不正確',
  'Username already registered': '帳號已被註冊',
  'Password must be at least 8 characters': '密碼至少 8 個字元',
  'Invalid invite code': '邀請碼無效、已過期或已用完', 'Registration is closed': '目前不開放註冊',
  'Admin only': '只有管理員可以使用', 'Invite not found': '找不到這組邀請碼',
  'Invite code must be 4-20 letters or digits': '自訂邀請碼需為 4～20 個英文字母或數字',
  'Invite code already exists': '這組邀請碼已經存在',
  'Incorrect or expired code': '驗證碼錯誤或已過期', 'Invalid email address': 'Email 格式不正確',
  'Email already in use': '這個 email 已經被其他帳號使用', 'Email is not configured': '目前沒有開啟 email 功能',
  'Shoe not found': '跑鞋不存在',
  // SPEC-085: admin rights follow the name, so an admin account stays until it leaves ADMIN_USERNAMES.
  'Admin accounts cannot be deleted': '管理員帳號不能刪除；要刪除請先把這個帳號從 ADMIN_USERNAMES 移除',
};
function translateError(detail) { return ERROR_ZH[detail] || detail; }

async function handleLogin() {
  if (authOperation) return;
  hideAuthError();
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  if (!username || !password) { showAuthError('請輸入帳號和密碼'); return; }
  const operation = beginAuthOperation();
  let authenticatedSession = null;
  showAppBoot('正在登入並載入資料…');
  try {
    const res = await authRequest(API_BASE + '/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      signal: operation.controller.signal,
    });
    if (!isCurrentAuthOperation(operation)) return;
    if (!res.ok) {
      let msg = '登入失敗';
      try { const err = await res.json(); msg = translateError(err.detail) || msg; } catch {}
      if (!isCurrentAuthOperation(operation)) return;
      if (res.status === 500) msg = '伺服器錯誤，請稍後再試';
      throw new Error(msg);
    }
    const data = await res.json();
    if (!isCurrentAuthOperation(operation)) return;
    setAuth(data.access_token, username);
    authenticatedSession = captureAuthSession();
    resetAuthInputs();
    resetAgentChat();
    resetAppLayout();
    showAppView({ keepBoot: true });
    loadAgentModels();
    await loadData();
    if (!isCurrentAuthSession(authenticatedSession)) return;
    hideAppBoot();
  } catch (e) {
    if (e.name === 'AbortError' || (authenticatedSession
      ? !isCurrentAuthSession(authenticatedSession) : !isCurrentAuthOperation(operation))) return;
    document.getElementById('login-password').value = '';
    hideAppBoot();
    showAuthError(e.message);
  } finally { finishAuthOperation(operation); }
}

async function handleRegister() {
  if (authOperation) return;
  hideRegError();
  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value;
  const password2 = document.getElementById('reg-password2').value;
  const inviteCode = document.getElementById('reg-invite')?.value.trim() || '';
  if (!username || !password) { showRegError('請輸入帳號和密碼'); return; }
  if (registrationMode === 'invite' && !inviteCode) { showRegError('請輸入邀請碼'); return; }
  if (password.length < 8) { showRegError('密碼至少 8 個字元'); return; }
  if (password !== password2) { showRegError('兩次密碼不一致'); return; }
  const operation = beginAuthOperation();
  let authenticatedSession = null;
  showAppBoot('正在建立帳號並載入資料…');
  try {
    const regRes = await authRequest(API_BASE + '/auth/register', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, invite_code: inviteCode }),
      signal: operation.controller.signal,
    });
    if (!isCurrentAuthOperation(operation)) return;
    if (!regRes.ok) {
      let msg = '註冊失敗';
      try { const err = await regRes.json(); msg = translateError(err.detail) || msg; } catch {}
      if (!isCurrentAuthOperation(operation)) return;
      if (regRes.status === 500) msg = '伺服器錯誤，請稍後再試';
      throw new Error(msg);
    }
    const loginRes = await authRequest(API_BASE + '/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      signal: operation.controller.signal,
    });
    if (!isCurrentAuthOperation(operation)) return;
    if (!loginRes.ok) {
      hideAppBoot(); showLoginForm(); showAuthError('註冊成功！請登入'); return;
    }
    const data = await loginRes.json();
    if (!isCurrentAuthOperation(operation)) return;
    setAuth(data.access_token, username);
    authenticatedSession = captureAuthSession();
    resetAuthInputs();
    resetAppLayout();
    showAppView({ keepBoot: true });
    loadAgentModels();
    await loadData();
    if (!isCurrentAuthSession(authenticatedSession)) return;
    hideAppBoot();
  } catch (e) {
    if (e.name === 'AbortError' || (authenticatedSession
      ? !isCurrentAuthSession(authenticatedSession) : !isCurrentAuthOperation(operation))) return;
    hideAppBoot();
    showRegError(e.message);
  } finally { finishAuthOperation(operation); }
}

function handleLogout() { clearAuth(); showLoginView(); }

