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
  featureLifecycle = createLifecycle(name => console.error('功能清理失敗：', name));
  for (const [name, reset] of featureResetters) featureLifecycle.register(name, reset);
}

function resetFeatureLifecycles() {
  if (!featureLifecycle) throw new Error('Application runtime is not initialized');
  featureLifecycle.reset();
}

let formOperationFactory = null;
let formSnapshotMatches = null;
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
  return `${shoe.nickname ? shoe.nickname + ' · ' : ''}${name} · ${shoe.date} · #${shoe.id}${shoe.is_retired ? ' · 已退役' : ''}`;
}
