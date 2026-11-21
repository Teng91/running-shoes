// Compatibility bridge: native ownership/policy, legacy feature cache adapters.
let resourceStore = null;
// Native owner of the core account data (SPEC-095); created before any data arrives.
let coreDataStore = null;

async function initializeDataResources() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  const { createResourceStore } = await import('./runtime/resource-store.mjs?v=' + encodeURIComponent(version));
  const { createCoreDataStore } = await import('./runtime/core-data.mjs?v=' + encodeURIComponent(version));
  useCoreDataStore(createCoreDataStore());
  resourceStore = createResourceStore({ session: { capture: captureAuthSession, current: isCurrentAuthSession } });
  registerResourceCaches();
}

// Installs the store whose read-only view every script reads as `coreData`.
function useCoreDataStore(store) {
  coreDataStore = store;
  coreData = store.view;
}

// The only way data enters the core store (SPEC-094/095): a loaded resource becomes
// exactly the fields runtime/core-data.mjs returns for it.
function applyCoreResource(resource, value) {
  // Only monthly history chooses the shown year.
  const options = resource === 'monthly' ? { selectedYear, currentYear: appCalendarDate().year } : {};
  const patch = coreDataStore.apply(resource, value, options);
  if ('selectedYear' in patch) selectedYear = patch.selectedYear;
  return patch;
}

registerFeatureReset('dashboard-data', () => coreDataStore?.reset());

function registerResourceCaches() {
  resourceStore.registerCache('spending', () => {
    applyCoreResource('spending', null); spendingLoadRequestId++; spendingLoadPending = false;
  });
  resourceStore.registerCache('goal', () => {
    goalProgressRequestId++; resourceStore.invalidate(['goal-progress', 'training-trends']);
  });
  resourceStore.registerCache('annual', () => {
    runController.state.annualRequest++;
    resourceStore.invalidate(['annual-summary', 'training-trends', 'shoe-timeline', 'pace-analysis', 'race-readiness', 'run-totals']);
  });
  resourceStore.registerCache('dashboard', () => {
    dashboardAnalyticsRequest++;
    resourceStore.invalidate(['dashboard-analytics', 'shoe-timeline', 'home-summary', 'year-review', 'shoe-distance-mix', 'run-totals']);
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
