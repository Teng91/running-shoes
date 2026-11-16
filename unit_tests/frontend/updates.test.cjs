// SPEC-059: apply a new version by itself at safe moments, and keep AI turns across reloads.
const { test, assert, vm, extract, htmlSource, source } = require('./helpers.cjs');

const constant = name => source.match(new RegExp(`const ${name} = [^\\n]+`))[0];
const MINUTE = 60 * 1000;

function nodes() {
  return new Proxy({}, { get: (target, id) => target[id] ||= {
    id, value: '', textContent: '', hidden: true, disabled: false,
    style: { display: 'none' }, querySelectorAll: () => [],
  } });
}

function updateContext({ version = 'v1', storage = new Map(), globals = {} } = {}) {
  const elements = nodes(), documentListeners = {}, timers = [], worker = {};
  let reloads = 0, modalOpen = false;
  const page = {
    visibilityState: 'visible', readyState: 'loading',
    querySelector: selector => (selector === 'meta[name="app-asset-version"]' ? { content: version }
      : selector === '.modal-overlay.active' && modalOpen ? {} : null),
    getElementById: id => elements[id],
    addEventListener: (name, fn) => { documentListeners[name] = fn; },
  };
  const clock = { now: 1_000_000 };
  const context = vm.createContext({
    document: page, console,
    navigator: { serviceWorker: { addEventListener: (name, fn) => { worker[name] = fn; } } },
    window: { addEventListener() {}, location: { reload: () => { reloads += 1; } } },
    sessionStorage: {
      getItem: key => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: key => storage.delete(key),
    },
    setInterval() {}, setTimeout: (fn, ms) => timers.push({ fn, ms }), clearTimeout() {},
    Date: { now: () => clock.now }, ...globals,
  });
  vm.runInContext([constant('APP_UPDATE_ATTEMPT_KEY'), ...['initializeAppUpdates', 'appUpdateBusy',
    'readAppUpdateAttempt', 'writeAppUpdateAttempt', 'showAppUpdate', 'applyAppUpdate'].map(extract)].join('\n'), context);
  context.initializeAppUpdates();
  return {
    context, elements, storage, timers, clock,
    get reloads() { return reloads; },
    deploy: next => worker.message({ data: { type: 'SHELL_VERSION', version: next } }),
    input: (kind = 'keydown') => { clock.now += 1000; documentListeners[kind](); },
    setVisibility: state => { page.visibilityState = state; clock.now += 1000; documentListeners.visibilitychange(); },
    setModal: value => { modalOpen = value; },
    nextTimer: () => timers.at(-1).fn(),
  };
}

test('SPEC-059 an untouched, backgrounded or idle app switches to the new version by itself', () => {
  // Just opened or just returned: nothing typed or clicked yet, so the reload happens at once.
  const fresh = updateContext();
  fresh.deploy('v1');
  assert.equal(fresh.reloads, 0, 'the same shell is not an update');
  fresh.deploy('v2');
  assert.equal(fresh.reloads, 1);
  assert.equal(fresh.storage.get('app-update-attempt'), 'v2');

  // In use: only the prompt, then the switch happens when the app goes to the background.
  const active = updateContext();
  active.input();
  active.deploy('v2');
  assert.equal(active.reloads, 0, 'a visible app in use is never reloaded under the user');
  assert.equal(active.elements['app-update-notice'].hidden, false);
  assert.equal(active.elements['app-update-title'].textContent, '有新版本 vv2');
  assert.equal(active.timers.at(-1).ms, MINUTE, 'the update is retried every minute');
  active.setVisibility('hidden');
  assert.equal(active.reloads, 1);

  // Returning to the foreground counts as untouched until the next input.
  const returning = updateContext({ globals: { agentController: {} } });
  returning.input('pointerdown');
  returning.deploy('v2');
  returning.setVisibility('hidden');
  assert.equal(returning.reloads, 0, 'an answer still streaming keeps the page');
  returning.context.agentController = null;
  returning.setVisibility('visible');
  assert.equal(returning.reloads, 1);

  // Left open on a screen: five minutes without input are enough.
  const idle = updateContext();
  idle.input('pointerdown');
  idle.deploy('v2');
  idle.clock.now += 4 * MINUTE; idle.nextTimer();
  assert.equal(idle.reloads, 0);
  idle.clock.now += MINUTE; idle.nextTimer();
  assert.equal(idle.reloads, 1);
});

test('SPEC-059 work in progress postpones the automatic update until it is safe', () => {
  const cases = [
    ['AI answer streaming', { agentController: {} }, ctx => { ctx.context.agentController = null; }],
    ['report generating', { reportGenerationController: {} }, ctx => { ctx.context.reportGenerationController = null; }],
    ['request in flight', { activeHttpRequests: new Set([{}]) }, ctx => ctx.context.activeHttpRequests.clear()],
    ['inline edit open', { inlineEditors: new Map([['shoe-table', {}]]) }, ctx => ctx.context.inlineEditors.clear()],
    ['dialog open', {}, ctx => ctx.setModal(false), ctx => ctx.setModal(true)],
    ['unsent AI text', {}, ctx => { ctx.elements['agent-input'].value = ''; }, ctx => { ctx.elements['agent-input'].value = '我的鞋'; }],
    ['typed sign-in form', {}, ctx => { ctx.elements['auth-view'].querySelectorAll = () => [{ value: '' }]; },
      ctx => { ctx.elements['auth-view'].style.display = ''; ctx.elements['auth-view'].querySelectorAll = () => [{ value: 'joy' }]; }],
  ];
  for (const [label, globals, finish, start = () => {}] of cases) {
    const ctx = updateContext({ globals });
    start(ctx);
    ctx.deploy('v2');
    ctx.setVisibility('hidden');
    assert.equal(ctx.reloads, 0, `${label} postpones the update`);
    finish(ctx);
    ctx.nextTimer();
    assert.equal(ctx.reloads, 1, `${label}: the next check applies the update`);
  }
});

test('SPEC-059 an automatic reload that missed the new version falls back to the prompt', () => {
  const storage = new Map([['app-update-attempt', 'v2']]);
  const ctx = updateContext({ storage });
  ctx.deploy('v2');
  ctx.setVisibility('hidden');
  assert.equal(ctx.reloads, 0, 'the same version is not retried in a loop');
  assert.equal(ctx.elements['app-update-notice'].hidden, false, 'the prompt stays available');
  ctx.context.applyAppUpdate();
  assert.equal(ctx.reloads, 1, 'the manual update still works');
  // A later deployment is a new attempt.
  const later = updateContext({ storage: new Map([['app-update-attempt', 'v2']]) });
  later.deploy('v3');
  assert.equal(later.reloads, 1);
  // Reaching the attempted version clears the record.
  const arrived = updateContext({ version: 'v2', storage: new Map([['app-update-attempt', 'v2']]) });
  assert.equal(arrived.storage.has('app-update-attempt'), false);
  assert.match(htmlSource, /App 閒置或切到背景時會自動更新；表單草稿與 AI 對話都會保留/);
});

test('SPEC-059 completed AI turns survive a reload for the same account only', () => {
  const storage = new Map();
  const element = () => ({ className: '', textContent: '', innerHTML: '', children: [], appendChild(child) { this.children.push(child); } });
  const container = { ...element(), scrollTop: 0, scrollHeight: 10 };
  const context = vm.createContext({
    document: { getElementById: id => (id === 'agent-messages' ? container : null), createElement: element },
    sessionStorage: {
      getItem: key => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: key => storage.delete(key),
    },
    renderMarkdown: text => `<p>${text}</p>`,
  });
  vm.runInContext(`let agentHistory = []; let currentUser = 'joy';\n${constant('AGENT_CHAT_STORAGE_KEY')}\n${constant('AGENT_CHAT_STORED_TURNS')}\n`
    + ['saveAgentChat', 'restoreAgentChat', 'addAgentMessage'].map(extract).join('\n'), context);
  vm.runInContext(`agentHistory = [{ role: 'user', content: '<b>今年跑多少</b>' }, { role: 'assistant', content: '**1200 km**' }]`, context);
  context.saveAgentChat();
  assert.deepEqual(JSON.parse(storage.get('agent-chat')).user, 'joy');

  vm.runInContext('agentHistory = []', context);
  context.restoreAgentChat();
  assert.equal(vm.runInContext('agentHistory.length', context), 2, 'the next question continues the same context');
  const [question, answer] = container.children;
  assert.equal(question.className, 'agent-message user');
  assert.equal(question.children[0].textContent, '<b>今年跑多少</b>', 'questions stay plain text');
  assert.equal(answer.className, 'agent-message bot');
  assert.equal(answer.children[0].innerHTML, '<p>**1200 km**</p>', 'answers use the safe Markdown renderer');

  // Another account in this tab, malformed data, or a reset conversation restores nothing.
  container.children = [];
  vm.runInContext("agentHistory = []; currentUser = 'other'", context);
  context.restoreAgentChat();
  assert.equal(container.children.length, 0);
  assert.equal(storage.has('agent-chat'), false, 'a foreign conversation is discarded');
  storage.set('agent-chat', '{bad json');
  vm.runInContext("currentUser = 'joy'", context);
  context.restoreAgentChat();
  assert.equal(container.children.length, 0);
  vm.runInContext("agentHistory = [{ role: 'user', content: 'x' }]", context);
  context.saveAgentChat();
  vm.runInContext('agentHistory = []', context);
  context.saveAgentChat();
  assert.equal(storage.has('agent-chat'), false, 'resetting the conversation removes it');

  assert.match(extract('resetAgentChat'), /agentHistory = \[\];[\s\S]*saveAgentChat\(\);/);
  assert.match(extract('sendAgentMessage'), /if \(result\.completed\) \{\s*agentHistory = [^\n]+\n\s*saveAgentChat\(\);/);
  assert.equal(extract('init').match(/showAppView\(\{ keepBoot: true \}\);\s*restoreAgentChat\(\);/g).length, 2);
  assert.doesNotMatch(extract('saveAgentChat') + extract('restoreAgentChat'), /localStorage|indexedDB/);
});
