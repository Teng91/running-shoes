// Dashboard shell, theme, tab navigation, and aggregate data loading.
let panelRevision = 0;
const renderedPanels = new Map();

// SPEC-101: feature scripts register what each panel draws and which data they own when they
// load. The shell never names a feature's functions, so features depend on it and not back.
const panelHooks = new Map();
const resourceReaders = new Map();
const dataHooks = [];

// hooks: { render() draws the panel, enter() runs before its tab opens, key() joins the redraw
// key }. A panel runs its hooks in registration order, i.e. the script order in assets.json.
function registerPanel(name, hooks) {
  if (!panelHooks.has(name)) panelHooks.set(name, []);
  panelHooks.get(name).push(hooks);
}

// reader: { scope() is taken when a load starts, read(scope) loads, current(scope) tells whether
// the screen still shows that scope, apply(value) stores a current value }.
function registerResourceReader(name, reader) {
  resourceReaders.set(name, reader);
}

// hooks: { arrived(resource, value, current) after a resource is applied (current: the value
// still matches the screen's scope), invalidated() on a full redraw,
// history() when a load also refreshes the import history }.
function registerDataHooks(hooks) {
  dataHooks.push(hooks);
}

function invalidatePanels(resource = null) {
  if (!resource) {
    panelRevision += 1;
    dataHooks.forEach(hook => hook.invalidated?.());
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
  const hooks = panelHooks.get(name) || [];
  const key = [panelRevision, currentTheme, localDateISO(), ...hooks.map(hook => hook.key?.() ?? '')].join('|');
  if (!name || renderedPanels.get(name) === key) return;
  renderedPanels.set(name, key);
  hooks.forEach(hook => hook.render?.());
}

function setMobileMenu(open) {
  document.getElementById('sidebar-menu').classList.toggle('menu-open', open);
  document.querySelector('.mobile-menu-toggle').setAttribute('aria-expanded', String(open));
}

function switchTab(name) {
  // Features prepare before the fields become interactive (the goal form takes its baseline);
  // the chart render runs in a later frame and must already recognize edits made in between.
  (panelHooks.get(name) || []).forEach(hook => hook.enter?.());
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
  const error = document.getElementById('data-load-error');
  // Scopes are taken now: a value loaded for another scope (e.g. a run month the user has
  // since left) is not applied.
  const scopes = {};
  const readers = {
    shoes: () => Promise.all([apiGet('/shoes/active'), apiGet('/shoes/retired')]),
    monthly: () => apiGet('/monthly-mileage'),
  };
  for (const [name, reader] of resourceReaders) {
    const scope = reader.scope?.();
    if (scope !== undefined) scopes[name] = scope;
    readers[name] = () => reader.read(scope);
  }
  readers.goal = () => apiGet('/running-goal');
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
    const reader = resourceReaders.get(resource);
    const current = !reader?.current || reader.current(scopes[resource]);
    if (reader && current) reader.apply(value);
    dataHooks.forEach(hook => hook.arrived?.(resource, value, current));
    // A slow optional source must not hold an otherwise usable screen behind boot.
    if (typeof hideAppBoot === 'function') hideAppBoot();
  };
  const completion = resourceStore.refresh(mutation, readers, scopes, applyResource);
  if (resourceStore.policy(mutation).history) dataHooks.forEach(hook => void hook.history?.());
  await completion;
}

// loadData delivers resources progressively and records errors instead of rejecting.
// Mutations need an explicit core-data check before reporting refreshed UI.
async function refreshCoreData(options) {
  const session = captureAuthSession();
  await loadData(options);
  if (!isCurrentAuthSession(session)) throw Object.assign(Error('登入狀態已變更'), { name: 'AbortError' });
  if (resourceStore.policy(options?.mutation).resources.some(resource => resourceStore.getError(resource))) {
    throw new Error('資料讀取尚未完成');
  }
}
