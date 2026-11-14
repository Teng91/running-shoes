const { test, assert, fs, path, vm, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, transportContext } = require('./helpers.cjs');

test('startup and login show progress until the application is ready', () => {
  assert.match(htmlSource, /id="app-boot"[^>]+role="status"[^>]+aria-live="polite"/);
  assert.match(htmlSource, /id="app-boot-message">正在準備應用程式/);
  assert.match(htmlSource, /id="app-boot-retry"[^>]+hidden>重新載入/);
  assert.ok(htmlSource.indexOf('id="app-boot"') < htmlSource.indexOf('src="/vendor/chart.umd.min.js"'));
  assert.match(htmlSource, /__appBootLegacyPoll/);
  assert.match(htmlSource, /Critical startup UI must not depend[\s\S]+body \{ margin: 0; opacity: 1 !important; \}/);
  assert.match(htmlSource, /id="app-styles" rel="preload" href="\/styles\.css\?v=[^"]+" as="style"/);
  assert.match(htmlSource, /link\.dataset\.ready = 'true';\s+window\.dispatchEvent\(new Event\('appstylesready'\)\);/);
  assert.match(source, /\.app-boot\.is-hidden \{ opacity: 0; visibility: hidden/);
  assert.match(source, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(source, /body \{[^}]*opacity:\s*0/);

  const initSource = extract('init');
  const loginSource = extract('handleLogin');
  assert.match(initSource, /showAppView\(\{ keepBoot: true \}\)[\s\S]+await loadData\(\);[\s\S]+hideAppBoot\(\)/);
  assert.match(loginSource, /showAppBoot\('正在登入並載入資料…'\)[\s\S]+await loadData\(\);[\s\S]+hideAppBoot\(\)/);
  assert.match(source, /showAppBootError\('載入時間比預期久/);
  assert.match(source, /initializeFeatureLifecycle\(\)\.then\(/);
  assert.match(source, /return init\(\);[\s\S]+\.catch\(error =>/);
});

test('successful login and logout clear every authentication field', () => {
  const ids = [
    'login-username', 'login-password',
    'reg-username', 'reg-password', 'reg-password2',
    'change-username', 'change-old-password', 'change-new-password', 'change-new-password2',
  ];
  const elements = Object.fromEntries(ids.map(id => [id, { value: 'previous-user-secret' }]));
  const context = vm.createContext({ document: { getElementById: id => elements[id] } });
  vm.runInContext(`const AUTH_INPUT_IDS = ${JSON.stringify(ids)};\n${extract('resetAuthInputs')}`, context);
  context.resetAuthInputs();
  assert.deepEqual(ids.map(id => elements[id].value), ids.map(() => ''));
  assert.match(extract('clearAuth'), /resetAuthInputs\(\)/);
  assert.match(extract('handleLogin'), /setAuth\(data\.access_token, username\);[\s\S]+resetAuthInputs\(\)/);
  // SPEC-055 supersedes the disabled autocomplete: fields are still cleared on every
  // auth transition, and password managers may fill them on the owner's request.
  assert.match(htmlSource, /id="login-password" type="password" autocomplete="current-password"/);
});

test('mobile page gutters preserve standalone safe-area insets', () => {
  assert.match(source, /padding:\s*calc\(var\(--page-gutter\) \+ env\(safe-area-inset-top\)\)[\s\S]*max\(var\(--page-gutter\), env\(safe-area-inset-right\)\)[\s\S]*max\(var\(--page-gutter\), env\(safe-area-inset-bottom\)\)[\s\S]*max\(var\(--page-gutter\), env\(safe-area-inset-left\)\)/);
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*?\.container \{ --page-gutter: 16px; \}/);
  assert.match(source, /@media \(max-width: 380px\)[\s\S]*?\.container \{ --page-gutter: 12px; \}/);
  assert.doesNotMatch(source, /@media \(max-width: (?:760|380)px\)[\s\S]*?\.container \{ padding:/);
});

test('monthly reports progressively render markdown with document styling', () => {
  assert.match(source, /class="agent-msg-content report-content"/);
  assert.match(source, /\.report-content h2 \{/);
  assert.match(source, /\.report-content blockquote \{/);
  assert.match(source, /scheduleMarkdownRender\(\)/);
  assert.match(source, /content\.classList\.add\('is-streaming'\)/);
});

test('temporary auth connectivity failures preserve the stored session', () => {
  const initSource = source.slice(source.indexOf('async function init()'), source.indexOf('\ninit();'));
  assert.match(initSource, /authenticatedFetch\(API_BASE \+ '\/auth\/me'/);
  assert.match(extract('authenticatedFetch'), /response\.status === 401/);
  assert.match(initSource, /catch \(error\)[\s\S]+showAppView\(\{ keepBoot: true \}\);[\s\S]+await loadData\(\);/);
  assert.doesNotMatch(initSource.match(/catch \(error\) \{[\s\S]+?\n    \}/)[0], /clearAuth\(\)/);
});

test('monthly shoe share draws values in the doughnut without a separate legend', () => {
  assert.doesNotMatch(source, /id="chart-value-legend"/);
  assert.match(source, /id: 'shoeShareLabels'/);
  assert.match(source, /strokeText\(`\$\{km\} km`/);
  assert.match(source, /percentage\.toFixed\(1\)/);
});

test('SPEC-050 the share doughnut shows each active shoe’s 90-day monthly average and their total', () => {
  const configs = {};
  const context = vm.createContext({
    document: { getElementById: id => ({ id }) },
    shoes: [
      { id: 1, brand: 'Mizuno', model: 'Rider', monthly_km: 40, actual_monthly_km_90_days: 30 },
      { id: 2, brand: 'PUMA', model: 'Nitro', monthly_km: 10, actual_monthly_km_90_days: 12.44 },
      // No runs in 90 days (or a record cached before the field existed): no slice, planned km ignored.
      { id: 3, brand: 'Adidas', model: 'Boston', monthly_km: 30 },
    ],
    chartInstances: {}, getThemeColor: (_, fallback) => fallback, shoeColor: () => '#123456',
    progressColor: () => '#123456', fitChartLabel: label => label,
    Chart: function(canvas, config) { configs[canvas.id] = config; this.destroy = () => {}; },
  });
  vm.runInContext(`${['calc', 'fmtDate'].map(extract).join('\n')}\n${fs.readFileSync('frontend/app-shoe-charts.js', 'utf8')}`, context);
  context.renderShoeTimeline = context.renderDistanceMix = () => {};
  context.renderCharts();
  const doughnut = configs['chart-value'];
  assert.deepEqual(doughnut.data.datasets[0].data, [30, 12.44, 0]);
  assert.equal(doughnut.options.plugins.tooltip.callbacks.label({ raw: 12.44 }), '近 90 天月均 12.4 km');
  const written = [];
  const ctx = { save() {}, restore() {}, fillText: text => written.push(text) };
  doughnut.plugins.find(plugin => plugin.id === 'centerText')
    .afterDraw({ ctx, chartArea: { top: 0, bottom: 200, left: 0, right: 200 } });
  assert.deepEqual(written, ['近 90 天月均', '42.4 km']);
  assert.match(htmlSource, /<h3>近 90 天月均里程佔比<\/h3><div class="chart-canvas"><canvas id="chart-value">/);
  assert.doesNotMatch(htmlSource, /月跑量佔比/);
});

test('run shoe distribution shows monthly percentage, mileage, and wear count', () => {
  const legend = {};
  const context = vm.createContext({
    document: { getElementById: () => legend },
    runShoe: id => ({ brand: 'Test', model: `Shoe ${id}` }),
    brandColor: () => '#123456', shoeColor: () => '#123456', esc: value => value,
  });
  vm.runInContext(extract('renderRunShoeChart'), context);
  context.renderRunShoeChart(new Map([
    [1, { km: 15, count: 2 }],
    [2, { km: 5, count: 1 }],
  ]));
  assert.match(legend.innerHTML, /75\.0%<\/span><span class="run-shoe-legend-km">15\.00 km<\/span><span class="run-shoe-legend-count">2 次/);
  assert.match(legend.innerHTML, /25\.0%<\/span><span class="run-shoe-legend-km">5\.00 km<\/span><span class="run-shoe-legend-count">1 次/);
});

test('shoe analytics ignores stale responses after a second open or close', () => {
  const openAnalytics = extract('openShoeAnalytics');
  const closeAnalytics = extract('closeShoeAnalytics');
  assert.match(source, /let shoeAnalyticsRequestId = 0/);
  assert.match(openAnalytics, /const requestId = \+\+shoeAnalyticsRequestId/);
  assert.match(openAnalytics, /requestId !== shoeAnalyticsRequestId/);
  assert.match(closeAnalytics, /shoeAnalyticsRequestId \+= 1/);
});

test('shoe analytics uses the requested six-card order without cost or reconciliation copy', () => {
  const analytics = extract('renderShoeAnalytics');
  const cards = analytics.slice(analytics.indexOf('const cards'), analytics.indexOf('const recentRows'));
  const labels = [...cards.matchAll(/label: '([^']+)'/g)].map(match => match[1]);
  assert.deepEqual(labels, ['總里程', '穿著次數', '近 30／90 天', '最後使用', '壽命進度', '預估退役']);
  assert.doesNotMatch(analytics, /每公里成本|每次穿著|日誌 .*歷史調整/);
  assert.match(analytics, /card\.sub \? `<div class="insight-card-sub">/);
});

test('unclassified shoes stay unclassified when the form is saved', () => {
  const context = vm.createContext({ document: { querySelectorAll: () => [] } });
  vm.runInContext(extract('getSelectedCategories'), context);
  assert.deepEqual(Array.from(context.getSelectedCategories()), []);
});

function loadUiActions(globals = {}) {
  const plainVm = require('node:vm');
  class Element {}
  const listeners = {};
  const context = plainVm.createContext({ Element, console, ...globals,
    document: { addEventListener: (type, listener) => { listeners[type] = listener; } } });
  plainVm.runInContext(fs.readFileSync('frontend/app-actions.js', 'utf8') + '\nthis.UI_ACTIONS = UI_ACTIONS;', context);
  const element = (attributes, parent = null, tagName = 'BUTTON') => Object.assign(new Element(), {
    tagName, parent, dataset: attributes.dataset || {},
    getAttribute: name => attributes[name],
    closest(selector) {
      const name = selector.slice(1, -1);
      for (let node = this; node; node = node.parent) if (node.getAttribute(name) !== undefined) return node;
      return null;
    },
  });
  return { context, listeners, element };
}

test('SPEC-047 markup declares UI actions instead of inline JavaScript handlers', () => {
  const inline = /\son(?:click|dblclick|change|input|submit|keydown|keyup|focus|blur|error|load)=/g;
  // SPEC-054 moved the last exception, the stylesheet onload, into a hashed script.
  assert.deepEqual(htmlSource.match(inline) || [], []);
  assert.match(htmlSource, /<link id="app-styles" rel="preload" href="[^"]+" as="style">\n<script>/, 'the stylesheet loader runs before any application script');
  assert.equal((scriptSource.match(inline) || []).length, 0, 'generated rows declare data actions');
  assert.match(htmlSource, /getElementById\('app-boot-retry'\)\.addEventListener\('click'/, 'boot retry works without the app bundle');
});

test('SPEC-047 every declared data action has exactly one registered handler', () => {
  const { context, listeners } = loadUiActions();
  const declared = new Map();
  for (const [, type, name] of `${htmlSource}\n${scriptSource}`.matchAll(/data-(click|dblclick|change|input|submit|keydown)="([a-z-]+)"/g)) {
    declared.set(`${type}:${name}`, [type, name]);
  }
  for (const [type, name] of declared.values()) {
    assert.equal(typeof context.UI_ACTIONS[type][name], 'function', `${type}:${name} is registered`);
  }
  const registered = Object.entries(context.UI_ACTIONS).flatMap(([type, actions]) => Object.keys(actions).map(name => `${type}:${name}`));
  assert.deepEqual(registered.filter(key => !declared.has(key)), [], 'no registered action is unused');
  assert.deepEqual(Object.keys(listeners).sort(), ['change', 'click', 'dblclick', 'input', 'keydown', 'submit']);
});

test('SPEC-047 delegated dispatch runs only the nearest action and owns navigation defaults', () => {
  const calls = [];
  const { listeners, element } = loadUiActions({
    selectRunCalendarDate: (date, event) => calls.push(['day', date, event.type]),
    openRunModal: id => calls.push(['run', id]),
    handleLogin: () => calls.push(['login']),
    showLoginForm: () => calls.push(['show-login']),
    sendAgentMessage: () => calls.push(['send']),
  });
  const event = (type, target, extra = {}) => {
    const value = { type, target, prevented: false, preventDefault() { this.prevented = true; }, ...extra };
    listeners[type](value);
    return value;
  };
  const day = element({ 'data-click': 'select-calendar-date', dataset: { date: '2026-11-01' } });
  const runButton = element({ 'data-click': 'open-run', dataset: { runId: '42' } }, day);
  const label = element({}, runButton, 'SPAN');
  event('click', label);
  event('click', day);
  assert.deepEqual(calls.splice(0), [['run', 42], ['day', '2026-11-01', 'click']]);

  assert.equal(event('submit', element({ 'data-submit': 'login' }, null, 'FORM')).prevented, true);
  assert.equal(event('click', element({ 'data-click': 'show-login-form' }, null, 'A')).prevented, true);
  assert.equal(event('click', element({ 'data-click': 'open-run', dataset: { runId: '7' } })).prevented, false);
  const compose = element({ 'data-keydown': 'agent-compose' }, null, 'TEXTAREA');
  assert.equal(event('keydown', compose, { key: 'Enter', shiftKey: true }).prevented, false);
  assert.equal(event('keydown', compose, { key: 'Enter', shiftKey: false }).prevented, true);
  assert.deepEqual(calls, [['login'], ['show-login'], ['run', 7], ['send']]);
});
