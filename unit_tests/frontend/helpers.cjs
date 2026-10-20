// Run with: node --test unit_tests/frontend_regressions.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
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
  const context = vm.createContext({ document: { getElementById: id => elements[id] },
    captureAuthSession: () => ({ current: true }), isCurrentAuthSession: session => session.current,
    refreshDateLimits() {}, populateRunShoeSelects() {}, populateMonthlyEditSelects(year, month) {
      elements['m-year'].value = year; elements['m-month'].value = month;
    }, localDateISO: () => '2026-10-19', loadData: async () => {},
    translateError: value => value, confirm: () => true, alert() {},
  });
  vm.runInContext(`let editingRun = null, editingMonthly = null;\n` +
    ['openRunModal', 'closeRunModal', 'saveRun', 'deleteEditingRun',
      'editMonthlyMileage', 'closeMonthlyModal', 'saveMonthlyMileage'].map(extract).join('\n'), context);
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
    DOMException, FormData, Blob,
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

module.exports = { test, assert, fs, path, vm, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, transportContext };
