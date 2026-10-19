// Dashboard shell, theme, tab navigation, and aggregate data loading.
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.panel === name));
  localStorage.setItem('activeTab', name);
  if (name === 'monthly') requestAnimationFrame(() => renderMonthlyCharts());
  if (name === 'spending') requestAnimationFrame(() => renderSpendingCharts());
  if (name === 'runs') requestAnimationFrame(() => renderRunLog());
  if (name === 'report' && authToken) {
    loadReportHistory();
    loadSavedReport();
  }
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
  applyTheme(currentTheme === 'dark' ? 'light' : 'dark');
  const activeTab = document.querySelector('.tab.active')?.dataset?.tab || 'runs';
  if (activeTab === 'shoes') renderCharts();
  else if (activeTab === 'monthly') renderMonthlyCharts();
  else if (activeTab === 'spending') renderSpendingCharts();
  else if (activeTab === 'runs') renderRunLog();
}

applyTheme(currentTheme);

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
      apiGet('/runs/import/strava/history').catch(loadError => {
        console.warn('載入 Strava 匯入歷史失敗:', loadError);
        return [];
      }),
      apiGet('/running-goal'),
    ]);
    if (generation !== dataLoadGeneration || token !== authToken || requestedRunMonth !== selectedRunMonth()) return;
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
  } catch (loadError) {
    console.error('載入資料失敗:', loadError);
    if (generation !== dataLoadGeneration || token !== authToken || requestedRunMonth !== selectedRunMonth()) return;
    error.hidden = false;
    return;
  }
  if (monthlyMileages.length > 0) {
    const years = [...new Set(monthlyMileages.map(item => item.year))].sort((a, b) => b - a);
    if (!selectedYear || !years.includes(selectedYear)) selectedYear = years[0];
  } else {
    selectedYear = new Date().getFullYear();
  }
  render();
}
