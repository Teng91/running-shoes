// Compatibility bridge: native ownership/policy, legacy feature cache adapters.
let resourceStore = null;
// Native owner of the core account data (SPEC-095); created before any data arrives.
let coreDataStore = null;

async function initializeDataResources() {
  const version = document.querySelector('meta[name="app-asset-version"]').content;
  // SPEC-137: independent modules load together (the page preloads every module).
  const [{ createResourceStore }, { createCoreDataStore }] = await Promise.all([
    import('./runtime/resource-store.mjs?v=' + encodeURIComponent(version)),
    import('./runtime/core-data.mjs?v=' + encodeURIComponent(version)),
  ]);
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

// SPEC-106: a feature registers what invalidating one of its caches resets, when it loads;
// the hooks are installed once the store exists.
const resourceCacheHooks = [];

function registerResourceCache(name, onInvalidate) {
  resourceCacheHooks.push([name, onInvalidate]);
}

function registerResourceCaches() {
  for (const [name, onInvalidate] of resourceCacheHooks) resourceStore.registerCache(name, onInvalidate);
  resourceStore.registerCache('annual', () => {
    runController.state.annualRequest++;
    resourceStore.invalidate(['annual-summary', 'training-trends', 'shoe-timeline', 'pace-analysis', 'race-readiness', 'run-totals']);
  });
  resourceStore.registerCache('dashboard', () => {
    dashboardAnalyticsRequest++;
    resourceStore.invalidate(['dashboard-analytics', 'shoe-timeline', 'home-summary', 'year-review', 'shoe-distance-mix', 'run-totals', 'personal-bests']);
  });
}

function invalidateDataResources(resources) {
  resourceStore.invalidate(resources);
  document.getElementById('data-load-error').hidden = !resourceStore.hasErrors();
}
registerFeatureReset('data-resources', () => resourceStore?.reset());

