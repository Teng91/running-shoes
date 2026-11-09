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
    goalProgressRequestId++; resourceStore.invalidate(['goal-progress', 'training-trends']);
  });
  resourceStore.registerCache('annual', () => {
    runController.state.annualRequest++;
    resourceStore.invalidate(['annual-summary', 'training-trends', 'shoe-timeline']);
  });
  resourceStore.registerCache('dashboard', () => {
    dashboardAnalyticsRequest++;
    resourceStore.invalidate(['dashboard-analytics', 'shoe-timeline', 'home-summary', 'year-review', 'shoe-distance-mix']);
  });
}

function invalidateDataResources(resources) {
  resourceStore.invalidate(resources);
  document.getElementById('data-load-error').hidden = !resourceStore.hasErrors();
}
registerFeatureReset('data-resources', () => resourceStore?.reset());

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
