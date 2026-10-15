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

// ====== Auth State ======
let authToken = localStorage.getItem('token');
let currentUser = localStorage.getItem('username');

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
  document.body.style.opacity = '1';
}

function showAppView() {
  document.getElementById('auth-view').style.display = 'none';
  document.getElementById('app-view').style.display = '';
  document.getElementById('user-label').textContent = currentUser || '';
  render();
  document.body.style.opacity = '1';
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
    resetAgentChat();  // 保險：確保進入時對話是乾淨的，不殘留上一位使用者
    resetAppLayout();  // 清掉上一位使用者切到 AI 助手留下的 inline 樣式，並回到跑步日誌
    showAppView();
    loadAgentModels();
    loadData();
  } catch (e) {
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
      showLoginForm();
      showAuthError('註冊成功！請登入');
      return;
    }
    const data = await loginRes.json();
    setAuth(data.access_token, username);
    resetAppLayout();  // 清掉殘留 inline 樣式並回到跑步日誌
    showAppView();
    loadAgentModels();
    loadData();
  } catch (e) {
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
function calc(shoe) {
  const { price, orig_price, mileage, expected_mileage, monthly_km } = shoe;
  const discount = orig_price > 0 ? price / orig_price : 0;
  const costPerKm = mileage > 0 ? price / mileage : null;
  const expectedCost = expected_mileage > 0 ? price / expected_mileage : 0;
  const lifeProgress = expected_mileage > 0 ? mileage / expected_mileage : 0;
  const remainingMileage = Math.max(0, expected_mileage - mileage);
  const remainingMonths = monthly_km > 0 ? remainingMileage / monthly_km : null;
  const today = new Date();
  let retireDate = null;
  if (remainingMonths !== null) {
    const remainDays = remainingMonths * 30;
    retireDate = new Date(today.getTime() + remainDays * 86400000);
  }
  return { discount, costPerKm, expectedCost, lifeProgress, remainingMileage, remainingMonths, retireDate };
}

// ====== Formatting ======
function fmtPct(v) { return (v * 100).toFixed(2) + '%'; }
function fmtMoney(v) { return '$' + Math.round(v).toLocaleString(); }
function fmtDate(d) { if (!d) return '-'; return `${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}`; }
function fmtCostPerKm(v) { return v !== null ? '$' + v.toFixed(2) : '-'; }
function progressColor(pct) {
  if (pct < 0.2) return '#16a34a';
  if (pct < 0.4) return '#4ade80';
  if (pct < 0.6) return '#eab308';
  if (pct < 0.8) return '#f97316';
  return '#ef4444';
}

function brandColor(brand, seq) {
  const palette = BRAND_COLORS[brand];
  if (!palette) return '#6366f1';
  return palette[seq % palette.length] || palette[0];
}

// ====== Render ======
function render() {
  const now = new Date();
  const todayStr = `${now.getFullYear()}/${String(now.getMonth()+1).padStart(2,'0')}/${String(now.getDate()).padStart(2,'0')}`;
  document.getElementById('today-label').textContent = '資料日期：' + todayStr;

  shoes.sort(byDate);
  retiredShoes.sort(byDate);

  renderCards();
  renderAlerts();
  renderCategorySummary();
  renderTable();
  renderRetiredTable();
  renderMonthlyTable();
  populateRunShoeSelects();
  renderRunLog();
  if (typeof Chart !== 'undefined') {
    renderCharts();
    renderMonthlyCharts();
    if (document.querySelector('.tab-panel.active').dataset.panel === 'spending') {
      renderSpendingCharts();
    }
  }
}

function renderCards() {
  const allShoes = [...shoes, ...retiredShoes];
  let totalMileage = 0, totalPrice = 0;
  allShoes.forEach(s => {
    totalMileage += s.mileage;
    totalPrice += s.price;
  });
  const avgCostPerKm = totalMileage > 0 ? totalPrice / totalMileage : 0;
  const alertCount = shoes.filter(s => {
    const c = calc(s);
    return c.lifeProgress >= 0.8;
  }).length;

  const cards = [
    { label: '現役跑鞋', value: shoes.length + '/' + allShoes.length, sub: '雙' },
    { label: '總里程', value: totalMileage.toLocaleString(), sub: 'km' },
    { label: '總花費', value: '$' + totalPrice.toLocaleString(), sub: '花費合計' },
    { label: '平均每km成本', value: '$' + avgCostPerKm.toFixed(2), sub: '總花費 / 總里程' },
    { label: '換鞋提醒', value: alertCount, sub: '雙鞋需留意' },
    { label: '需補鞋類別', value: categoryCounts(SUMMARY_CATEGORIES).filter(c => c.active === 0).length, sub: '類別目前無現役鞋' },
  ];
  document.getElementById('summary-cards').innerHTML = cards.map(c =>
    `<div class="card"><div class="card-label">${c.label}</div><div class="card-value">${c.value}</div><div class="card-sub">${c.sub}</div></div>`
  ).join('');
}

const SHOE_CATEGORIES = ['Daily', 'Speed', 'Tempo', 'Race'];
const SUMMARY_CATEGORIES = SHOE_CATEGORIES;

// Safely get a shoe's categories as an array (handles both old string and new array formats)
function shoeCategories(s) {
  if (Array.isArray(s.categories)) return s.categories;
  if (typeof s.categories === 'string') {
    try { return JSON.parse(s.categories); } catch { return [s.categories]; }
  }
  if (typeof s.category === 'string') return [s.category]; // backward compat
  return [];
}

function categoryCounts(categories = SHOE_CATEGORIES) {
  return categories.map(category => ({
    category,
    active: shoes.filter(s => shoeCategories(s).includes(category)).length,
    retired: retiredShoes.filter(s => shoeCategories(s).includes(category)).length,
  }));
}

function renderCategorySummary() {
  const container = document.getElementById('category-summary');
  container.innerHTML = categoryCounts(SUMMARY_CATEGORIES).map(({ category, active, retired }) => {
    const need = active === 0;
    return `<div class="category-card${need ? ' need' : ''}">
      <strong>${category}</strong><span>現役 ${active} 雙・退役 ${retired} 雙・${need ? '需要補鞋' : '目前不用補'}</span>
    </div>`;
  }).join('');
}

function renderAlerts() {
  const container = document.getElementById('shoe-alerts');
  const alerts = shoes.map(s => ({ shoe: s, calc: calc(s) }))
    .filter(({ calc: c }) => c.lifeProgress >= 0.8)
    .sort((a, b) => b.calc.lifeProgress - a.calc.lifeProgress);

  if (alerts.length === 0) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = alerts.map(({ shoe: s, calc: c }) => {
    const urgent = c.lifeProgress >= 0.9;
    const pct = Math.round(c.lifeProgress * 100);
    const categories = shoeCategories(s);
    const uncovered = categories.filter(category => !shoes.some(other =>
      other.id !== s.id && shoeCategories(other).includes(category)));
    const lifecycleMessage = urgent
      ? `已使用 ${pct}%，可以準備換鞋。`
      : `已使用 ${pct}%，開始注意這雙鞋的使用狀況。`;
    const coverageMessage = categories.length === 0
      ? '尚未設定用途類別，請先分類再評估是否需要補鞋。'
      : uncovered.length > 0
        ? `${esc(uncovered.join('、'))} 沒有其他現役鞋，建議準備補鞋。`
        : '所有用途類別都有其他現役鞋可替代，目前單純注意這雙鞋即可。';
    return `<div class="shoe-alert${urgent ? ' urgent' : ''}">
      <strong>${esc(s.brand)} ${esc(s.model)}</strong>：<span>${lifecycleMessage} ${coverageMessage}</span>
    </div>`;
  }).join('');
}

function renderTable() {
  const tbody = document.getElementById('shoe-table');
  let brandSeq = {};
  tbody.innerHTML = shoes.map((s, i) => {
    const c = calc(s);
    const pc = progressColor(c.lifeProgress);
    brandSeq[s.brand] = (brandSeq[s.brand] || 0);
    const bc = brandColor(s.brand, brandSeq[s.brand]);
    brandSeq[s.brand]++;
    return `<tr>
      <td><span class="brand-dot" style="background:${bc}"></span><span class="brand">${esc(s.brand)}</span></td>
      <td>${esc(s.model)}</td>
      <td>${esc(s.date.replace(/-/g,'/'))}</td>
      <td class="editable" ondblclick="inlineEditRow(shoes, ${i}, 'mileage', this)">${s.mileage}</td>
      <td>${fmtCostPerKm(c.costPerKm)}</td>
      <td class="editable" ondblclick="inlineEditRow(shoes, ${i}, 'expected_mileage', this)">${s.expected_mileage}</td>
      <td>${fmtCostPerKm(c.expectedCost)}</td>
      <td style="color:${pc}">${fmtPct(c.lifeProgress)}</td>
      <td class="editable" ondblclick="inlineEditRow(shoes, ${i}, 'monthly_km', this)">${s.monthly_km}</td>
      <td>${fmtDate(c.retireDate)}</td>
      <td>${esc(shoeCategories(s).join(', ') || '未分類')}</td>
      <td>${esc(s.size)}</td>
      <td>${fmtMoney(s.price)}</td>
      <td>${fmtMoney(s.orig_price)}</td>
      <td>${fmtPct(c.discount)}</td>
      <td>
        <button class="btn btn-sm" onclick="openShoeAnalytics(${s.id})">分析</button>
        <button class="btn btn-sm btn-edit" onclick="openEditModal(${i})">編輯</button>
      </td>
    </tr>`;
  }).join('');
}

function renderRetiredTable() {
  const tbody = document.getElementById('retired-table');
  let brandSeq = {};
  tbody.innerHTML = retiredShoes.map((s, i) => {
    const c = calc(s);
    const pc = progressColor(c.lifeProgress);
    brandSeq[s.brand] = (brandSeq[s.brand] || 0);
    const bc = brandColor(s.brand, brandSeq[s.brand]);
    brandSeq[s.brand]++;
    return `<tr>
      <td><span class="brand-dot" style="background:${bc}"></span><span class="brand">${esc(s.brand)}</span></td>
      <td>${esc(s.model)}</td>
      <td>${esc(s.date.replace(/-/g,'/'))}</td>
      <td class="editable" ondblclick="inlineEditRow(retiredShoes, ${i}, 'mileage', this)">${s.mileage}</td>
      <td>${fmtCostPerKm(c.costPerKm)}</td>
      <td class="editable" ondblclick="inlineEditRow(retiredShoes, ${i}, 'expected_mileage', this)">${s.expected_mileage}</td>
      <td>${fmtCostPerKm(c.expectedCost)}</td>
      <td style="color:${pc}">${fmtPct(c.lifeProgress)}</td>
      <td>${esc(shoeCategories(s).join(', ') || '未分類')}</td>
      <td>${esc(s.size)}</td>
      <td>${fmtMoney(s.price)}</td>
      <td>${fmtMoney(s.orig_price)}</td>
      <td>${fmtPct(c.discount)}</td>
      <td><button class="btn btn-sm" onclick="openShoeAnalytics(${s.id})">分析</button> <button class="btn btn-sm btn-edit" onclick="openRetiredEditModal(${i})">編輯</button></td>
    </tr>`;
  }).join('');
}

// ====== Monthly Mileage Table ======
function renderMonthlyTable() {
  const tbody = document.getElementById('monthly-table');
  if (monthlyMileages.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:24px;">尚無月跑量紀錄，使用上方表單新增</td></tr>';
    return;
  }
  tbody.innerHTML = monthlyMileages.map((m, i) => `
    <tr>
      <td>${m.year}</td>
      <td>${m.month}</td>
      <td>${(m.km - (m.adjustment_km || 0)).toFixed(2)} km</td>
      <td>${(m.adjustment_km || 0).toFixed(2)} km</td>
      <td class="editable" ondblclick="inlineEditMonthly(${i},'km',this)"><strong>${m.km.toFixed(2)}</strong></td>
      <td>
        <button class="btn btn-sm btn-edit" onclick="editMonthlyMileage(${i})">編輯</button>
        <button class="btn btn-sm btn-delete" onclick="deleteMonthlyMileage(${i})">刪除</button>
      </td>
    </tr>
  `).join('');
}

async function inlineEditMonthly(idx, field, el) {
  const entry = { ...monthlyMileages[idx] };
  const current = entry[field];
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'inline-input';
  input.step = '0.01';
  input.min = '0';
  input.value = current;
  let committed = false;
  const commit = async () => {
    if (committed) return;
    committed = true;
    const val = parseFloat(input.value);
    if (!isNaN(val) && val >= 0) {
      try {
        await apiPut('/monthly-mileage/' + entry.id, {
          km: val,
          expected_version: entry.version || 0,
        });
      } catch (e) {
        alert(e.message || '更新失敗');
      }
    }
    await loadData();
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') commit();
    if (e.key === 'Escape') { committed = true; render(); }
  });
  el.innerHTML = '';
  el.appendChild(input);
  input.focus();
}

async function deleteMonthlyMileage(idx) {
  const m = monthlyMileages[idx];
  if (!confirm(`確定要刪除 ${m.year} 年 ${m.month} 月的紀錄？`)) return;
  try {
    await apiDelete('/monthly-mileage/' + m.id + '?expected_version=' + (m.version || 0));
  } catch (e) {
    console.error('刪除失敗:', e);
    alert(e.message || '刪除失敗');
    return;
  }
  await loadData();
}

// ====== Monthly Mileage: inline add form ======
function populateAddSelects() {
  const now = new Date();
  const yearSel = document.getElementById('add-year');
  const monthSel = document.getElementById('add-month');
  yearSel.innerHTML = '';
  const startY = now.getFullYear() - 5;
  const endY = now.getFullYear() + 5; // 往未來延伸 5 年
  for (let y = endY; y >= startY; y--) {
    const opt = document.createElement('option');
    opt.value = y;
    opt.textContent = y;
    if (y === now.getFullYear()) opt.selected = true;
    yearSel.appendChild(opt);
  }
  monthSel.innerHTML = '';
  for (let m = 1; m <= 12; m++) {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m + ' 月';
    if (m === now.getMonth() + 1) opt.selected = true;
    monthSel.appendChild(opt);
  }
}

let monthlySaving = false;
async function addMonthlyMileage() {
  if (monthlySaving) return;
  const year = parseInt(document.getElementById('add-year').value, 10);
  const month = parseInt(document.getElementById('add-month').value, 10);
  const rawKm = parseFloat(document.getElementById('add-km').value);
  const km = Number.isFinite(rawKm) ? rawKm : 0;
  const errEl = document.getElementById('add-error');
  errEl.style.display = 'none';

  const button = document.getElementById('add-monthly-btn');
  try {
    monthlySaving = true;
    button.disabled = true;
    await apiPost('/monthly-mileage', { year, month, km });
  } catch (e) {
    errEl.textContent = translateError(e.message) || '儲存失敗';
    errEl.style.display = '';
    return;
  } finally {
    monthlySaving = false;
    button.disabled = false;
  }
  document.getElementById('add-km').value = '';
  await loadData();
}

// ====== Monthly Mileage: edit modal ======
let editingMonthlyIdx = -1;

function editMonthlyMileage(idx) {
  editingMonthlyIdx = idx;
  const m = monthlyMileages[idx];
  populateMonthlyEditSelects(m.year, m.month);
  document.getElementById('monthly-modal-title').textContent = '編輯月份';
  document.getElementById('m-km').value = m.km;
  document.getElementById('monthly-error').style.display = 'none';
  document.getElementById('monthly-modal').classList.add('active');
}

function populateMonthlyEditSelects(year, month) {
  const now = new Date();
  const yearSel = document.getElementById('m-year');
  const monthSel = document.getElementById('m-month');
  yearSel.innerHTML = '';
  // Range that covers both existing data and future additions
  const years = new Set(monthlyMileages.map(m => m.year));
  years.add(now.getFullYear());
  years.add(now.getFullYear() + 1);
  years.add(now.getFullYear() + 2);
  years.add(now.getFullYear() + 3);
  years.add(now.getFullYear() + 4);
  years.add(now.getFullYear() + 5);
  years.add(now.getFullYear() - 1);
  [...years].sort((a, b) => b - a).forEach(y => {
    const opt = document.createElement('option');
    opt.value = y;
    opt.textContent = y;
    if (y === year) opt.selected = true;
    yearSel.appendChild(opt);
  });
  monthSel.innerHTML = '';
  for (let m = 1; m <= 12; m++) {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m + ' 月';
    if (m === month) opt.selected = true;
    monthSel.appendChild(opt);
  }
}

function closeMonthlyModal() {
  document.getElementById('monthly-modal').classList.remove('active');
  editingMonthlyIdx = -1;
}

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

    const res = await fetch(API_BASE + '/export?' + params.toString(), {
      headers: authHeaders()
    });

    if (res.status === 401) {
      clearAuth();
      showLoginView();
      throw new Error('Unauthorized');
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
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
    const blob = await res.blob();
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
    console.error('匯出失敗:', e);
    document.getElementById('export-error').textContent = '匯出失敗：' + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

async function exportAccountData() {
  const error = document.getElementById('export-error');
  error.textContent = '';
  try {
    const res = await fetch(API_BASE + '/export/account', { headers: authHeaders() });
    if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
    if (!res.ok) throw new Error('完整備份失敗：' + res.status);
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = match ? match[1] : `running_shoes_account_${localDateISO()}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
    closeExportModal();
  } catch (e) {
    error.textContent = e.message || '完整備份失敗';
  }
}

async function saveMonthlyMileage() {
  if (monthlySaving) return;
  const year = parseInt(document.getElementById('m-year').value, 10);
  const month = parseInt(document.getElementById('m-month').value, 10);
  const rawKm = parseFloat(document.getElementById('m-km').value);
  const km = Number.isFinite(rawKm) ? rawKm : 0;
  const errEl = document.getElementById('monthly-error');
  errEl.style.display = 'none';

  const button = document.getElementById('save-monthly-btn');
  try {
    monthlySaving = true;
    button.disabled = true;
    if (editingMonthlyIdx >= 0) {
      const entry = monthlyMileages[editingMonthlyIdx];
      await apiPut('/monthly-mileage/' + entry.id, {
        year, month, km, expected_version: entry.version || 0,
      });
    } else {
      await apiPost('/monthly-mileage', { year, month, km });
    }
  } catch (e) {
    errEl.textContent = translateError(e.message) || '儲存失敗';
    errEl.style.display = 'block';
    return;
  } finally {
    monthlySaving = false;
    button.disabled = false;
  }
  closeMonthlyModal();
  await loadData();
}

// ====== Charts ======
let chartInstances = {};
let shoeAnalyticsRequestId = 0;

// ====== Run Log ======
let editingRunId = null;

function localDateISO(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function allRunShoes() { return [...shoes, ...retiredShoes]; }
function runShoe(shoeId) { return allRunShoes().find(s => s.id === shoeId); }

function populateRunShoeSelects(selectedId = null) {
  const shoeList = allRunShoes();
  const options = shoeList.map(s =>
    `<option value="${s.id}">${esc(s.brand)} ${esc(s.model)}${s.is_retired ? ' · 已退役' : ''}</option>`
  ).join('');
  ['run-shoe', 'edit-run-shoe'].forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;
    const previous = id === 'edit-run-shoe' && selectedId !== null
      ? selectedId
      : parseInt(select.value, 10);
    select.innerHTML = options || '<option value="">請先新增跑鞋</option>';
    if (previous && shoeList.some(s => s.id === previous)) {
      select.value = String(previous);
    } else if (id === 'edit-run-shoe' && selectedId !== null) {
      select.insertAdjacentHTML(
        'afterbegin',
        '<option value="" selected disabled>原鞋款已刪除，請重新選擇</option>',
      );
    }
  });
}

function selectedRunMonth() {
  const value = document.getElementById('run-month').value;
  return /^\d{4}-\d{2}$/.test(value) ? value : localDateISO().slice(0, 7);
}

const RUN_PAGE_SIZE = 200;

async function fetchRunPages({ year, month = null }) {
  const rows = [];
  for (let offset = 0; ; offset += RUN_PAGE_SIZE) {
    const params = new URLSearchParams({
      year: String(year),
      limit: String(RUN_PAGE_SIZE),
      offset: String(offset),
    });
    if (month !== null) params.set('month', String(month));
    const page = await apiGet('/runs?' + params.toString());
    rows.push(...page);
    if (page.length < RUN_PAGE_SIZE) return rows;
  }
}

async function loadRunsForSelectedMonth() {
  const requestId = ++runListRequestId;
  const [year, month] = selectedRunMonth().split('-').map(Number);
  try {
    const loadedRuns = await fetchRunPages({ year, month });
    if (requestId !== runListRequestId) return;
    runs = loadedRuns;
    renderRunLog();
  } catch (error) {
    if (requestId !== runListRequestId) return;
    console.error('載入跑步紀錄失敗:', error);
    document.getElementById('data-load-error').hidden = false;
  }
}

function monthRuns() {
  const month = selectedRunMonth();
  return runs.filter(run => run.date.slice(0, 7) === month);
}

let runSaving = false;
async function addRun() {
  if (runSaving) return;
  const error = document.getElementById('run-error');
  error.textContent = '';
  const date = document.getElementById('run-date').value;
  const km = parseFloat(document.getElementById('run-km').value);
  const shoeId = parseInt(document.getElementById('run-shoe').value, 10);
  if (!date || !Number.isFinite(km) || km <= 0 || !shoeId) {
    error.textContent = '請填寫日期、正確里程與鞋款。';
    return;
  }
  if (date > localDateISO()) {
    error.textContent = '跑步日期不可晚於今天。';
    return;
  }
  try {
    runSaving = true;
    document.getElementById('add-run-btn').disabled = true;
    await apiPost('/runs', {
      date, km, shoe_id: shoeId,
    });
    document.getElementById('run-km').value = '';
    document.getElementById('run-month').value = date.slice(0, 7);
    await loadData();
  } catch (e) {
    error.textContent = e.message || '新增失敗，請稍後再試。';
  } finally {
    runSaving = false;
    document.getElementById('add-run-btn').disabled = false;
  }
}

function openRunModal(runId) {
  const run = runs.find(item => item.id === runId);
  if (!run) return;
  editingRunId = runId;
  document.getElementById('edit-run-date').value = run.date;
  document.getElementById('edit-run-km').value = run.km;
  populateRunShoeSelects(run.shoe_id);
  document.getElementById('edit-run-error').style.display = 'none';
  document.getElementById('run-modal').classList.add('active');
}

function closeRunModal() {
  editingRunId = null;
  document.getElementById('run-modal').classList.remove('active');
}

async function saveRun() {
  if (!editingRunId) return;
  const error = document.getElementById('edit-run-error');
  const editingRun = runs.find(item => item.id === editingRunId);
  if (!editingRun) {
    error.textContent = '找不到這筆跑步紀錄，請重新載入。';
    error.style.display = 'block';
    return;
  }
  const payload = {
    date: document.getElementById('edit-run-date').value,
    km: parseFloat(document.getElementById('edit-run-km').value),
    shoe_id: parseInt(document.getElementById('edit-run-shoe').value, 10),
    expected_version: editingRun.version || 0,
  };
  if (!payload.date || !Number.isFinite(payload.km) || payload.km <= 0 || !payload.shoe_id) {
    error.textContent = '請完整填寫紀錄。';
    error.style.display = 'block';
    return;
  }
  if (payload.date > localDateISO()) {
    error.textContent = '跑步日期不可晚於今天。';
    error.style.display = 'block';
    return;
  }
  try {
    await apiPut('/runs/' + editingRunId, payload);
    closeRunModal();
    document.getElementById('run-month').value = payload.date.slice(0, 7);
    await loadData();
  } catch (e) {
    error.textContent = e.message || '儲存失敗。';
    error.style.display = 'block';
  }
}

async function deleteEditingRun() {
  const run = runs.find(item => item.id === editingRunId);
  if (!run || !confirm(`確定刪除 ${run.date.replace(/-/g, '/')} 的 ${run.km} km 紀錄？`)) return;
  try {
    await apiDelete('/runs/' + editingRunId + '?expected_version=' + (run.version || 0));
    closeRunModal();
    await loadData();
  } catch (e) { alert(e.message || '刪除失敗'); }
}

function openStravaModal() {
  if (stravaPreviewController) stravaPreviewController.abort();
  stravaPreviewRequestId += 1;
  stravaPreview = null;
  stravaPreviewKey = '';
  document.getElementById('strava-file').value = '';
  document.getElementById('strava-summary').innerHTML = '';
  document.getElementById('strava-mapping').innerHTML = '';
  document.getElementById('strava-error').style.display = 'none';
  document.getElementById('strava-import-btn').disabled = true;
  renderStravaImportHistory();
  const rangeKey = `strava-import-range:${currentUser || 'anonymous'}`;
  let savedRange = null;
  try { savedRange = JSON.parse(localStorage.getItem(rangeKey)); } catch {}
  const now = new Date();
  const defaultStart = new Date(now.getFullYear(), now.getMonth() - 13, 1);
  const defaultEnd = new Date(now.getFullYear(), now.getMonth(), 0);
  const formatDate = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const lastEnd = stravaImports[0]?.end_date;
  let nextStart = '';
  const today = formatDate(now);
  if (/^\d{4}-\d{2}-\d{2}$/.test(lastEnd || '')) {
    const next = new Date(`${lastEnd}T00:00:00`);
    next.setDate(next.getDate() + 1);
    nextStart = formatDate(next) <= today ? formatDate(next) : today;
  }
  document.getElementById('strava-start-date').value = nextStart || savedRange?.start || formatDate(defaultStart);
  document.getElementById('strava-end-date').value = nextStart ? today : savedRange?.end || formatDate(defaultEnd);
  document.getElementById('strava-modal').classList.add('active');
}

function renderStravaImportHistory() {
  const target = document.getElementById('strava-history');
  const last = stravaImports[0];
  if (!last) { target.textContent = '目前沒有 Strava 匯入紀錄。'; return; }
  const when = new Date(last.imported_at).toLocaleString('zh-TW');
  const range = last.start_date || last.end_date ? `${last.start_date || '不限'} ～ ${last.end_date || '不限'}` : '未限制日期';
  target.innerHTML = `<strong>上次成功匯入</strong><br>${esc(when)} · ${esc(range)}<br>新增 ${last.imported_count} 筆／${Number(last.imported_km).toFixed(2)} km · 重複 ${last.duplicate_count} 筆 · 未配對 ${last.unmapped_count} 筆 · 格式略過 ${last.invalid_count} 筆`;
}

function closeStravaModal() {
  if (stravaPreviewController) stravaPreviewController.abort();
  stravaPreviewController = null;
  stravaPreviewRequestId += 1;
  stravaPreview = null;
  stravaPreviewKey = '';
  document.getElementById('strava-modal').classList.remove('active');
}

function stravaInputKey(file, startDate, endDate) {
  if (!file) return '';
  return [file.name, file.size, file.lastModified, startDate, endDate].join('|');
}

async function previewStravaFile() {
  const file = document.getElementById('strava-file').files[0];
  const startDate = document.getElementById('strava-start-date').value;
  const endDate = document.getElementById('strava-end-date').value;
  const summary = document.getElementById('strava-summary');
  const error = document.getElementById('strava-error');
  const mapping = document.getElementById('strava-mapping');
  localStorage.setItem(
    `strava-import-range:${currentUser || 'anonymous'}`,
    JSON.stringify({ start: startDate, end: endDate }),
  );
  if (stravaPreviewController) stravaPreviewController.abort();
  stravaPreviewController = null;
  const requestId = ++stravaPreviewRequestId;
  stravaPreview = null;
  stravaPreviewKey = '';
  summary.innerHTML = '';
  mapping.innerHTML = '';
  error.style.display = 'none';
  document.getElementById('strava-import-btn').disabled = true;
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    error.textContent = 'CSV 檔案不可超過 10 MB';
    error.style.display = 'block';
    return;
  }
  summary.textContent = '正在分析 CSV…';
  const inputKey = stravaInputKey(file, startDate, endDate);
  const controller = new AbortController();
  stravaPreviewController = controller;
  try {
    const preview = await apiUpload(
      '/runs/import/strava/preview',
      file,
      { start_date: startDate, end_date: endDate },
      controller.signal,
    );
    if (requestId !== stravaPreviewRequestId) return;
    stravaPreview = preview;
    stravaPreviewKey = inputKey;
    const unknown = stravaPreview.gear_groups.filter(group => !group.suggested_shoe_id).length;
    summary.innerHTML = `找到 <strong>${stravaPreview.run_count}</strong> 筆跑步活動；` +
      `其中 ${stravaPreview.importable_count} 筆（${Number(stravaPreview.importable_km).toFixed(2)} km）可匯入，` +
      `已有 ${stravaPreview.duplicate_count} 筆重複。` +
      (unknown ? `有 ${unknown} 個鞋款需要手動配對或略過。` : '待匯入鞋款已全部自動配對。');
    const shoeOptions = allRunShoes().map(shoe => `<option value="${shoe.id}">${esc(shoe.brand)} ${esc(shoe.model)} · ${esc(shoe.date)}${shoe.is_retired ? ' · 已退役' : ''}</option>`).join('');
    mapping.innerHTML = stravaPreview.gear_groups.map((group, index) => `
      <div class="strava-group"><div><strong>${esc(group.gear || '未指定鞋款')}</strong><small>${group.count} 次 · ${Number(group.km).toFixed(2)} km</small></div>
        <select id="strava-map-${index}"><option value="">不匯入此鞋款</option>${shoeOptions}</select></div>`).join('');
    stravaPreview.gear_groups.forEach((group, index) => {
      if (group.suggested_shoe_id) document.getElementById(`strava-map-${index}`).value = String(group.suggested_shoe_id);
    });
    document.getElementById('strava-import-btn').disabled = stravaPreview.importable_count === 0;
  } catch (e) {
    if (e.name === 'AbortError' || requestId !== stravaPreviewRequestId) return;
    stravaPreview = null;
    stravaPreviewKey = '';
    summary.innerHTML = '';
    error.textContent = e.message || 'CSV 分析失敗';
    error.style.display = 'block';
  } finally {
    if (requestId === stravaPreviewRequestId) stravaPreviewController = null;
  }
}

async function importStrava() {
  if (!stravaPreview) return;
  const file = document.getElementById('strava-file').files[0];
  const mapping = {};
  const startDate = document.getElementById('strava-start-date').value;
  const endDate = document.getElementById('strava-end-date').value;
  const error = document.getElementById('strava-error');
  if (stravaPreviewKey !== stravaInputKey(file, startDate, endDate)) {
    error.textContent = '檔案或日期範圍已變更，請等待最新預覽完成。';
    error.style.display = 'block';
    await previewStravaFile();
    return;
  }
  stravaPreview.gear_groups.forEach((group, index) => {
    const value = document.getElementById(`strava-map-${index}`).value;
    mapping[group.gear] = value ? Number(value) : null;
  });
  const button = document.getElementById('strava-import-btn');
  button.disabled = true;
  try {
    const result = await apiUpload('/runs/import/strava', file, { mapping: JSON.stringify(mapping), start_date: startDate, end_date: endDate });
    closeStravaModal();
    alert(`已匯入 ${result.imported} 筆跑步紀錄${result.skipped_unmapped ? `，略過 ${result.skipped_unmapped} 筆未配對鞋款` : ''}${result.synced_mileage ? `，並同步 ${result.synced_mileage.toFixed(2)} km 至跑鞋與月跑量` : ''}。`);
    await loadData();
  } catch (e) {
    error.textContent = e.message || '匯入失敗';
    error.style.display = 'block';
    button.disabled = false;
  }
}

function renderRunLog() {
  const month = selectedRunMonth();
  const filtered = monthRuns();
  const total = filtered.reduce((sum, run) => sum + run.km, 0);
  const days = new Set(filtered.map(run => run.date)).size;
  const shoeStats = new Map();
  filtered.forEach(run => {
    const current = shoeStats.get(run.shoe_id) || { km: 0, count: 0 };
    shoeStats.set(run.shoe_id, { km: current.km + run.km, count: current.count + 1 });
  });
  const favoriteEntry = [...shoeStats.entries()].sort((a, b) => b[1].km - a[1].km)[0];
  const favorite = favoriteEntry ? runShoe(favoriteEntry[0]) : null;
  const monthLabel = `${parseInt(month.slice(5), 10)} 月`;
  document.getElementById('run-stats').innerHTML = [
    { label: '本月總里程', value: `${total.toFixed(2)} km`, sub: `${filtered.length} 次跑步` },
    { label: '跑步天數', value: `${days} 天`, sub: days ? `平均每天 ${(total / days).toFixed(2)} km` : '還沒有紀錄' },
    { label: '本月主力鞋', value: favorite ? esc(favorite.model) : '—', sub: favoriteEntry ? `${favoriteEntry[1].km.toFixed(2)} km` : '還沒有紀錄' },
  ].map(card => `<div class="card"><div class="card-label">${card.label}</div><div class="card-value">${card.value}</div><div class="card-sub">${card.sub}</div></div>`).join('');
  renderStravaStatus();

  document.getElementById('run-table-title').textContent = `${monthLabel}跑步紀錄`;
  document.getElementById('run-table').innerHTML = filtered.length ? filtered.map(run => {
    const shoe = runShoe(run.shoe_id);
    const color = shoe ? brandColor(shoe.brand, 0) : '#64748b';
    const shoeName = shoe ? `${esc(shoe.brand)} ${esc(shoe.model)}` : '鞋款已刪除';
    const source = run.strava_id ? '<span class="run-source strava">Strava</span>' : '<span class="run-source">手動</span>';
    return `<tr><td>${esc(run.date.replace(/-/g, '/'))}</td><td><strong>${run.km.toFixed(2)} km</strong></td><td><span class="run-shoe-label"><span class="brand-dot" style="background:${color}"></span>${shoeName}</span></td><td>${source}</td><td><button class="btn btn-sm btn-edit" onclick="openRunModal(${run.id})">編輯</button></td></tr>`;
  }).join('') : '<tr><td colspan="5" class="empty-state">這個月還沒有跑步紀錄。點月曆日期或從右上角記下第一跑吧！</td></tr>';

  renderRunCalendar(filtered, month);
  renderRunShoeChart(shoeStats);
  loadDashboardAnalytics(month);
}

async function loadDashboardAnalytics(month) {
  const target = document.getElementById('dashboard-insights');
  if (!target || !authToken) return;
  const cacheKey = `${localDateISO()}|${month}`;
  for (const key of dashboardAnalyticsCache.keys()) {
    if (!key.startsWith(`${localDateISO()}|`)) dashboardAnalyticsCache.delete(key);
  }
  if (dashboardAnalyticsCache.has(cacheKey)) {
    renderDashboardInsights(dashboardAnalyticsCache.get(cacheKey));
    return;
  }
  const requestId = ++dashboardAnalyticsRequest;
  target.innerHTML = '<div class="insight-card"><div class="insight-card-sub">分析載入中…</div></div>';
  try {
    const [year, monthNumber] = month.split('-').map(Number);
    const data = await apiGet(`/analytics/dashboard?year=${year}&month=${monthNumber}`);
    if (requestId !== dashboardAnalyticsRequest || selectedRunMonth() !== month) return;
    dashboardAnalyticsCache.set(cacheKey, data);
    renderDashboardInsights(data);
  } catch (error) {
    if (requestId !== dashboardAnalyticsRequest) return;
    target.innerHTML = `<div class="insight-alert warning">進階分析暫時無法載入：${esc(error.message || '未知錯誤')}</div>`;
  }
}

function renderDashboardInsights(data) {
  const target = document.getElementById('dashboard-insights');
  const goal = data.goal || {};
  const comparison = data.comparison || {};
  const delta = Number(comparison.delta_km ?? data.month_delta_km ?? 0);
  const recent = data.recent_7_days || {};
  const forecast = data.forecast || {};
  const goalSummary = dashboardGoalSummary(goal);
  const forecastSummary = forecast.state === 'current'
    ? ` · 月底預測 ${Number(forecast.projected_month_km || 0).toFixed(2)} km`
    : '';
  const cards = [
    { label: comparison.label || '與上月比較', value: comparison.label === '尚未開始' ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(2)} km`, sub: comparison.label === '尚未開始' ? '所選月份尚未開始' : `上月${comparison.through_day ? `前 ${comparison.through_day} 天` : ''} ${Number(comparison.previous_km ?? data.previous_month?.km ?? 0).toFixed(2)} km` },
    { label: '近 7 天趨勢', value: recent.state === 'future' ? '—' : `${Number(recent.km || 0).toFixed(2)} km`, sub: recent.state === 'future' ? '所選月份尚未開始' : `較前 7 天 ${Number(recent.delta_km || 0) >= 0 ? '+' : ''}${Number(recent.delta_km || 0).toFixed(2)} km` },
    { label: '月目標', value: goal.active ? `${Number(goal.month_achievement_percent || 0).toFixed(1)}%` : '尚未啟用', sub: `${goalSummary}${forecastSummary}` },
  ];
  const alerts = (data.alerts || []).map(alert => `<div class="insight-alert ${esc(alert.severity || '')}">${esc(alert.message)}</div>`).join('');
  target.innerHTML = `
    <div class="insight-grid">${cards.map(card => `<div class="insight-card"><div class="insight-card-label">${card.label}</div><div class="insight-card-value">${card.value}</div><div class="insight-card-sub">${card.sub}</div></div>`).join('')}</div>
    ${alerts ? `<div class="insight-alerts">${alerts}</div>` : ''}`;
}

function dashboardGoalSummary(goal) {
  if (!goal.active) return `從 ${goal.start_year || '—'} 年開始`;
  if (goal.month_state === 'future') return '尚未開始';
  if (goal.month_state === 'past') {
    const remainingKm = Number(goal.month_remaining_km || 0);
    if (remainingKm > 0) return `月底結算，未達目標 ${remainingKm.toFixed(2)} km`;
    const overKm = Math.max(0, Number(goal.month_km || 0) - Number(goal.monthly_km || 0));
    return `已達成目標，超過 ${overKm.toFixed(2)} km`;
  }
  if (goal.month_state === 'before_goal') return `從 ${goal.start_year || '—'} 年開始`;

  const paceDelta = Number(goal.pace_delta_km || 0);
  const parts = [
    `${paceDelta >= 0 ? '超前' : '落後'} ${Math.abs(paceDelta).toFixed(2)} km`,
    `剩 ${Number(goal.remaining_days || 0)} 天`,
  ];
  if (goal.required_daily_km !== null && goal.required_daily_km !== undefined) {
    parts.push(`每天需 ${Number(goal.required_daily_km).toFixed(2)} km`);
  }
  return parts.join(' · ');
}

function renderStravaStatus() {
  const target = document.getElementById('strava-last');
  const last = stravaImports[0];
  if (!last) { target.textContent = '尚未匯入'; return; }
  const when = new Date(last.imported_at).toLocaleString('zh-TW', { month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit' });
  target.textContent = `上次 ${when} · 新增 ${last.imported_count} 筆`;
}

function selectRunCalendarDate(date, event) {
  if (event.target.closest('.calendar-run')) return;
  document.getElementById('run-date').value = date;
  document.getElementById('run-month').value = date.slice(0, 7);
  document.getElementById('run-km').focus();
}

function renderRunCalendar(filtered, month) {
  const target = document.getElementById('run-calendar');
  const [year, monthNumber] = month.split('-').map(Number);
  const daysInMonth = new Date(year, monthNumber, 0).getDate();
  const firstWeekday = (new Date(year, monthNumber - 1, 1).getDay() + 6) % 7;
  const byDay = new Map();
  filtered.forEach(run => {
    const day = Number(run.date.slice(8));
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(run);
  });
  const weekdays = ['一','二','三','四','五','六','日'].map(day => `<div class="calendar-weekday">${day}</div>`);
  const blanks = Array.from({length:firstWeekday}, () => '<div class="calendar-day outside"></div>');
  const today = localDateISO();
  const cells = Array.from({length:daysInMonth}, (_, index) => {
    const day = index + 1;
    const date = `${month}-${String(day).padStart(2,'0')}`;
    const dayRuns = byDay.get(day) || [];
    const total = dayRuns.reduce((sum, run) => sum + run.km, 0);
    const intensity = total ? Math.min(.18 + total / 25, .68) : 0;
    const items = dayRuns.map(run => {
      const shoe = runShoe(run.shoe_id);
      return `<button class="calendar-run" onclick="event.stopPropagation();openRunModal(${run.id})">${esc(shoe?.model || '跑鞋')}</button>`;
    }).join('');
    return `<div class="calendar-day${date === today ? ' today' : ''}" style="background:rgba(34,197,94,${intensity})" onclick="selectRunCalendarDate('${date}',event)"><div class="calendar-number">${day}</div>${total ? `<div class="calendar-total">${total.toFixed(2)} km</div>` : ''}${items}</div>`;
  });
  target.innerHTML = [...weekdays, ...blanks, ...cells].join('');
}

function getThemeColor(varName, fallback) {
  const val = getComputedStyle(document.body).getPropertyValue(varName).trim();
  return val || fallback;
}

function renderRunShoeChart(shoeStats) {
  const entries = [...shoeStats.entries()].sort((a, b) => b[1].km - a[1].km);
  const shoeList = entries.map(([id]) => runShoe(id));
  const colors = shoeList.map((shoe, i) => shoe ? brandColor(shoe.brand, i) : '#64748b');
  const total = entries.reduce((sum, [, stats]) => sum + stats.km, 0);
  const legend = document.getElementById('run-shoe-legend');
  legend.innerHTML = entries.length ? entries.map(([, stats], index) => {
    const shoe = shoeList[index];
    const name = shoe ? `${shoe.brand} ${shoe.model}` : '鞋款已刪除';
    const percentage = total > 0 ? stats.km / total * 100 : 0;
    return `<div class="run-shoe-legend-row"><div class="run-shoe-legend-name"><span class="run-shoe-legend-dot" style="background:${colors[index]}"></span><span>${esc(name)}</span></div><span class="run-shoe-legend-pct">${percentage.toFixed(1)}%</span><span class="run-shoe-legend-km">${stats.km.toFixed(2)} km</span><span class="run-shoe-legend-count">${stats.count} 次</span></div>`;
  }).join('') : '<div class="empty-state">這個月還沒有鞋款里程。</div>';
  if (typeof Chart === 'undefined') return;
  if (chartInstances.runShoes) chartInstances.runShoes.destroy();
  const cardBg = getThemeColor('--card', '#1a1d2e');
  chartInstances.runShoes = new Chart(document.getElementById('chart-run-shoes'), {
    type: 'doughnut',
    data: {
      labels: shoeList.map(shoe => shoe ? `${shoe.brand} ${shoe.model}` : '鞋款已刪除'),
      datasets: [{ data: entries.map(([, stats]) => stats.km), backgroundColor: colors, borderColor: cardBg, borderWidth: 3 }],
    },
    options: { maintainAspectRatio: false, cutout: '60%', plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${total > 0 ? (ctx.raw / total * 100).toFixed(1) : '0.0'}% / ${ctx.raw.toFixed(2)} km / ${entries[ctx.dataIndex][1].count} 次` } } } }
  });
}

async function openShoeAnalytics(shoeId) {
  const modal = document.getElementById('shoe-analysis-modal');
  const content = document.getElementById('shoe-analysis-content');
  const requestId = ++shoeAnalyticsRequestId;
  modal.classList.add('active');
  content.innerHTML = '<div class="empty-state">載入跑鞋分析…</div>';
  try {
    const data = await apiGet(`/shoes/${shoeId}/analytics`);
    if (requestId !== shoeAnalyticsRequestId || !modal.classList.contains('active')) return;
    renderShoeAnalytics(data);
  } catch (error) {
    if (requestId !== shoeAnalyticsRequestId || !modal.classList.contains('active')) return;
    content.innerHTML = `<div class="insight-alert warning">分析載入失敗：${esc(error.message || '未知錯誤')}</div>`;
  }
}

function closeShoeAnalytics() {
  shoeAnalyticsRequestId += 1;
  document.getElementById('shoe-analysis-modal').classList.remove('active');
  if (chartInstances.shoeAnalytics) {
    chartInstances.shoeAnalytics.destroy();
    delete chartInstances.shoeAnalytics;
  }
}

function renderShoeAnalytics(data) {
  const shoe = data.shoe;
  const life = data.lifecycle;
  const usage = data.usage;
  document.getElementById('shoe-analysis-title').textContent = `${shoe.brand} ${shoe.model}`;
  document.getElementById('shoe-analysis-sub').textContent = `${shoe.is_retired ? '已退役' : '使用中'} · ${shoe.categories.join(' / ') || '未分類'} · 購入 ${shoe.purchase_date.replace(/-/g, '/')}`;
  const forecast = life.forecast_retirement_date
    ? life.forecast_retirement_date.replace(/-/g, '/')
    : '無法預估';
  const source = life.forecast_source === 'recent_90_days' ? '依近 90 天實際使用' : '依計畫月跑量';
  const cards = [
    { label: '總里程', value: `${Number(life.total_mileage_km).toFixed(2)} km`, sub: '' },
    { label: '穿著次數', value: `${usage.count} 次`, sub: usage.count ? '已納入逐筆日誌' : '尚無日誌紀錄' },
    { label: '近 30／90 天', value: `${Number(usage.km_30_days).toFixed(1)} / ${Number(usage.km_90_days).toFixed(1)} km`, sub: `實際月均 ${Number(usage.actual_monthly_km_90_days).toFixed(1)} km` },
    { label: '最後使用', value: usage.last_run_date ? usage.last_run_date.replace(/-/g, '/') : '—', sub: usage.first_run_date ? `首次紀錄 ${usage.first_run_date.replace(/-/g, '/')}` : '尚無日誌紀錄' },
    { label: '壽命進度', value: life.usage_percent === null ? '—' : `${Number(life.usage_percent).toFixed(1)}%`, sub: `剩餘 ${Number(life.remaining_mileage_km).toFixed(2)} km` },
    { label: '預估退役', value: forecast, sub: `${source} · ${Number(life.forecast_monthly_km).toFixed(1)} km／月` },
  ];
  const recentRows = data.recent_runs.length ? data.recent_runs.map(run => `
    <tr><td>${run.date.replace(/-/g, '/')}</td><td>${Number(run.km).toFixed(2)} km</td></tr>`).join('')
    : '<tr><td colspan="2" class="empty-state">尚無逐筆跑步紀錄。</td></tr>';
  document.getElementById('shoe-analysis-content').innerHTML = `<div class="shoe-analysis-grid">${cards.map(card => `<div class="insight-card"><div class="insight-card-label">${card.label}</div><div class="insight-card-value">${card.value}</div>${card.sub ? `<div class="insight-card-sub">${card.sub}</div>` : ''}</div>`).join('')}</div>
    <div class="shoe-analysis-section"><h3>近 12 個月使用趨勢</h3><div class="shoe-analysis-chart"><canvas id="chart-shoe-analytics"></canvas></div></div>
    <div class="shoe-analysis-section"><h3>最近跑步</h3><div class="table-wrap" tabindex="0" role="region" aria-label="跑鞋最近跑步"><table><thead><tr><th>日期</th><th>距離</th></tr></thead><tbody>${recentRows}</tbody></table></div></div>`;
  if (typeof Chart === 'undefined') return;
  if (chartInstances.shoeAnalytics) chartInstances.shoeAnalytics.destroy();
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#334155');
  chartInstances.shoeAnalytics = new Chart(document.getElementById('chart-shoe-analytics'), {
    type: 'bar',
    data: {
      labels: data.monthly_history.map(item => `${item.year}/${item.month}`),
      datasets: [{ label: '里程', data: data.monthly_history.map(item => item.km), backgroundColor: '#22c55e', borderRadius: 4 }],
    },
    options: { maintainAspectRatio:false, plugins:{ legend:{display:false}, tooltip:{callbacks:{label:ctx => `${Number(ctx.raw).toFixed(2)} km · ${data.monthly_history[ctx.dataIndex].count} 次`}}}, scales:{x:{grid:{display:false},ticks:{color:textColor}},y:{beginAtZero:true,grid:{color:gridColor},ticks:{color:textColor,callback:value => value + ' km'}}} },
  });
}

// Keep full data labels for tooltips; only shorten the axis presentation.
function fitChartLabel(label, chart, widthFraction) {
  const text = String(label ?? '');
  const maxWidth = Math.min(160, chart.width * widthFraction);
  const ctx = chart.ctx;
  ctx.save();
  ctx.font = '11px "Segoe UI", system-ui, sans-serif';
  let result = text;
  if (ctx.measureText(result).width > maxWidth) {
    const chars = Array.from(text);
    while (chars.length && ctx.measureText(chars.join('') + '…').width > maxWidth) chars.pop();
    result = chars.join('') + '…';
  }
  ctx.restore();
  return result;
}

// Keep the monthly allocation readable without a tall legend below the chart.
const shoeShareLabels = {
  id: 'shoeShareLabels',
  afterDatasetsDraw(chart) {
    const dataset = chart.data.datasets[0];
    const values = dataset.data.map(Number);
    const total = values.reduce((sum, value) => sum + Math.max(0, value || 0), 0);
    if (!total) return;

    const meta = chart.getDatasetMeta(0);
    const { ctx } = chart;
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#fff';
    ctx.strokeStyle = 'rgba(15, 23, 42, .65)';
    ctx.lineWidth = 3;
    ctx.lineJoin = 'round';

    meta.data.forEach((arc, index) => {
      const value = values[index];
      if (!(value > 0) || arc.hidden) return;
      const angle = (arc.startAngle + arc.endAngle) / 2;
      const radius = (arc.innerRadius + arc.outerRadius) / 2;
      const x = arc.x + Math.cos(angle) * radius;
      const y = arc.y + Math.sin(angle) * radius;
      const km = Number.isInteger(value) ? String(value) : value.toFixed(1);
      const percentage = value / total * 100;

      ctx.font = '700 10px "Segoe UI", system-ui, sans-serif';
      ctx.strokeText(`${km} km`, x, y - 6);
      ctx.fillText(`${km} km`, x, y - 6);
      ctx.font = '700 9px "Segoe UI", system-ui, sans-serif';
      ctx.strokeText(`${percentage.toFixed(1)}%`, x, y + 6);
      ctx.fillText(`${percentage.toFixed(1)}%`, x, y + 6);
    });
    ctx.restore();
  }
};

function renderCharts() {
  ['progress', 'cost', 'retire', 'value'].forEach(key => {
    if (chartInstances[key]) {
      chartInstances[key].destroy();
      delete chartInstances[key];
    }
  });

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#2a2d3e');
  const mainTextColor = getThemeColor('--text', '#e4e4e7');

  const labels = shoes.map(s => s.brand + ' ' + s.model);
  let brandSeq = {};
  const colors = shoes.map(s => {
    brandSeq[s.brand] = (brandSeq[s.brand] || 0);
    const c = brandColor(s.brand, brandSeq[s.brand]);
    brandSeq[s.brand]++;
    return c;
  });
  const calcs = shoes.map(s => calc(s));

  chartInstances.progress = new Chart(document.getElementById('chart-progress'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '已跑里程',
        data: shoes.map(s => s.mileage),
        backgroundColor: calcs.map(c => progressColor(c.lifeProgress)),
        borderRadius: 4,
      }, {
        label: '剩餘里程',
        data: calcs.map(c => c.remainingMileage),
        backgroundColor: '#22c55e44',
        borderColor: '#22c55e',
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { labels: { color: textColor, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: ctx => {
              const shoe = shoes[ctx.dataIndex];
              const c = calcs[ctx.dataIndex];
              if (ctx.datasetIndex === 0) {
                return `已跑 ${shoe.mileage} km (${(c.lifeProgress * 100).toFixed(1)}%)`;
              }
              return `剩餘 ${c.remainingMileage} km`;
            }
          }
        }
      },
      scales: {
        x: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' } },
        y: { stacked: true, grid: { display: false }, ticks: { color: textColor, font: { size: 11 }, callback: function(value) { return fitChartLabel(this.getLabelForValue(value), this.chart, 0.3); } } }
      }
    }
  });

  chartInstances.cost = new Chart(document.getElementById('chart-cost'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '每km成本',
        data: calcs.map(c => c.costPerKm ?? 0),
        backgroundColor: colors,
        borderRadius: 4,
      }, {
        label: '預期成本',
        data: calcs.map(c => c.expectedCost),
        backgroundColor: colors.map(c => c + '44'),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: textColor, font: { size: 11 } } }, tooltip: { callbacks: { label: ctx => '$' + ctx.raw.toFixed(2) + '/km' } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxRotation: 0, callback: function(value) { return fitChartLabel(this.getLabelForValue(value), this.chart, 0.18); } } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => '$' + v } }
      }
    }
  });

  const retireData = calcs.map((c, i) => ({
    x: c.retireDate ? c.retireDate.getTime() : null,
    y: i,
    shoeIdx: i,
    label: labels[i]
  })).filter(d => d.x !== null);

  chartInstances.retire = new Chart(document.getElementById('chart-retire'), {
    type: 'scatter',
    data: {
      datasets: [{
        data: retireData.map(d => ({ x: d.x, y: d.y })),
        backgroundColor: retireData.map((d) => colors[d.shoeIdx] || '#6366f1'),
        pointRadius: 10,
        pointHoverRadius: 14,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const d = new Date(ctx.raw.x);
              return retireData[ctx.dataIndex].label + ': ' + fmtDate(d);
            }
          }
        }
      },
      scales: {
        x: {
          type: 'linear',
          grid: { color: gridColor },
          ticks: {
            color: textColor,
            callback: v => {
              const d = new Date(v);
              return d.getFullYear() + '/' + (d.getMonth()+1);
            }
          }
        },
        y: {
          min: -1,
          max: shoes.length,
          reverse: true,
          grid: { display: false },
          ticks: {
            color: textColor,
            callback: function(v) {
              if (Number.isInteger(v) && v >= 0 && v < labels.length) return fitChartLabel(labels[v], this.chart, 0.3);
              return '';
            },
            font: { size: 10 }
          }
        }
      }
    }
  });

  const totalMonthlyKm = shoes.reduce((sum, s) => sum + s.monthly_km, 0);
  chartInstances.value = new Chart(document.getElementById('chart-value'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: shoes.map(s => s.monthly_km),
        backgroundColor: colors,
        borderWidth: 0,
      }]
    },
    options: {
      maintainAspectRatio: false,
      cutout: '60%',
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw + ' km/月' } }
      }
    },
    plugins: [shoeShareLabels, {
      id: 'centerText',
      afterDraw(chart) {
        const { ctx, chartArea: { top, bottom, left, right } } = chart;
        const cx = (left + right) / 2;
        const cy = (top + bottom) / 2;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const h1 = 13, gap = 4, h2 = 24;
        const y0 = cy - (h1 + gap + h2) / 2;
        ctx.fillStyle = textColor;
        ctx.font = '13px "Segoe UI", system-ui, sans-serif';
        ctx.fillText('總月跑量', cx, y0);
        ctx.fillStyle = mainTextColor;
        ctx.font = 'bold 24px "Segoe UI", system-ui, sans-serif';
        ctx.fillText(totalMonthlyKm + ' km', cx, y0 + h1 + gap);
        ctx.restore();
      }
    }]
  });
}

// ====== Monthly Mileage Charts ======
let selectedStackedYear = null;

function renderMonthlyCharts() {
  if (chartInstances.monthlyYear) { chartInstances.monthlyYear.destroy(); delete chartInstances.monthlyYear; }
  if (chartInstances.shoeStacked) { chartInstances.shoeStacked.destroy(); delete chartInstances.shoeStacked; }
  if (chartInstances.yearlyTotal) { chartInstances.yearlyTotal.destroy(); delete chartInstances.yearlyTotal; }
  populateYearSelect();
  renderGoalProgress();
  renderMonthlyYearChart();
  renderShoeStackedChart();
  renderYearlyTotalChart();
}

function populateYearSelect() {
  const sel = document.getElementById('year-select');
  const stackedSel = document.getElementById('stacked-year-select');
  const years = [...new Set([
    ...monthlyMileages.map(m => m.year),
    runningGoal.start_year,
    new Date().getFullYear(),
  ])].sort((a, b) => b - a);
  if (years.length === 0) {
    sel.innerHTML = '<option value="">無資料</option>';
    if (stackedSel) stackedSel.innerHTML = '<option value="">無資料</option>';
    selectedYear = null;
    selectedStackedYear = null;
    return;
  }
  if (!selectedYear || !years.includes(selectedYear)) {
    selectedYear = years[0];
  }
  if (!selectedStackedYear || !years.includes(selectedStackedYear)) {
    selectedStackedYear = years[0];
  }
  sel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedYear ? 'selected' : ''}>${y}</option>`).join('');
  if (stackedSel) {
    stackedSel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedStackedYear ? 'selected' : ''}>${y}</option>`).join('');
  }
}

function onYearChange() {
  const sel = document.getElementById('year-select');
  selectedYear = parseInt(sel.value, 10) || null;
  selectedGoalMonth = null;
  renderGoalProgress();
  renderMonthlyYearChart();
}

function renderGoalProgress() {
  const cards = document.getElementById('goal-cards');
  if (!cards) return;
  document.getElementById('goal-start-year').value = runningGoal.start_year;
  document.getElementById('goal-monthly-km').value = runningGoal.monthly_km;
  const year = selectedYear || new Date().getFullYear();
  const now = new Date();
  const rows = monthlyMileages.filter(item => item.year === year);
  const latestRecordedMonth = rows.length
    ? Math.max(...rows.map(item => item.month))
    : null;
  if (!selectedGoalMonth) {
    selectedGoalMonth = year === now.getFullYear()
      ? now.getMonth() + 1
      : (latestRecordedMonth || 12);
  }
  const monthSelect = document.getElementById('goal-month-select');
  monthSelect.innerHTML = Array.from({length: 12}, (_, index) => {
    const month = index + 1;
    return `<option value="${month}" ${month === selectedGoalMonth ? 'selected' : ''}>${month} 月</option>`;
  }).join('');
  if (year < runningGoal.start_year) {
    cards.innerHTML = `<div class="card"><div class="card-label">${year} 年目標</div><div class="card-value">尚未開始</div><div class="card-sub">目標自 ${runningGoal.start_year} 年起生效</div></div>`;
    return;
  }
  const selectedRow = rows.find(item => item.month === selectedGoalMonth);
  const monthKm = selectedRow ? selectedRow.km : 0;
  const monthPct = monthKm / runningGoal.monthly_km * 100;
  const yearKm = rows.filter(item => item.month <= selectedGoalMonth).reduce((sum, item) => sum + item.km, 0);
  const yearPct = yearKm / runningGoal.yearly_km * 100;
  const daysInMonth = new Date(year, selectedGoalMonth, 0).getDate();
  const selectedKey = year * 100 + selectedGoalMonth;
  const currentKey = now.getFullYear() * 100 + now.getMonth() + 1;
  let paceText;
  if (selectedKey < currentKey) {
    paceText = monthKm >= runningGoal.monthly_km
      ? `已達成目標，超過 ${(monthKm - runningGoal.monthly_km).toFixed(2)} km`
      : `月底結算，未達目標 ${(runningGoal.monthly_km - monthKm).toFixed(2)} km`;
  } else if (selectedKey > currentKey) {
    paceText = '尚未開始';
  } else {
    const elapsedDays = now.getDate();
    const remainingDays = daysInMonth - elapsedDays;
    const expectedKm = runningGoal.monthly_km * elapsedDays / daysInMonth;
    const paceDelta = monthKm - expectedKm;
    const remainingKm = Math.max(0, runningGoal.monthly_km - monthKm);
    const dailyNeeded = remainingDays > 0 ? remainingKm / remainingDays : null;
    paceText = `${paceDelta >= 0 ? '超前' : '落後'} ${Math.abs(paceDelta).toFixed(2)} km · 剩 ${remainingDays} 天` +
      (dailyNeeded === null ? '' : ` · 每天需 ${dailyNeeded.toFixed(2)} km`);
  }
  cards.innerHTML = `
    <div class="card">
      <div class="card-label">${year} 年 ${selectedGoalMonth} 月目標</div>
      <div class="card-value">${monthKm.toFixed(2)} / ${Number(runningGoal.monthly_km).toFixed(0)} km</div>
      <div class="card-sub">達成 ${monthPct.toFixed(1)}% · ${paceText}</div>
      <div class="goal-progress"><span style="width:${Math.min(100, monthPct)}%"></span></div>
    </div>
    <div class="card">
      <div class="card-label">${year} 年截至 ${selectedGoalMonth} 月年度進度</div>
      <div class="card-value">${yearKm.toFixed(2)} / ${Number(runningGoal.yearly_km).toFixed(0)} km</div>
      <div class="card-sub">達成 ${yearPct.toFixed(1)}% · 尚差 ${Math.max(0, runningGoal.yearly_km - yearKm).toFixed(2)} km</div>
      <div class="goal-progress"><span style="width:${Math.min(100, yearPct)}%"></span></div>
    </div>`;
}

function onGoalMonthChange() {
  selectedGoalMonth = Number(document.getElementById('goal-month-select').value) || 1;
  renderGoalProgress();
}

async function saveRunningGoal() {
  const status = document.getElementById('goal-settings-status');
  const payload = {
    expected_version: Number(runningGoal.version || 0),
    start_year: Number(document.getElementById('goal-start-year').value),
    monthly_km: Number(document.getElementById('goal-monthly-km').value),
  };
  if (!Number.isInteger(payload.start_year) || payload.monthly_km <= 0) {
    status.textContent = '請輸入有效的年份與正數里程。';
    return;
  }
  try {
    runningGoal = await apiPut('/running-goal', payload);
    dashboardAnalyticsCache.clear();
    status.textContent = '目標已儲存。';
    populateYearSelect();
    renderGoalProgress();
  } catch (error) {
    status.textContent = error.message || '目標儲存失敗。';
  }
}

function onStackedYearChange() {
  const sel = document.getElementById('stacked-year-select');
  selectedStackedYear = parseInt(sel.value, 10) || null;
  renderShoeStackedChart();
}

async function renderShoeStackedChart() {
  if (chartInstances.shoeStacked) { chartInstances.shoeStacked.destroy(); delete chartInstances.shoeStacked; }
  const sel = document.getElementById('stacked-year-select');
  const year = parseInt(sel ? sel.value : selectedStackedYear, 10);
  if (!year) return;
  const requestId = ++stackedRunsRequestId;
  let yearRuns = yearlyRunsCache.get(year);
  if (!yearRuns) {
    try {
      yearRuns = await fetchRunPages({ year });
    } catch (error) {
      console.error('載入年度跑步紀錄失敗:', error);
      return;
    }
    if (requestId !== stackedRunsRequestId) return;
    yearlyRunsCache.set(year, yearRuns);
  }
  if (requestId !== stackedRunsRequestId) return;

  const labels = Array.from({length: 12}, (_, i) => (i + 1) + '月');
  const allShoes = [...shoes, ...retiredShoes];

  // Build matrix: shoeId -> array of 12 month values
  const shoeMonthlyMap = new Map();
  yearRuns.forEach(r => {
    if (!r.date || !r.shoe_id) return;
    const rYear = parseInt(r.date.slice(0, 4), 10);
    const rMonth = parseInt(r.date.slice(5, 7), 10);
    if (rYear === year && rMonth >= 1 && rMonth <= 12) {
      if (!shoeMonthlyMap.has(r.shoe_id)) {
        shoeMonthlyMap.set(r.shoe_id, Array(12).fill(0));
      }
      shoeMonthlyMap.get(r.shoe_id)[rMonth - 1] += r.km;
    }
  });

  // Filter to shoes that actually have runs in this selected year
  const activeShoeIds = [...shoeMonthlyMap.keys()];
  const displayShoes = allShoes.filter(s => activeShoeIds.includes(s.id));

  let brandSeq = {};
  const datasets = displayShoes.map(s => {
    brandSeq[s.brand] = (brandSeq[s.brand] || 0);
    const color = brandColor(s.brand, brandSeq[s.brand]);
    brandSeq[s.brand]++;
    const data = shoeMonthlyMap.get(s.id).map(v => parseFloat(v.toFixed(2)));
    return {
      label: s.brand + ' ' + s.model + (s.is_retired ? ' (退役)' : ''),
      data,
      backgroundColor: color,
      borderRadius: 2,
    };
  });

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  chartInstances.shoeStacked = new Chart(document.getElementById('chart-shoe-stacked'), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.raw.toFixed(2)} km`
          }
        }
      },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: textColor, font: { size: 11 } } },
        y: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true }
      }
    }
  });
}

function renderYearlyTotalChart() {
  if (chartInstances.yearlyTotal) { chartInstances.yearlyTotal.destroy(); delete chartInstances.yearlyTotal; }
  if (monthlyMileages.length === 0) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');
  const mainTextColor = getThemeColor('--text', '#1e293b');

  const yearMap = new Map();
  monthlyMileages.forEach(m => {
    yearMap.set(m.year, (yearMap.get(m.year) || 0) + m.km);
  });
  const years = [...yearMap.keys()].sort((a, b) => a - b);
  const totals = years.map(y => parseFloat(yearMap.get(y).toFixed(2)));

  chartInstances.yearlyTotal = new Chart(document.getElementById('chart-yearly-total'), {
    type: 'bar',
    data: {
      labels: years.map(String),
      datasets: [{
        label: '年總跑量',
        data: totals,
        backgroundColor: '#6366f1',
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw.toFixed(2) + ' km' } }
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true, suggestedMax: Math.ceil(Math.max(...totals) * 1.15 / 50) * 50 }
      }
    },
    plugins: [{
      id: 'valueOnTop',
      afterDatasetsDraw(chart) {
        const { ctx } = chart;
        const meta = chart.getDatasetMeta(0);
        meta.data.forEach((bar, i) => {
          const v = totals[i];
          if (!bar) return;
          ctx.save();
          ctx.fillStyle = mainTextColor;
          ctx.font = 'bold 11px "Segoe UI", system-ui, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(v.toFixed(0), bar.x, bar.y - 6);
          ctx.restore();
        });
      }
    }]
  });
}

function renderMonthlyYearChart() {
  if (chartInstances.monthlyYear) { chartInstances.monthlyYear.destroy(); delete chartInstances.monthlyYear; }
  const sel = document.getElementById('year-select');
  const year = parseInt(sel.value, 10);
  if (!year) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  const yearData = monthlyMileages.filter(m => m.year === year);
  const monthMap = new Map(yearData.map(m => [m.month, m.km]));
  const labels = Array.from({length: 12}, (_, i) => (i + 1) + '月');
  const values = Array.from({length: 12}, (_, i) => monthMap.get(i + 1) ?? 0);

  const total = values.reduce((a, b) => a + b, 0);
  // Divide by months that actually have a record (user logs 0 for inactive months)
  const monthsWithData = yearData.length;
  const avg = monthsWithData > 0 ? total / monthsWithData : 0;

  chartInstances.monthlyYear = new Chart(document.getElementById('chart-monthly-year'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: year + ' 年月跑量 (km)',
        data: values,
        backgroundColor: '#22c55e',
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw.toFixed(2) + ' km' } }
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 11 } } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true }
      }
    },
    plugins: [{
      id: 'avgLine',
      afterDraw(chart) {
        const { ctx, chartArea, scales: { y } } = chart;
        if (avg <= 0) return;
        const yPx = y.getPixelForValue(avg);
        if (yPx < chartArea.top || yPx > chartArea.bottom) return;
        ctx.save();
        ctx.strokeStyle = '#eab308';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(chartArea.left, yPx);
        ctx.lineTo(chartArea.right, yPx);
        ctx.stroke();
        ctx.fillStyle = '#eab308';
        ctx.font = '11px "Segoe UI", system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText('月均 ' + avg.toFixed(1) + ' km', chartArea.right - 6, yPx - 6);
        ctx.restore();
      }
    }]
  });
}

// ====== Spending Charts & Render ======
function renderSpendingCharts() {
  if (chartInstances.spending) { chartInstances.spending.destroy(); delete chartInstances.spending; }
  if (chartInstances.spendingYearly) { chartInstances.spendingYearly.destroy(); delete chartInstances.spendingYearly; }
  renderSpendingCards();
  populateSpendingYearSelect();
  renderSpendingChart();
  renderSpendingYearlyChart();
  renderSpendingTable();
}

function populateSpendingYearSelect() {
  const sel = document.getElementById('spending-year-select');
  const years = [...new Set(monthlySpending.map(m => m.year))].sort((a, b) => b - a);
  if (years.length === 0) {
    sel.innerHTML = '<option value="">無資料</option>';
    selectedSpendingYear = null;
    return;
  }
  if (!selectedSpendingYear || !years.includes(selectedSpendingYear)) {
    selectedSpendingYear = years[0];
  }
  sel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedSpendingYear ? 'selected' : ''}>${y} 年</option>`).join('');
}

function onSpendingYearChange() {
  const sel = document.getElementById('spending-year-select');
  selectedSpendingYear = parseInt(sel.value, 10) || null;
  renderSpendingChart();
}

function renderSpendingCards() {
  const allShoes = [...shoes, ...retiredShoes];
  const totalPaid = allShoes.reduce((sum, s) => sum + (s.price || 0), 0);
  const totalOrig = allShoes.reduce((sum, s) => sum + (s.orig_price || 0), 0);
  const totalSavings = totalOrig - totalPaid;
  const avgDiscount = totalOrig > 0 ? (totalPaid / totalOrig) * 100 : 100;

  // Average monthly spend: from first purchase month through current month.
  // Months with no purchases still count in the denominator (gives true
  // monthly burn rate over your entire buying history).
  const validDates = allShoes.filter(s => s.date).sort((a, b) => new Date(a.date) - new Date(b.date));
  let avgMonthly = 0;
  let monthSpan = 0;
  let startDate = null;
  if (validDates.length > 0) {
    startDate = new Date(validDates[0].date);
    const now = new Date();
    monthSpan = (now.getFullYear() - startDate.getFullYear()) * 12 + (now.getMonth() - startDate.getMonth()) + 1;
    avgMonthly = monthSpan > 0 ? totalPaid / monthSpan : 0;
  }

  // Find highest spend month
  let highestMonth = '';
  let highestAmount = 0;
  monthlySpending.forEach(m => {
    if (m.total_paid > highestAmount) {
      highestAmount = m.total_paid;
      highestMonth = `${m.year}/${String(m.month).padStart(2, '0')}`;
    }
  });

  const spanLabel = monthSpan > 0 && startDate
    ? `從 ${startDate.getFullYear()}/${String(startDate.getMonth()+1).padStart(2,'0')} 到今月，共 ${monthSpan} 個月`
    : '無購買紀錄';

  const cards = [
    { label: '總花費', value: '$' + Math.round(totalPaid).toLocaleString(), sub: '買價總和' },
    { label: '原價總和', value: '$' + Math.round(totalOrig).toLocaleString(), sub: '原始價格' },
    { label: '省下金額', value: '$' + Math.round(totalSavings).toLocaleString(), sub: '總折扣' },
    { label: '平均折數', value: avgDiscount.toFixed(1) + '%', sub: '$' + Math.round(totalPaid) + ' / $' + Math.round(totalOrig) },
    { label: '平均月支出', value: '$' + Math.round(avgMonthly).toLocaleString(), sub: spanLabel },
    { label: '最高支出月', value: '$' + Math.round(highestAmount).toLocaleString(), sub: highestMonth || '無' },
  ];
  document.getElementById('spending-cards').innerHTML = cards.map(c =>
    `<div class="card"><div class="card-label">${c.label}</div><div class="card-value">${c.value}</div><div class="card-sub">${c.sub}</div></div>`
  ).join('');
}

function _spendingMonthMap(year) {
  // Build label/data arrays for all 12 months of the given year, filling 0
  const labels = Array.from({length: 12}, (_, i) => (i + 1) + ' 月');
  const paid = Array(12).fill(0);
  monthlySpending.forEach(m => {
    if (m.year === year) {
      paid[m.month - 1] = m.total_paid;
    }
  });
  return { labels, paid };
}

function renderSpendingChart() {
  if (chartInstances.spending) { chartInstances.spending.destroy(); delete chartInstances.spending; }

  const sel = document.getElementById('spending-year-select');
  const year = parseInt(sel.value, 10);
  if (!year) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  const { labels, paid } = _spendingMonthMap(year);

  chartInstances.spending = new Chart(document.getElementById('chart-spending'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '花費',
        data: paid,
        backgroundColor: '#6366f1',
        borderRadius: 4,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => '$' + Math.round(ctx.raw).toLocaleString(),
          },
        },
      },
      responsive: true,
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: textColor, font: { size: 11 } },
        },
        y: {
          grid: { color: gridColor },
          ticks: { color: textColor, callback: v => '$' + v },
          beginAtZero: true,
        },
      },
    },
  });
}

function renderSpendingYearlyChart() {
  if (chartInstances.spendingYearly) { chartInstances.spendingYearly.destroy(); delete chartInstances.spendingYearly; }
  if (monthlySpending.length === 0) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  const yearMap = new Map();
  monthlySpending.forEach(m => {
    if (!yearMap.has(m.year)) yearMap.set(m.year, { paid: 0, orig: 0 });
    yearMap.get(m.year).paid += m.total_paid;
    yearMap.get(m.year).orig += m.total_orig;
  });
  const years = [...yearMap.keys()].sort((a, b) => a - b);
  const paidTotals = years.map(y => yearMap.get(y).paid);

  chartInstances.spendingYearly = new Chart(document.getElementById('chart-spending-yearly'), {
    type: 'bar',
    data: {
      labels: years.map(String),
      datasets: [{
        label: '年度花費',
        data: paidTotals,
        backgroundColor: '#6366f1',
        borderRadius: 4,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => '$' + Math.round(ctx.raw).toLocaleString(),
          },
        },
      },
      responsive: true,
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: textColor },
        },
        y: {
          grid: { color: gridColor },
          ticks: { color: textColor, callback: v => '$' + v },
          beginAtZero: true,
        },
      },
    },
  });
}

function renderSpendingTable() {
  const tbody = document.getElementById('spending-table');
  const allShoes = [...shoes, ...retiredShoes].sort(byDate);
  tbody.innerHTML = allShoes.map(s => {
    const discount = s.orig_price > 0 ? (s.price / s.orig_price * 100).toFixed(1) : '—';
    const status = s.is_retired ? '已退役' : '使用中';
    return `<tr>
      <td>${esc(s.date.replace(/-/g, '/'))}</td>
      <td>${esc(s.brand)}</td>
      <td>${esc(s.model)}</td>
      <td>${fmtMoney(s.price)}</td>
      <td>${fmtMoney(s.orig_price)}</td>
      <td>${discount}%</td>
      <td>${esc(shoeCategories(s).join(', ') || '未分類')}</td>
      <td>${status}</td>
    </tr>`;
  }).join('');
}

// ====== Inline Edit (double-click) ======
// 現役與退役共用的表格內即時編輯：差別只在操作哪個陣列（arr）
async function inlineEditRow(arr, idx, field, el) {
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'inline-input';
  input.value = arr[idx][field];
  const shoe = { ...arr[idx] };
  let committed = false;
  const commit = async () => {
    if (committed) return;
    committed = true;
    const val = parseFloat(input.value);
    if (Number.isFinite(val) && val >= 0) {
      try {
        await apiPut('/shoes/' + shoe.id, { [field]: val, expected_version: shoe.version });
        await loadData();
      } catch (e) {
        alert(e.message || '更新失敗');
      }
    }
    render();
  };
  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { committed = true; render(); } });
  el.innerHTML = '';
  el.appendChild(input);
  input.focus();
}

// ====== Shoe Category Helpers ======
function getSelectedCategories() {
  const checked = document.querySelectorAll('#f-category-group input[type="checkbox"]:checked');
  return Array.from(checked).map(cb => cb.value);
}

// ====== Modal (Shoe) ======
class ShoeModal {
  constructor() {
    this.el = document.getElementById('modal');
    this.formIds = {
      brand: 'f-brand', model: 'f-model', date: 'f-date', size: 'f-size',
      price: 'f-price', orig: 'f-orig', mileage: 'f-mileage',
      expected: 'f-expected', monthly: 'f-monthly'
    };
    this.btnDelete = document.getElementById('btn-delete');
    this.btnMove = document.getElementById('btn-move');
    this.titleEl = document.getElementById('modal-title');
    this.monthlyRow = document.getElementById('f-monthly').parentElement;

    // 綁定一次
    this.el.querySelector('.btn-primary').onclick = () => this.submit();
    this.btnDelete.onclick = () => this.delete();
    this.btnMove.onclick = () => this.move();
    this.el.onclick = e => { if (e.target === this.el) this.close(); };
  }

  // ── 公開 API ──────────────────────────────────────────────
  openForCreate() {
    this.mode = 'create';
    this.shoe = null;
    this._resetForm();
    this._updateUI({ title: '新增跑鞋', showDelete: false, showMove: false, monthly: 60, monthlyVisible: true });
    this._show();
  }

  openForEdit(shoe, isRetired) {
    this.mode = isRetired ? 'editRetired' : 'editActive';
    this.shoe = { ...shoe };
    this._fillForm(shoe);
    this._updateUI({
      title: isRetired ? '編輯退役跑鞋' : '編輯跑鞋',
      showDelete: true,
      showMove: true,
      moveText: isRetired ? '移至現役' : '移至退役',
      monthly: isRetired ? 0 : shoe.monthly_km,
      monthlyVisible: !isRetired
    });
    this._show();
  }

  // ── 內部邏輯 ──────────────────────────────────────────────
  _resetForm() {
    Object.values(this.formIds).forEach(id => document.getElementById(id).value = '');
    document.getElementById('f-date').value = localDateISO();
    document.getElementById('f-expected').value = 800;
    // Reset category checkboxes — default to "Daily" checked
    document.querySelectorAll('#f-category-group input[type="checkbox"]')
      .forEach(cb => cb.checked = cb.value === 'Daily');
  }

  _fillForm(s) {
    Object.entries(this.formIds).forEach(([k, id]) => {
      const field = k === 'orig' ? 'orig_price' : k === 'expected' ? 'expected_mileage' : k;
      document.getElementById(id).value = s[field] ?? '';
    });
    // Check category checkboxes based on the shoe's categories
    const cats = shoeCategories(s);
    document.querySelectorAll('#f-category-group input[type="checkbox"]')
      .forEach(cb => cb.checked = cats.includes(cb.value));
  }

  _updateUI({ title, showDelete, showMove, moveText, monthly, monthlyVisible }) {
    this.titleEl.textContent = title;
    this.btnDelete.style.display = showDelete ? 'inline-block' : 'none';
    this.btnMove.style.display = showMove ? 'inline-block' : 'none';
    this.btnMove.textContent = moveText || '';
    this.monthlyRow.style.display = monthlyVisible ? '' : 'none';
    document.getElementById('f-monthly').value = monthly;
  }

  _show() { this.el.classList.add('active'); }
  close() { this.el.classList.remove('active'); this.shoe = null; }

  _payload() {
    const get = id => document.getElementById(id).value;
    const num = id => parseFloat(get(id)) || 0;
    return {
      brand: get('f-brand').trim(),
      model: get('f-model').trim(),
      date: get('f-date'),
      size: get('f-size').trim(),
      price: num('f-price'),
      orig_price: num('f-orig'),
      mileage: num('f-mileage'),
      expected_mileage: num('f-expected'),
      monthly_km: num('f-monthly'),
      categories: getSelectedCategories(),
      is_retired: this.mode === 'editRetired'
    };
  }

  async submit() {
    if (this.saving) return;
    const data = this._payload();
    if (!data.brand || !data.model || !data.date) return alert('請填寫品牌、鞋款、日期');
    this.saving = true;
    const saveButton = this.el.querySelector('.btn-primary');
    saveButton.disabled = true;
    try {
      if (this.mode === 'create') await apiPost('/shoes', data);
      else {
        const changes = Object.fromEntries(Object.entries(data).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(this.shoe[key])));
        await apiPut('/shoes/' + this.shoe.id, { ...changes, expected_version: this.shoe.version });
      }
      this.close();
      await loadData();
    } catch (e) { alert(e.message || '儲存失敗'); }
    finally {
      this.saving = false;
      saveButton.disabled = false;
    }
  }

  async delete() {
    if (!confirm(`確定刪除 ${this.shoe.brand} ${this.shoe.model}？跑步紀錄會保留，但鞋款無法復原。`)) return;
    try { await apiDelete('/shoes/' + this.shoe.id + '?expected_version=' + (this.shoe.version || 0)); }
    catch (e) { return alert(e.message || '刪除失敗'); }
    this.close();
    await loadData();
  }

  async move() {
    const targetRetired = this.mode === 'editActive';
    if (!confirm(`確定要移至${targetRetired ? '退役' : '現役'}？`)) return;
    try {
      const payload = { is_retired: targetRetired, expected_version: this.shoe.version, monthly_km: this.shoe.monthly_km };
      if (targetRetired) {
        payload.monthly_km = 0;
      } else if (!payload.monthly_km) {
        // 退役時月跑量被歸零，回到現役時用其他現役鞋的平均月跑量當起始參考，
        // 避免硬編碼 60。
        const activeKm = shoes
          .filter(s => s.id !== this.shoe.id && !s.is_retired && s.monthly_km > 0)
          .map(s => s.monthly_km);
        payload.monthly_km = activeKm.length
          ? Math.round(activeKm.reduce((a, b) => a + b, 0) / activeKm.length * 10) / 10
          : 60;
      }
      await apiPut('/shoes/' + this.shoe.id, payload);
    } catch (e) { return alert(e.message || '移動失敗'); }
    this.close();
    await loadData();
  }
}

// 初始化一次
const shoeModal = new ShoeModal();

// 給舊呼叫處用的精簡 wrapper
function openAddModal()      { shoeModal.openForCreate(); }
function openEditModal(i)    { shoeModal.openForEdit(shoes[i], false); }
function openRetiredEditModal(i) { shoeModal.openForEdit(retiredShoes[i], true); }
function closeModal()        { shoeModal.close(); }

// ====== Init ======
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
    try {
      const response = await fetch(API_BASE + '/auth/me', { headers: authHeaders() });
      if (response.status === 401) {
        clearAuth();
        showLoginView();
        document.body.style.opacity = '1';
        return;
      }
      if (!response.ok) throw new Error('驗證服務暫時無法使用');
      showAppView();
      loadAgentModels();
      // 還原 F5 之前的 tab（init 走 stored token，沒經過 resetAppLayout）。
      const savedTab = localStorage.getItem('activeTab');
      if (savedTab && savedTab !== 'runs') switchTab(savedTab);
      loadData();
    } catch (error) {
      // 離線或伺服器暫時無法連線時保留 token，避免 PWA 被迫重新登入。
      console.warn('無法驗證登入狀態，保留目前工作階段:', error);
      showAppView();
      loadAgentModels();
      loadData();
    }
  } else {
    showLoginView();
  }
  document.body.style.opacity = '1';
}

init();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js')
      .catch(error => console.warn('Service Worker 註冊失敗:', error));
  });
}

// Resize handler — re-apply agent tab layout on window resize
window.addEventListener('resize', () => {
  const activePanel = document.querySelector('.tab-panel.active');
  if (activePanel && activePanel.dataset.panel === 'agent') {
    const appView = document.getElementById('app-view');
    appView.style.height = 'max(100dvh, 680px)';
  }
});
