// Dashboard shell, theme, tab navigation, and aggregate data loading.
let panelRevision = 0;
const renderedPanels = new Map();

function invalidatePanels() {
  panelRevision += 1;
  runController.state.annualRequest += 1;
}

function resetPanelRendering() {
  invalidatePanels();
  renderedPanels.clear();
  Object.values(chartInstances).forEach(chart => chart.destroy());
  chartInstances = {};
}

function renderActivePanel() {
  const name = document.querySelector('.tab-panel.active')?.dataset.panel;
  const key = `${panelRevision}|${currentTheme}|${localDateISO()}|${name === 'runs' ? selectedRunMonth() : ''}`;
  if (!name || renderedPanels.get(name) === key) return;
  renderedPanels.set(name, key);
  if (name === 'shoes') {
    renderCards(); renderAlerts(); renderCategorySummary(); renderTable(); renderRetiredTable();
    if (typeof Chart !== 'undefined') renderCharts();
  } else if (name === 'runs') {
    populateRunShoeSelects(); renderRunLog();
  } else if (name === 'monthly') {
    renderMonthlyTable();
    if (typeof Chart !== 'undefined') renderMonthlyCharts();
  } else if (name === 'spending') {
    renderSpendingCharts();
  }
}

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
  requestAnimationFrame(() => renderActivePanel());
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
  invalidatePanels();
  renderActivePanel();
}

applyTheme(currentTheme);

registerFeatureReset('panel-rendering', resetPanelRendering);

async function loadData({ mutation = null } = {}) {
  const session = captureAuthSession();
  const requestedRunMonth = selectedRunMonth();
  const [runYear, runMonth] = requestedRunMonth.split('-').map(Number);
  const error = document.getElementById('data-load-error');
  const readers = {
    shoes: () => Promise.all([apiGet('/shoes/active'), apiGet('/shoes/retired')]),
    monthly: () => apiGet('/monthly-mileage'),
    runs: () => {
      const requestId = ++runController.state.listRequest;
      return Promise.all([fetchRunPage({ year: runYear, month: runMonth }),
        apiGet(`/runs/summary?year=${runYear}&month=${runMonth}`)])
        .then(([page, summary]) => ({ page, summary, requestId }));
    },
    goal: () => apiGet('/running-goal'),
  };
  const results = await resourceStore.refresh(mutation, readers, { runs: requestedRunMonth });
  const accepted = resourceStore.accept(results, mutation);
  for (const result of accepted) {
    const { resource, value } = result;
    if (result.status === 'rejected') {
      if (result.error.name !== 'AbortError') console.error('載入資料失敗:', result.error);
      continue;
    }
    if (resource === 'shoes') [shoes, retiredShoes] = value;
    if (resource === 'monthly') monthlyMileages = value;
    if (resource === 'goal') runningGoal = value;
    if (resource === 'runs' && value.requestId === runController.state.listRequest
        && requestedRunMonth === selectedRunMonth()) {
      const { page, summary } = value;
      Object.assign(runController.state, { rows: page.rows, summary, offset: 0, hasMore: page.hasMore, day: null });
      document.getElementById('run-load-error').hidden = true;
    }
  }
  if (!isCurrentAuthSession(session)) return;
  error.hidden = !resourceStore.hasErrors();
  const succeeded = accepted.filter(result => result.status === 'fulfilled');
  if (!succeeded.length) return;
  if (succeeded.some(result => result.resource === 'monthly')) {
    const years = [...new Set(monthlyMileages.map(item => item.year))].sort((a, b) => b - a);
    if (!selectedYear || !years.includes(selectedYear)) selectedYear = years[0] || new Date().getFullYear();
  }
  render();
  if (resourceStore.policy(mutation).history && isCurrentAuthSession(session)) loadStravaHistory();
}
