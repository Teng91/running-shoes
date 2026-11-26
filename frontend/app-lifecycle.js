// Compatibility bridge while legacy DOM handlers migrate to native modules.
const featureResetters = new Map();
let featureLifecycle = null;

function registerFeatureReset(name, reset) {
  if (featureResetters.has(name)) throw new Error('Duplicate feature lifecycle: ' + name);
  featureResetters.set(name, reset);
  if (featureLifecycle) featureLifecycle.register(name, reset);
}

async function initializeFeatureLifecycle() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  const { createLifecycle } = await import('./runtime/feature-lifecycle.mjs?v=' + encodeURIComponent(version));
  const forms = await import('./runtime/form-operations.mjs?v=' + encodeURIComponent(version));
  formOperationFactory = forms.createFormOperations;
  formSnapshotMatches = forms.matchesSnapshot;
  formDraftFactory = forms.createFormDraft;
  featureLifecycle = createLifecycle(name => console.error('功能清理失敗：', name));
  for (const [name, reset] of featureResetters) featureLifecycle.register(name, reset);
}

function resetFeatureLifecycles() {
  if (!featureLifecycle) throw new Error('Application runtime is not initialized');
  featureLifecycle.reset();
}

let formOperationFactory = null;
let formSnapshotMatches = null;
let formDraftFactory = null;
const formDrafts = new Map();
const formOperationOwners = new Map();
function getFormOperations(name) {
  if (!formOperationOwners.has(name)) {
    if (!formOperationFactory) throw new Error('Form runtime is not initialized');
    const owner = formOperationFactory({ capture: captureAuthSession, current: isCurrentAuthSession });
    formOperationOwners.set(name, owner);
    registerFeatureReset('form-' + name, () => owner.reset());
  }
  return formOperationOwners.get(name);
}

function readForm(ids) {
  return Object.fromEntries(ids.map(id => [id, String(document.getElementById(id).value)]));
}

function matchesForm(snapshot) {
  return formSnapshotMatches(snapshot, readForm(Object.keys(snapshot)));
}

function shoeLabel(shoe) {
  const name = [shoe.brand, shoe.model].join(' ');
  return `${shoe.nickname ? shoe.nickname + ' · ' : ''}${name} · ${shoe.date}${shoe.is_retired ? ' · 已退役' : ''}`;
}

function getFormDraft(name) {
  if (!formDrafts.has(name)) {
    const draft = formDraftFactory();
    formDrafts.set(name, draft);
    registerFeatureReset('draft-' + name, () => draft.reset());
  }
  return formDrafts.get(name);
}

// SPEC-101: feature scripts register what each panel draws and which data they own when they
// load. The shell (app-core.js) never names a feature's functions, so features depend on it and
// not back. The registry lives here because this script loads before every feature (SPEC-106):
// a script may call, while it loads, only functions of scripts loaded before it.
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
// refreshed(resource) after the shell's refreshPanels redraw (SPEC-135),
// history() when a load also refreshes the import history }.
function registerDataHooks(hooks) {
  dataHooks.push(hooks);
}

// SPEC-135: each feature registers how its dialog closes, by overlay ID. app-dialogs.js closes the
// topmost one on Escape, and a backdrop click closes the dialogs registered with backdrop: true.
// Another script closes a dialog with closeDialog(id), never with the owner's own close function.
const dialogClosers = new Map();

function registerDialog(id, { close, backdrop = false }) {
  if (dialogClosers.has(id)) throw new Error('Dialog registered twice: ' + id);
  dialogClosers.set(id, { close, backdrop });
}

function closeDialog(id, { fromBackdrop = false } = {}) {
  const dialog = dialogClosers.get(id);
  if (!dialog) throw new Error('Unknown dialog: ' + id);
  if (!fromBackdrop || dialog.backdrop) dialog.close();
}

// SPEC-135: features register what an automatic update must not interrupt (SPEC-059): a
// streaming answer, a request in flight, typed text. app-updates.js asks featureBusy().
const busyChecks = [];

function registerBusyCheck(check) {
  busyChecks.push(check);
}

function featureBusy() {
  return busyChecks.some(check => check());
}

// SPEC-113: delegated UI actions by event type. Each feature registers the actions its markup
// names (data-click="run-page" and the like); app-actions.js dispatches them and freezes the
// table once every feature has loaded. A name registered twice for one event type is an error.
const UI_ACTIONS = { click: {}, dblclick: {}, change: {}, input: {}, submit: {}, keydown: {} };

function registerUiActions(actionsByType) {
  for (const [type, actions] of Object.entries(actionsByType)) {
    // A late registration would otherwise be dropped silently by the frozen table.
    if (Object.isFrozen(UI_ACTIONS[type])) throw new Error('UI actions are already installed; register them while the script loads');
    for (const [name, handler] of Object.entries(actions)) {
      if (Object.hasOwn(UI_ACTIONS[type], name)) throw new Error(`UI action ${type}:${name} is registered twice`);
      UI_ACTIONS[type][name] = handler;
    }
  }
}
