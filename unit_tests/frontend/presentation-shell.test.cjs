const { test, assert, fs, path, vm, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, transportContext } = require('./helpers.cjs');

test('startup and login show progress until the application is ready', () => {
  assert.match(htmlSource, /id="app-boot"[^>]+role="status"[^>]+aria-live="polite"/);
  assert.match(htmlSource, /id="app-boot-message">正在準備應用程式/);
  assert.match(htmlSource, /id="app-boot-retry"[^>]+hidden>重新載入/);
  assert.ok(htmlSource.indexOf('id="app-boot"') < htmlSource.indexOf('src="/vendor/chart.umd.min.js"'));
  assert.match(htmlSource, /__appBootLegacyPoll/);
  assert.match(htmlSource, /Critical startup UI must not depend[\s\S]+body \{ margin: 0; opacity: 1 !important; \}/);
  assert.match(htmlSource, /id="app-styles" rel="preload" href="\/styles\.css\?v=[^"]+" as="style"/);
  assert.match(htmlSource, /dataset\.ready='true';window\.dispatchEvent\(new Event\('appstylesready'\)\)/);
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
  assert.match(htmlSource, /id="login-form" autocomplete="off"/);
  assert.match(htmlSource, /id="login-password" type="password" autocomplete="off"/);
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
