// Run with: node --test unit_tests/frontend_regressions.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let createRunController, createFormOperations, matchesSnapshot, createFormDraft, createResourceStore, createCoreDataStore;
require('node:test').before(async () => {
  ({ createRunController } = await import('../../frontend/runtime/run-controller.mjs'));
  ({ createFormOperations, matchesSnapshot, createFormDraft } = await import('../../frontend/runtime/form-operations.mjs'));
  ({ createResourceStore } = await import('../../frontend/runtime/resource-store.mjs'));
  ({ createCoreDataStore } = await import('../../frontend/runtime/core-data.mjs'));
});

const CORE_FIELDS = ['shoes', 'retiredShoes', 'monthlyMileages', 'runningGoal', 'stravaImports', 'spendingSummary', 'monthlySpending'];

// SPEC-095: core data fixtures (passed like globals, e.g. { shoes: [...] }) seed a real store;
// code reads them through context.coreData and writes through the real bridge.
function splitCoreFixtures(globals) {
  const core = {}, rest = {};
  for (const [name, value] of Object.entries(globals)) (CORE_FIELDS.includes(name) ? core : rest)[name] = value;
  return { core, rest };
}

// Replaces the given fields and keeps the rest, like a test fixture changing one resource.
function seedCoreData(context, fields) {
  const store = createCoreDataStore({ ...(context.coreData || {}), ...fields });
  context.coreDataStore = store;
  context.coreData = store.view;
  return store.view;
}

function featureContext(globals = {}) {
  const { core, rest } = splitCoreFixtures(globals);
  const context = vm.createContext({ structuredClone, formSnapshotMatches: matchesSnapshot,
    dashboardAnalyticsCache: new Map(), dashboardAnalyticsRequest: 0, inlineEditors: new Map(), inlineTableRows: new Map(),
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true,
    // SPEC-101: a whole feature script registers its panel hooks on load; panelWiring() replaces these.
    registerPanel() {}, registerResourceReader() {}, registerDataHooks() {}, workspaceDataArrived() {},
    // SPEC-108: whole scripts register their sign-in and session-expiry hooks on load.
    onAuthView() {},
    // SPEC-113: whole scripts register their UI actions on load.
    registerUiActions() {},
    getSelectedCategories: () => [], ...rest });
  seedCoreData(context, core);
  context.seedCoreData = fields => seedCoreData(context, fields);
  const drafts = new Map();
  context.getFormDraft = name => {
    if (!drafts.has(name)) drafts.set(name, createFormDraft());
    return drafts.get(name);
  };
  context.resourceStore = createResourceStore({ session: {
    capture: () => context.captureAuthSession(), current: value => context.isCurrentAuthSession(value),
  } });
  const owners = new Map();
  context.getFormOperations = name => {
    if (!owners.has(name)) owners.set(name, createFormOperations({
      capture: () => context.captureAuthSession(), current: value => context.isCurrentAuthSession(value),
    }));
    return owners.get(name);
  };
  vm.runInContext(['applyCoreResource', 'beginInlineEdit', 'finishInlineEdit', 'preserveInlineTable', 'readForm', 'matchesForm', 'shoeLabel', 'invalidateDataResources', 'refreshCoreData', 'registerResourceCaches', 'goalFormValues', 'goalStartYearOptions', 'setGoalField', 'setGoalSettingsOpen', 'updateGoalYearlyHint', 'prepareGoalForm', 'formatRunDuration', 'formatPace'].map(extract).join('\n'), context);
  // SPEC-060 pace helpers are shared by run creation, editing and rendering.
  vm.runInContext(source.match(/const RUN_PACE_MIN_SECONDS = \d+;\s*const RUN_PACE_MAX_SECONDS = \d+;/)[0] + '\n'
    + ['parseRunDuration', 'groupDurationDigits', 'formatDurationInput', 'plausibleRunPace', 'updateRunPacePreview', 'readRunDuration'].map(extract).join('\n'), context);
  // SPEC-096 activity types: constants and the form/label helpers shared by run features.
  vm.runInContext(source.match(/const RUN_ACTIVITY_TYPES = [^\n]+\n(?:const RUN_[A-Z_]+ = [^\n]+\n){3}/)[0]
    + ['lastActivityTypeForShoe', 'runActivityLabel', 'updateRunActivityHint'].map(extract).join('\n'), context);
  // SPEC-093: calendar days come from the service's fixed zone, shared by every feature.
  vm.runInContext(source.match(/const APP_UTC_OFFSET_MINUTES = \d+;/)[0] + '\n' + extract('appCalendarDate'), context);
  // SPEC-106: features register their cache hooks when they load; install them like initializeDataResources().
  vm.runInContext(`const resourceCacheHooks = [];\n${extract('registerResourceCache')}\n${featureRegistrations(/^registerResourceCache\(/gm)}`, context);
  context.registerResourceCaches();
  // SPEC-112: what a test passes in wins over the shared helpers installed above (for example a
  // prepareGoalForm or updateRunActivityHint spy), so a test never has to re-assign it afterwards.
  for (const [name, value] of Object.entries(rest)) {
    if (context[name] !== value) context[name] = value;
  }
  return context;
}

function runContext(globals) {
  const context = featureContext(globals);
  let nextKey = 0;
  context.runController = createRunController({
    transport: { post: (...args) => context.apiPost(...args), put: (...args) => context.apiPut(...args), delete: (...args) => context.apiDelete(...args) },
    session: { capture: () => context.captureAuthSession?.() || {}, current: value => context.isCurrentAuthSession?.(value) ?? true },
    newKey: () => 'synthetic-operation-' + (++nextKey),
  });
  const names = { runs: 'rows', runSummary: 'summary', runPageOffset: 'offset', runPageHasMore: 'hasMore',
    runDayFilter: 'day', yearlyRunsCache: 'annualCache', runListRequestId: 'listRequest', stackedRunsRequestId: 'annualRequest' };
  for (const [legacy, owned] of Object.entries(names)) {
    if (legacy in globals) context.runController.state[owned] = globals[legacy];
  }
  return context;
}
// Git may check sources out with CRLF on Windows; browsers normalize HTML line
// endings and CI uses LF, so assertions always see LF.
const readText = file => fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
const htmlSource = readText('frontend/index.html');
const scriptPaths = JSON.parse(fs.readFileSync('frontend/assets.json', 'utf8')).scripts.map(file => 'frontend/' + file);
const scriptSource = scriptPaths.map(readText).join('\n');
const styleSource = readText('frontend/styles.css');
const source = `${htmlSource}\n${styleSource}\n${scriptSource}`;


function authOperationContext() {
  const controls = [{ disabled: false }];
  const elements = new Proxy({}, { get: (target, id) => target[id] ||= { value: '', style: {}, textContent: '' } });
  const state = { account: null, hides: 0, writes: [] };
  const context = vm.createContext({ AbortController,
    document: { getElementById: id => elements[id], querySelectorAll: () => controls },
    API_BASE: '/api', translateError: value => value,
    hideAuthError() {}, hideRegError() {},
    showAuthError: text => state.writes.push(text), showRegError: text => state.writes.push(text),
    showAppBoot() {}, hideAppBoot: () => state.hides++,
    resetAuthInputs() {}, resetAgentChat() {}, resetAppLayout() {}, showAppView() {}, showLoginView() {},
    loadAgentModels() {}, loadData: async () => {},
    authRequest: (...args) => context.fetch(...args),
  });
  vm.runInContext('let authGeneration = 0, authOperation = null, registrationMode = null;\n' + [
    'setAuthControlsDisabled', 'cancelAuthOperation', 'beginAuthOperation', 'isCurrentAuthOperation',
    'finishAuthOperation', 'handleLogin', 'handleRegister',
  ].map(extract).join('\n'), context);
  context.captureAuthSession = () => ({ generation: vm.runInContext('authGeneration', context) });
  context.isCurrentAuthSession = session => session.generation === vm.runInContext('authGeneration', context);
  context.clearAuth = () => { context.cancelAuthOperation(); vm.runInContext('authGeneration++', context); state.account = null; };
  context.setAuth = (_, username) => { context.clearAuth(); state.account = username; };
  return { context, elements, controls, state };
}

function streamContext() {
  const context = vm.createContext({ DOMException, TextDecoder,
    authenticatedResponses: new WeakMap(),
    requireAuthSession: session => { if (!session?.current) throw new DOMException('stale', 'AbortError'); },
    readAuthenticatedError: async response => response.json(),
  });
  vm.runInContext(extract('readJsonEventStream'), context);
  context.bind = response => { context.authenticatedResponses.set(response, { current: true }); return response; };
  return context;
}

function editContext() {
  const elements = new Proxy({}, { get: (target, id) => target[id] ||= {
    value: '', style: {}, classList: { add() {}, remove() {} },
  } });
  const context = runContext({ document: { getElementById: id => elements[id] },
    captureAuthSession: () => ({ current: true }), isCurrentAuthSession: session => session.current,
    refreshDateLimits() {}, populateRunShoeSelects() {}, localDateISO: () => '2026-10-19', loadData: async () => {},
    translateError: value => value, confirm: () => true, alert() {},
  });
  vm.runInContext(['openRunModal', 'closeRunModal', 'saveRun', 'deleteEditingRun'].map(extract).join('\n'), context);
  return { context, elements };
}

function tableHeaders(tbodyId) {
  const beforeBody = htmlSource.slice(0, htmlSource.indexOf(`<tbody id="${tbodyId}"`));
  const header = beforeBody.slice(beforeBody.lastIndexOf('<thead>'));
  return [...header.matchAll(/<th\b[^>]*>(.*?)<\/th>/g)].map(match => match[1]);
}

function extract(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
  return source.slice(start, source.indexOf('\n}', start) + 2);
}

// SPEC-114: report generation is split into named steps; source checks read all of them.
function reportGenerationSource() {
  return ['generateReport', 'startReportGeneration', 'isCurrentReport', 'scheduleReportMarkdown', 'handleReportEvent',
    'finishReportStream', 'showReportFailure', 'endReportGeneration'].map(extract).join('\n');
}

// SPEC-101: the top-level register*() statements of every script, in assets.json order.
function featureRegistrations(pattern = /^register(?:Panel|ResourceReader|DataHooks)\(/gm) {
  const statements = [];
  for (const file of scriptPaths) {
    const text = readText(file);
    for (const match of text.matchAll(pattern)) {
      let depth = 0, end = match.index;
      for (; end < text.length; end++) {
        if (text[end] === '(') depth++;
        else if (text[end] === ')' && --depth === 0) break;
      }
      statements.push(text.slice(match.index, end + 1) + ';');
    }
  }
  return statements.join('\n');
}

// The shell's panel registry plus the hooks the feature scripts register when they load, so a
// test drives renderActivePanel/switchTab/loadData through the real wiring.
function panelWiring() {
  return `const panelHooks = new Map(), resourceReaders = new Map(), dataHooks = [];
    ${['registerPanel', 'registerResourceReader', 'registerDataHooks', 'runsResourceReader'].map(extract).join('\n')}
    ${featureRegistrations()}`;
}

function transportContext() {
  const context = vm.createContext({
    // SPEC-108: a real event target, so a 401 reaches the sign-out listener like in the page.
    window: Object.assign(new EventTarget(), { location: { origin: 'http://test.local' } }), Event,
    DOMException, FormData, Blob, AbortController, setTimeout, clearTimeout, registerFeatureReset() {},
    clearCalls: 0, loginCalls: 0,
  });
  vm.runInContext(`let authToken = 'A', authGeneration = 1;
    ${extract('authTokenClaims')}
    ${extract('captureAuthSession')}
    ${extract('isCurrentAuthSession')}
    ${extract('requireAuthSession')}
    function clearAuth() { authToken = null; authGeneration++; clearCalls++; }
    function showLoginView() { loginCalls++; }
    window.addEventListener('auth-session-expired', () => { clearAuth(); showLoginView(); });
    function switchSession(token) { authToken = token; authGeneration++; }
    function activeToken() { return authToken; }
    ${fs.readFileSync('frontend/app-api.js', 'utf8')}`, context);
  return context;
}

module.exports = { runContext, test, assert, fs, path, readText, vm: { ...vm, createContext: featureContext }, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, panelWiring, featureRegistrations, reportGenerationSource, transportContext };
