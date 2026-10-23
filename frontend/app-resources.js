// Compatibility bridge: native ownership/policy, legacy feature cache adapters.
let resourceStore = null;

async function initializeDataResources() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  const { createResourceStore } = await import('./runtime/resource-store.mjs?v=' + encodeURIComponent(version));
  resourceStore = createResourceStore({ session: { capture: captureAuthSession, current: isCurrentAuthSession } });
  registerResourceCaches();
}

function registerResourceCaches() {
  resourceStore.registerCache('spending', () => {
    spendingSummary = null; spendingLoadRequestId++; spendingLoadPending = false;
  });
  resourceStore.registerCache('goal', () => {
    goalProgressRequestId++; resourceStore.invalidate(['goal-progress']);
  });
  resourceStore.registerCache('annual', () => {
    runController.state.annualRequest++; resourceStore.invalidate(['annual-summary']);
  });
  resourceStore.registerCache('dashboard', () => {
    dashboardAnalyticsRequest++; resourceStore.invalidate(['dashboard-analytics']);
  });
}

function invalidateDataResources(resources) {
  resourceStore.invalidate(resources);
  document.getElementById('data-load-error').hidden = !resourceStore.hasErrors();
}
registerFeatureReset('data-resources', () => resourceStore?.reset());
