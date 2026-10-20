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
  featureLifecycle = createLifecycle(name => console.error('功能清理失敗：', name));
  for (const [name, reset] of featureResetters) featureLifecycle.register(name, reset);
}

function resetFeatureLifecycles() {
  if (!featureLifecycle) throw new Error('Application runtime is not initialized');
  featureLifecycle.reset();
}
