// Run with: node --test unit_tests/frontend_regressions.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let createRunController, createFormOperations, matchesSnapshot, createFormDraft, createResourceStore;
require('node:test').before(async () => {
  ({ createRunController } = await import('../../frontend/runtime/run-controller.mjs'));
  ({ createFormOperations, matchesSnapshot, createFormDraft } = await import('../../frontend/runtime/form-operations.mjs'));
  ({ createResourceStore } = await import('../../frontend/runtime/resource-store.mjs'));
});

function featureContext(globals = {}) {
  const context = vm.createContext({ structuredClone, formSnapshotMatches: matchesSnapshot,
    dashboardAnalyticsCache: new Map(), dashboardAnalyticsRequest: 0, inlineEditors: new Map(), inlineTableRows: new Map(),
    captureAuthSession: () => ({}), isCurrentAuthSession: () => true,
    getSelectedCategories: () => [], monthlyMileages: [], ...globals });
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
  vm.runInContext(['beginInlineEdit', 'finishInlineEdit', 'preserveInlineTable', 'readForm', 'matchesForm', 'shoeLabel', 'invalidateDataResources', 'refreshCoreData', 'registerResourceCaches', 'goalFormValues', 'goalStartYearOptions', 'setGoalField', 'setGoalSettingsOpen', 'updateGoalYearlyHint', 'prepareGoalForm'].map(extract).join('\n'), context);
  context.registerResourceCaches();
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
const htmlSource = fs.readFileSync('frontend/index.html', 'utf8');
const scriptPaths = JSON.parse(fs.readFileSync('frontend/assets.json', 'utf8')).scripts.map(file => 'frontend/' + file);
const scriptSource = scriptPaths.map(path => fs.readFileSync(path, 'utf8')).join('\n');
const styleSource = fs.readFileSync('frontend/styles.css', 'utf8');
const source = `${htmlSource}\n${styleSource}\n${scriptSource}`;


function authOperationContext() {
  const controls = [{ disabled: false }];
  const elements = new Proxy({}, { get: (target, id) => target[id] ||= { value: '', style: {}, textContent: '' } });
  const state = { account: null, hides: 0, writes: [] };
  const context = vm.createContext({ AbortController,
    document: { getElementById: id => elements[id], querySelectorAll: () => controls },
    API_BASE: '/api', translateError: value => value,
    hideAuthError() {}, hideRegError() {}, hideChangeError() {},
    showAuthError: text => state.writes.push(text), showRegError: text => state.writes.push(text),
    showChangeError: text => state.writes.push(text), showAppBoot() {}, hideAppBoot: () => state.hides++,
    resetAuthInputs() {}, resetAgentChat() {}, resetAppLayout() {}, showAppView() {}, showLoginView() {},
    loadAgentModels() {}, loadData: async () => {},
    authRequest: (...args) => context.fetch(...args),
  });
  vm.runInContext('let authGeneration = 0, authOperation = null;\n' + [
    'setAuthControlsDisabled', 'cancelAuthOperation', 'beginAuthOperation', 'isCurrentAuthOperation',
    'finishAuthOperation', 'handleLogin', 'handleRegister', 'handleChangePassword',
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

function transportContext() {
  const context = vm.createContext({
    window: { location: { origin: 'http://test.local' } },
    DOMException, FormData, Blob, AbortController, setTimeout, clearTimeout, registerFeatureReset() {},
    clearCalls: 0, loginCalls: 0,
  });
  vm.runInContext(`let authToken = 'A', authGeneration = 1;
    ${extract('captureAuthSession')}
    ${extract('isCurrentAuthSession')}
    ${extract('requireAuthSession')}
    function clearAuth() { authToken = null; authGeneration++; clearCalls++; }
    function showLoginView() { loginCalls++; }
    function switchSession(token) { authToken = token; authGeneration++; }
    function activeToken() { return authToken; }
    ${fs.readFileSync('frontend/app-api.js', 'utf8')}`, context);
  return context;
}

module.exports = { runContext, test, assert, fs, path, vm: { ...vm, createContext: featureContext }, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, transportContext };
