// Dashboard shell, theme, tab navigation, and aggregate data loading.
let panelRevision = 0;
const renderedPanels = new Map();

function invalidatePanels(resource = null) {
  if (!resource) {
    panelRevision += 1;
    runController.state.annualRequest += 1;
    return;
  }
  // The shoes panel also draws run-derived charts (rotation timeline, distance mix). Accepting
  // runs or the goal drops their cached reads, so those arrivals must redraw it as well.
  const dependencies = { shoes: ['shoes', 'runs', 'monthly'],
    monthly: ['monthly'], runs: ['shoes', 'runs', 'monthly'], goal: ['shoes', 'runs', 'monthly'] };
  for (const name of dependencies[resource] || []) renderedPanels.delete(name);
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
    // Spending lives at the bottom of the shoes tab.
    renderSpendingCharts();
  } else if (name === 'runs') {
    populateRunShoeSelects(); renderRunLog(); renderHomeSummary(); renderOnboarding();
  } else if (name === 'monthly') {
    if (typeof Chart !== 'undefined') renderMonthlyCharts();
  }
}

function setMobileMenu(open) {
  document.getElementById('sidebar-menu').classList.toggle('menu-open', open);
  document.querySelector('.mobile-menu-toggle').setAttribute('aria-expanded', String(open));
}

function switchTab(name) {
  // Establish a baseline before the fields become interactive; the chart render
  // runs in a later frame and must already recognize edits made in between.
  if (name === 'monthly') prepareGoalForm();
  // Chat and the monthly report share one AI destination.
  const destination = name === 'report' ? 'agent' : name;
  document.querySelectorAll('.tab').forEach(tab => {
    const active = tab.dataset.tab === destination;
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

const systemLightQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

function resolveTheme(preference, systemPrefersLight) {
  if (preference === 'light' || preference === 'dark') return preference;
  return systemPrefersLight ? 'light' : 'dark';
}

// Accepts a preference (light, dark or system); charts redraw when the shown theme changes.
function applyTheme(theme) {
  themePreference = THEME_PREFERENCES.includes(theme) ? theme : 'system';
  try { localStorage.setItem('theme', themePreference); } catch {}
  currentTheme = resolveTheme(themePreference, Boolean(systemLightQuery?.matches));
  document.body.classList.toggle('light-theme', currentTheme === 'light');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', currentTheme === 'light' ? '#eef1f4' : '#07090c');
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === themePreference));
  });
}

function setThemePreference(preference) {
  const previous = currentTheme;
  applyTheme(preference);
  if (currentTheme !== previous) {
    invalidatePanels();
    renderActivePanel();
  }
}

// Switches the shown theme directly (used by browser checks to force a themed redraw).
function toggleTheme() {
  setThemePreference(currentTheme === 'dark' ? 'light' : 'dark');
}

// Following the system: redraw when the device switches between light and dark.
systemLightQuery?.addEventListener?.('change', () => {
  if (themePreference === 'system') setThemePreference('system');
});

applyTheme(themePreference);

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
  const applyResource = result => {
    const [accepted] = resourceStore.accept([result], mutation);
    if (!accepted || !isCurrentAuthSession(session)) return;
    const { resource, value } = accepted;
    error.hidden = !resourceStore.hasErrors();
    if (accepted.status === 'rejected') {
      if (accepted.error.name !== 'AbortError') console.error('載入資料失敗:', accepted.error);
      return;
    }
    if (resource === 'shoes' || resource === 'monthly' || resource === 'goal') applyCoreResource(resource, value);
    if (resource === 'runs' && value.requestId === runController.state.listRequest
        && requestedRunMonth === selectedRunMonth()) {
      const { page, summary } = value;
      Object.assign(runController.state, { rows: page.rows, summary, offset: 0, hasMore: page.hasMore, day: null });
      document.getElementById('run-load-error').hidden = true;
    }
    if (typeof workspaceDataArrived === 'function' && (resource !== 'runs' || requestedRunMonth === selectedRunMonth())) workspaceDataArrived(resource, value);
    render(resource);
    // A slow optional source must not hold an otherwise usable screen behind boot.
    if (typeof hideAppBoot === 'function') hideAppBoot();
  };
  const completion = resourceStore.refresh(mutation, readers, { runs: requestedRunMonth }, applyResource);
  if (resourceStore.policy(mutation).history) void loadStravaHistory();
  await completion;
}
