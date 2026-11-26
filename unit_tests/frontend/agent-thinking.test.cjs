// SPEC-086: the model's reasoning streams into a block above the answer.
const nodeVm = require('node:vm');
const { test, assert, readText, extract } = require('./helpers.cjs');

class FakeText {
  constructor(data) { this.data = data; this.parentNode = null; }
  appendData(more) { this.data += more; }
  get textContent() { return this.data; }
  remove() { this.parentNode?.removeChild(this); }
}

class FakeElement {
  constructor(tagName) {
    Object.assign(this, { tagName, childNodes: [], parentNode: null, className: '', dataset: {},
      open: false, disabled: false, value: '', title: '', scrollTop: 0, scrollHeight: 120, html: '' });
  }
  get children() { return this.childNodes.filter(node => node instanceof FakeElement); }
  get classList() {
    const names = () => this.className.split(/\s+/).filter(Boolean);
    return {
      add: name => { if (!names().includes(name)) this.className = [...names(), name].join(' '); },
      remove: name => { this.className = names().filter(item => item !== name).join(' '); },
      contains: name => names().includes(name),
    };
  }
  appendChild(node) { return this.insertBefore(node, null); }
  insertBefore(node, before) {
    node.parentNode?.removeChild(node);
    const index = before ? this.childNodes.indexOf(before) : -1;
    this.childNodes.splice(index < 0 ? this.childNodes.length : index, 0, node);
    node.parentNode = this;
    return node;
  }
  removeChild(node) {
    this.childNodes.splice(this.childNodes.indexOf(node), 1);
    node.parentNode = null;
  }
  remove() { this.parentNode?.removeChild(this); }
  get nextElementSibling() {
    const siblings = this.parentNode?.children || [];
    return siblings[siblings.indexOf(this) + 1] || null;
  }
  get textContent() { return this.childNodes.map(node => node.textContent).join(''); }
  set textContent(value) {
    this.childNodes.forEach(node => { node.parentNode = null; });
    this.childNodes = [];
    this.html = '';
    if (value) this.appendChild(new FakeText(String(value)));
  }
  get innerHTML() { return this.html; }
  set innerHTML(value) {
    this.textContent = '';
    // Enough markup support for the tool rows: flat <span class="…">text</span>.
    for (const [, className, text] of String(value).matchAll(/<span class="([\w-]+)">(.*?)<\/span>/g)) {
      const span = this.appendChild(new FakeElement('span'));
      span.className = className;
      span.textContent = text;
    }
    this.html = String(value);
  }
  matches(selector) {
    const [, classes = '', negated = ''] = /^((?:\.[\w-]+)*)((?::not\(\.[\w-]+\))*)$/.exec(selector) || [];
    const required = classes.split('.').filter(Boolean);
    const excluded = [...negated.matchAll(/\.([\w-]+)/g)].map(match => match[1]);
    return required.every(name => this.classList.contains(name)) && !excluded.some(name => this.classList.contains(name));
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function agentContext() {
  const elements = {
    'agent-messages': new FakeElement('div'), 'agent-input': new FakeElement('textarea'),
    'agent-send-btn': new FakeElement('button'), 'agent-model': new FakeElement('select'),
  };
  elements['agent-input'].value = '幫我分析跑鞋';
  elements['agent-model'].value = 'vendor/model:free';
  const clock = { now: 1_000_000 };
  const timers = new Map();
  const saved = new Map();
  const encoder = new TextEncoder();
  let streamController;
  const requests = [];
  const context = nodeVm.createContext({
    DOMException, TextDecoder, AbortController, URL, console,
    Date: { now: () => clock.now },
    setInterval: callback => { const id = timers.size + 1; timers.set(id, callback); return id; },
    clearInterval: id => timers.delete(id),
    document: {
      getElementById: id => elements[id],
      createElement: tag => new FakeElement(tag),
      createTextNode: data => new FakeText(data),
      querySelectorAll: selector => elements['agent-messages'].querySelectorAll(selector),
    },
    sessionStorage: { setItem: (key, value) => saved.set(key, value), removeItem: key => saved.delete(key), getItem: () => null },
    authenticatedResponses: new WeakMap(),
    requireAuthSession: session => { if (!session?.current) throw new DOMException('stale', 'AbortError'); },
    readAuthenticatedError: async response => response.json(),
    captureAuthSession: () => ({ current: true, account: 'aid-runner' }), isCurrentAuthSession: session => session.current,
    registerFeatureReset() {}, registerUiActions() {}, registerBusyCheck() {}, onAuthView() {}, renderMarkdown: text => `<p>${text}</p>`, esc: text => String(text),
    API_BASE: '/api', authToken: 'synthetic-token', currentUser: 'runner',
  });
  context.authenticatedFetch = async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    const body = new ReadableStream({ start(controller) { streamController = controller; } });
    const response = new Response(body, { headers: { 'content-type': 'text/event-stream' } });
    context.authenticatedResponses.set(response, { current: true });
    return response;
  };
  nodeVm.runInContext(extract('readJsonEventStream'), context);
  nodeVm.runInContext(readText('frontend/app-agent.js'), context);
  const settle = async () => { for (let i = 0; i < 6; i += 1) await new Promise(resolve => setImmediate(resolve)); };
  const send = async (...events) => {
    for (const event of events) streamController.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
    await settle();
  };
  const tick = seconds => { clock.now += seconds * 1000; [...timers.values()].forEach(callback => callback()); };
  const container = elements['agent-messages'];
  const parts = () => container.children.map(node => node.className.split(' ')[0]);
  const bubble = () => container.querySelector('.agent-message.bot').querySelector('.agent-msg-content');
  const blocks = () => container.querySelectorAll('.agent-reasoning');
  const blockText = block => block.querySelector('.agent-reasoning-text').textContent;
  const summary = block => block.childNodes[0].textContent;
  return { context, settle, send, tick, timers, saved, requests, parts, bubble, blocks, blockText, summary };
}

test('SPEC-086 reasoning streams live above the answer, folds when it answers and is never kept', async () => {
  const view = agentContext();
  const finished = view.context.sendAgentMessage();
  await view.settle();
  assert.equal(view.bubble().textContent, '思考中…', 'an empty answer bubble shows that the model is working');
  assert.equal(view.timers.size, 1);
  view.tick(3);
  assert.equal(view.bubble().textContent, '思考中… 3 秒');

  await view.send({ type: 'thinking', text: '先看鞋況，' }, { type: 'thinking', text: '<b>再</b>整理。' });
  const [block] = view.blocks();
  assert.deepEqual(view.parts(), ['agent-message', 'agent-reasoning', 'agent-message'], 'the block sits between the question and the answer');
  assert.equal(block.open, true);
  assert.equal(view.blockText(block), '先看鞋況，<b>再</b>整理。', 'reasoning stays literal text');
  assert.equal(block.querySelector('.agent-reasoning-text').html, '');
  assert.equal(view.summary(block), '💭 思考中… 3 秒', 'the block continues the seconds of the waiting bubble');
  assert.equal(view.bubble().textContent, '', 'the live block shows the time instead of the bubble');
  view.tick(4);
  assert.equal(view.summary(block), '💭 思考中… 7 秒');

  await view.send({ type: 'token', text: '鞋況' });
  assert.equal(block.open, false, 'the first answer token folds the reasoning');
  assert.equal(view.summary(block), '💭 已思考 7 秒');
  assert.equal(view.bubble().textContent, '鞋況');
  await view.send({ type: 'token', text: '良好。' }, { type: 'done' });
  await finished;

  assert.equal(view.bubble().innerHTML, '<p>鞋況良好。</p>');
  assert.equal(view.timers.size, 0, 'the waiting timer stops with the stream');
  assert.equal(view.blocks().length, 1);
  const history = nodeVm.runInContext('agentHistory', view.context);
  assert.deepEqual(Array.from(history, turn => turn.content), ['幫我分析跑鞋', '鞋況良好。']);
  assert.doesNotMatch(view.saved.get('agent-chat'), /先看鞋況/, 'reasoning is not saved with the conversation');
});

test('SPEC-086 each model round gets its own block and the bubble waits again between rounds', async () => {
  const view = agentContext();
  const finished = view.context.sendAgentMessage();
  await view.settle();
  await view.send({ type: 'thinking', text: '需要鞋櫃資料' });
  view.tick(2);
  await view.send(
    { type: 'reasoning_start', text: '' },
    { type: 'tool', name: 'list_my_shoes', args: {} },
  );
  const [first] = view.blocks();
  assert.equal(first.open, false, 'calling a tool ends the first round of thinking');
  assert.equal(view.summary(first), '💭 已思考 2 秒');

  await view.send({ type: 'tool_done', name: 'list_my_shoes', ok: true });
  view.tick(5);
  assert.equal(view.bubble().textContent, '思考中… 5 秒', 'the bubble counts from the end of the tool round');

  await view.send({ type: 'thinking', text: '整理鞋況' });
  view.tick(1);
  await view.send({ type: 'token', text: '建議輪替。' }, { type: 'done' });
  await finished;

  assert.deepEqual(view.parts(), ['agent-message', 'agent-reasoning', 'agent-tools', 'agent-reasoning', 'agent-message', 'agent-retry-btn']);
  const [, second] = view.blocks();
  assert.equal(view.blockText(second), '整理鞋況');
  assert.equal(view.summary(second), '💭 已思考 6 秒', 'the second round counts from the end of the tool, not the first reasoning');
  assert.equal(view.bubble().innerHTML.startsWith('<p>建議輪替。</p>'), true);
});

test('SPEC-086 a long wait before a short burst of reasoning still reports the whole thinking time', async () => {
  // Regression: a model that thought for 30-odd seconds, then sent its reasoning in
  // one burst right before calling a tool, used to fold into「已思考 1 秒」.
  const view = agentContext();
  const finished = view.context.sendAgentMessage();
  await view.settle();
  view.tick(31);
  await view.send(
    { type: 'thinking', text: '先查鞋櫃' },
    { type: 'reasoning_start', text: '' },
    { type: 'tool', name: 'list_my_shoes', args: {} },
    { type: 'tool_done', name: 'list_my_shoes', ok: true },
  );
  view.tick(18);
  await view.send({ type: 'thinking', text: '整理' }, { type: 'token', text: '完成。' }, { type: 'done' });
  await finished;

  const [first, second] = view.blocks();
  assert.equal(view.summary(first), '💭 已思考 31 秒');
  assert.equal(view.summary(second), '💭 已思考 18 秒');
});

test('SPEC-086 a model that never thinks out loud still shows the waiting seconds, then the answer', async () => {
  const view = agentContext();
  const finished = view.context.sendAgentMessage();
  await view.settle();
  view.tick(12);
  assert.equal(view.bubble().textContent, '思考中… 12 秒');
  await view.send({ type: 'token', text: '你好！' }, { type: 'done' });
  await finished;
  assert.equal(view.blocks().length, 0);
  assert.equal(view.bubble().innerHTML.startsWith('<p>你好！</p>'), true);
  assert.equal(view.timers.size, 0);
});
