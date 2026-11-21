// Compatibility bridge: native ownership/policy, legacy feature cache adapters.
let resourceStore = null;
// Native core-data rules (SPEC-094); loaded before any data arrives.
let coreDataRules = null;

async function initializeDataResources() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  const { createResourceStore } = await import('./runtime/resource-store.mjs?v=' + encodeURIComponent(version));
  coreDataRules = await import('./runtime/core-data.mjs?v=' + encodeURIComponent(version));
  resourceStore = createResourceStore({ session: { capture: captureAuthSession, current: isCurrentAuthSession } });
  registerResourceCaches();
}

// The only writer of the core data globals declared in app-state.js (SPEC-094): a loaded
// resource becomes exactly the fields runtime/core-data.mjs returns for it.
function applyCoreResource(resource, value) {
  // Only monthly history chooses the shown year.
  const options = resource === 'monthly' ? { selectedYear, currentYear: appCalendarDate().year } : {};
  const patch = coreDataRules.coreDataPatch(resource, value, options);
  assignCoreFields(patch);
  return patch;
}

function assignCoreFields(patch) {
  if ('shoes' in patch) shoes = patch.shoes;
  if ('retiredShoes' in patch) retiredShoes = patch.retiredShoes;
  if ('monthlyMileages' in patch) monthlyMileages = patch.monthlyMileages;
  if ('runningGoal' in patch) runningGoal = patch.runningGoal;
  if ('stravaImports' in patch) stravaImports = patch.stravaImports;
  if ('spendingSummary' in patch) spendingSummary = patch.spendingSummary;
  if ('monthlySpending' in patch) monthlySpending = patch.monthlySpending;
  if ('selectedYear' in patch) selectedYear = patch.selectedYear;
}

function resetCoreData() {
  assignCoreFields(coreDataRules.coreDataDefaults());
}
registerFeatureReset('dashboard-data', () => { if (coreDataRules) resetCoreData(); });

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
