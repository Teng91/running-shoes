// Dashboard shell, theme, tab navigation, and aggregate data loading.
function setMobileMenu(open) {
  document.getElementById('sidebar-menu').classList.toggle('menu-open', open);
  document.querySelector('.mobile-menu-toggle').setAttribute('aria-expanded', String(open));
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(tab => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.toggle('active', panel.dataset.panel === name));
  document.getElementById('app-workspace').classList.toggle('agent-mode', name === 'agent');
  document.getElementById('mobile-page-label').textContent = document.querySelector('.tab.active > span:last-child').textContent;
  const menuWasOpen = document.getElementById('sidebar-menu').classList.contains('menu-open');
  setMobileMenu(false);
  if (menuWasOpen && window.matchMedia('(max-width: 800px)').matches) {
    document.querySelector('.mobile-menu-toggle').focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
  localStorage.setItem('activeTab', name);
  if (name === 'monthly') requestAnimationFrame(() => renderMonthlyCharts());
  if (name === 'spending') requestAnimationFrame(() => renderSpendingCharts());
  if (name === 'runs') requestAnimationFrame(() => renderRunLog());
  if (name === 'report' && authToken) {
    loadReportHistory();
    loadSavedReport();
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
