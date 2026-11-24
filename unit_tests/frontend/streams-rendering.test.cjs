const { runContext, test, assert, fs, path, vm, htmlSource, scriptPaths, scriptSource, styleSource, source, authOperationContext, streamContext, editContext, tableHeaders, extract, panelWiring, readText, transportContext } = require('./helpers.cjs');

test('panel rendering is lazy, reused, and invalidated by data or theme changes', () => {
  const counts = {};
  const hooks = ['renderCards', 'renderAlerts', 'renderCategorySummary', 'renderTable', 'renderRetiredTable',
    'renderCharts', 'populateRunShoeSelects', 'renderRunLog', 'renderHomeSummary', 'renderOnboarding', 'renderMonthlyCharts', 'renderPaceAnalysis', 'renderSpendingCharts'];
  let active = 'runs';
  const context = runContext({ document: { querySelector: () => ({ dataset: { panel: active } }) },
    Chart() {}, localDateISO: () => '2026-10-19', selectedRunMonth: () => '2026-10',
    ...Object.fromEntries(hooks.map(name => [name, () => { counts[name] = (counts[name] || 0) + 1; }])),
  });
  vm.runInContext(`let panelRevision = 0, stackedRunsRequestId = 0, currentTheme = 'light';
    const renderedPanels = new Map();\n${panelWiring()}\n${extract('invalidatePanels')}\n${extract('renderActivePanel')}`, context);
  context.renderActivePanel(); context.renderActivePanel();
  assert.equal(counts.renderRunLog, 1);
  assert.equal(counts.renderCharts, undefined);
  assert.equal(counts.renderMonthlyCharts, undefined);
  active = 'monthly'; context.renderActivePanel();
  assert.equal(counts.renderMonthlyCharts, 1);
  // SPEC-105: race readiness registers itself on the monthly tab, after the monthly charts.
  assert.equal(counts.renderPaceAnalysis, 1);
  active = 'runs'; context.renderActivePanel();
  assert.equal(counts.renderRunLog, 1);
  context.invalidatePanels(); context.renderActivePanel();
  assert.equal(counts.renderRunLog, 2);
  assert.equal(counts.renderMonthlyCharts, 1, 'data changes do not redraw hidden panels');
  vm.runInContext("currentTheme = 'dark'", context); context.renderActivePanel();
  assert.equal(counts.renderRunLog, 3);
});

test('SPEC-101 features register their panels and data in script order; the shell names none of them', () => {
  const order = [];
  const hooks = ['renderCards', 'renderAlerts', 'renderCategorySummary', 'renderTable', 'renderRetiredTable',
    'renderCharts', 'renderSpendingCharts', 'populateRunShoeSelects', 'renderRunLog', 'renderHomeSummary',
    'renderOnboarding', 'renderMonthlyCharts', 'prepareGoalForm', 'loadStravaHistory', 'render'];
  let active = 'shoes';
  const context = runContext({ document: { querySelector: () => ({ dataset: { panel: active } }) },
    Chart() {}, localDateISO: () => '2026-10-19', selectedRunMonth: () => '2026-10',
    ...Object.fromEntries(hooks.map(name => [name, (...args) => order.push(args.length ? `${name}(${args})` : name)])),
  });
  vm.runInContext(`let panelRevision = 0, currentTheme = 'light';
    const renderedPanels = new Map();\n${panelWiring()}\n${extract('invalidatePanels')}\n${extract('renderActivePanel')}`, context);
  // The shared feature context installs the real goal form helpers; observe this one instead.
  context.prepareGoalForm = () => order.push('prepareGoalForm');
  context.renderActivePanel();
  assert.deepEqual(order.splice(0), ['renderCards', 'renderAlerts', 'renderCategorySummary', 'renderTable',
    'renderRetiredTable', 'renderCharts', 'renderSpendingCharts']);
  active = 'runs'; context.renderActivePanel();
  assert.deepEqual(order.splice(0), ['populateRunShoeSelects', 'renderRunLog', 'renderHomeSummary', 'renderOnboarding']);
  // The run month is part of the runs panel's redraw key.
  context.renderActivePanel(); assert.deepEqual(order, []);
  context.selectedRunMonth = () => '2026-09'; context.renderActivePanel();
  assert.deepEqual(order.splice(0), ['populateRunShoeSelects', 'renderRunLog', 'renderHomeSummary', 'renderOnboarding']);
  const panels = vm.runInContext('panelHooks', context), readers = vm.runInContext('resourceReaders', context);
  assert.deepEqual([...panels.keys()].sort(), ['monthly', 'report', 'runs', 'shoes']);
  assert.deepEqual([...readers.keys()], ['runs']);
  panels.get('monthly').forEach(hook => hook.enter?.());
  vm.runInContext('dataHooks', context).forEach(hook => { hook.arrived?.('goal'); hook.history?.(); });
  assert.deepEqual(order.splice(0), ['prepareGoalForm', 'loadStravaHistory', 'render(goal)']);
  // A full redraw drops an in-flight annual run read.
  const before = context.runController.state.annualRequest;
  context.invalidatePanels(); assert.equal(context.runController.state.annualRequest, before + 1);
  // The shell calls no feature function by name: only registered hooks.
  const shell = readText('frontend/app-core.js').replace(/\/\/.*$/gm, '');
  for (const name of hooks) assert.doesNotMatch(shell, new RegExp(`(?<![.\\w])${name}\\(`), name);
});

test('shoe retirement presentation uses only the backend date, including no forecast', () => {
  const context = vm.createContext({});
  vm.runInContext(extract('calc'), context);
  const shoe = { price: 3000, mileage: 300, expected_mileage: 900, monthly_km: 60,
    forecast_retirement_date: '2027-04-17', forecast_monthly_km: 101.46 };
  const forecast = context.calc(shoe).retireDate;
  assert.equal(forecast.getFullYear(), 2027); assert.equal(forecast.getMonth(), 3); assert.equal(forecast.getDate(), 17);
  assert.equal(context.calc({ ...shoe, forecast_retirement_date: null }).retireDate, null);
});

test('table numeric headers and shared component geometry have explicit presentation contracts', () => {
  for (const [id, expected] of Object.entries({ 'shoe-table': [3,4,5,6,7], 'retired-table': [3,4,5,6,7], 'run-table': [1,2,3], 'spending-table': [4,5,6] })) {
    const before = htmlSource.slice(0, htmlSource.indexOf(`<tbody id="${id}"`));
    const heads = [...before.slice(before.lastIndexOf('<thead>')).matchAll(/<th\b([^>]*)>/g)];
    assert.deepEqual(heads.flatMap((head, index) => head[1].includes('numeric') ? [index] : []), expected);
  }
  assert.match(styleSource, /--control-height:\s*44px/);
  assert.match(styleSource, /--control-compact-height:\s*36px/);
  assert.match(styleSource, /th\.numeric, td\.numeric \{ text-align: right/);
  assert.match(htmlSource, /<label for="agent-model">今日免費模型/);
  assert.doesNotMatch(htmlSource, /<span style="flex:1"><\/span>/);
});

test('shoe action groups show only relevant controls without overriding shared button layout', () => {
  const definition = source.slice(source.indexOf('class ShoeModal {'), source.indexOf('// 初始化一次'));
  const elements = { 'shoe-secondary-actions': { hidden: false }, 'f-monthly': {} };
  const context = vm.createContext({ document: { getElementById: id => elements[id] } });
  vm.runInContext(definition + '\nglobalThis.Modal = ShoeModal;', context);
  const modal = Object.create(context.Modal.prototype);
  Object.assign(modal, { formIds: {}, titleEl: {}, btnDelete: { style: {} }, btnMove: { style: {} }, monthlyRow: { style: {} } });
  modal._updateUI({ title: '新增', showDelete: false, showMove: false, monthly: 60, monthlyVisible: true });
  assert.equal(elements['shoe-secondary-actions'].hidden, true);
  assert.equal(modal.btnDelete.style.display, 'none');
  modal._updateUI({ title: '編輯', showDelete: true, showMove: true, moveText: '移至退役', monthly: 80, monthlyVisible: true });
  assert.equal(elements['shoe-secondary-actions'].hidden, false);
  assert.equal(modal.btnDelete.style.display, ''); assert.equal(modal.btnMove.style.display, '');
  assert.equal(modal.btnMove.textContent, '移至退役'); assert.equal(elements['f-monthly'].value, 80);
});

test('shoe purchase columns live only in spending details, with aligned table rows', () => {
  const elements = { 'shoe-table': {}, 'retired-table': {} };
  const shoe = { id: 7, brand: 'Test', model: 'Runner', date: '2026-01-02',
    size: 'UNIQUE-SIZE', price: 2400, orig_price: 4000, mileage: 100,
    discount_percent: 60, cost_per_km: 24, expected_cost_per_km: 3,
    usage_percent: 12.5, remaining_mileage_km: 700,
    expected_mileage: 800, monthly_km: 50, categories: ['Daily'] };
  const context = vm.createContext({
    document: { getElementById: id => elements[id] },
    shoes: [shoe], retiredShoes: [{ ...shoe, id: 8, is_retired: true }],
    brandColor: () => '#123456', shoeColor: () => '#123456', progressColor: () => '#123456',
    getThemeColor: (_, fallback) => fallback, shoeCategories: s => s.categories,
  });
  vm.runInContext(['esc', 'calc', 'fmtPct', 'fmtCostPerKm', 'fmtDate', 'forecastSourceText', 'floorShoeKm', 'formatShoeMileage',
    'renderTable', 'renderRetiredTable'].map(extract).join('\n'), context);
  context.renderTable();
  context.renderRetiredTable();
  // SPEC-050: the planned monthly km is edited in the shoe form, not shown as a column.
  for (const [id, count] of [['shoe-table', 11], ['retired-table', 10]]) {
    const headers = tableHeaders(id);
    assert.equal(headers.length, count);
    assert.ok(['尺寸', '買價', '原價', '折數', '月跑量'].every(label => !headers.includes(label)));
    assert.doesNotMatch(elements[id].innerHTML, /data-field="monthly_km"/);
    assert.equal((elements[id].innerHTML.match(/<td\b/g) || []).length, count);
    assert.doesNotMatch(elements[id].innerHTML, /UNIQUE-SIZE|\$2,400|\$4,000|60\.00%/);
    assert.match(elements[id].innerHTML, /\$24\.00/); // Cost/km stays on shoes.
    assert.match(elements[id].innerHTML, />分析<\/button>/);
    assert.match(elements[id].innerHTML, />編輯<\/button>/);
  }
  assert.deepEqual(tableHeaders('spending-table'),
    ['日期', '品牌', '鞋款', '尺寸', '買價', '原價', '折數', '類別', '狀態']);
});

test('spending details retain active and retired purchases, escape sizes and handle missing values', () => {
  const tbody = {};
  const shoe = { id: 1, brand: 'Test', model: 'Active', date: '2026-02-02',
    size: '<img src=x onerror=alert(1)>', price: 2400, orig_price: 4000, discount_percent: 60, categories: ['Daily'] };
  const shoes = [shoe];
  const retiredShoes = [{ ...shoe, id: 2, model: 'Retired', date: '2026-01-01',
    size: '', price: 0, orig_price: 0, discount_percent: null, is_retired: true }];
  const context = vm.createContext({ document: { getElementById: () => tbody },
    shoes, retiredShoes, shoeCategories: s => s.categories,
    byDate: (a, b) => a.date.localeCompare(b.date),
  });
  vm.runInContext(['esc', 'fmtMoney', 'renderSpendingTable'].map(extract).join('\n'), context);
  context.renderSpendingTable();
  const rows = [...tbody.innerHTML.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(match => match[1]);
  assert.equal(rows.length, 2);
  for (const row of rows) assert.equal((row.match(/<td\b/g) || []).length, 9);
  assert.match(rows[0], /Retired[\s\S]*<td>—<\/td>[\s\S]*<td>已退役<\/td>/);
  assert.match(rows[1], /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(rows[1], /\$2,400[\s\S]*\$4,000[\s\S]*60\.0%[\s\S]*使用中/);
  assert.doesNotMatch(tbody.innerHTML, /<img|—%|NaN|Infinity/);
  assert.equal(shoes[0].size, shoe.size, 'rendering must not modify purchase data');
  context.seedCoreData({ shoes: [], retiredShoes: [] });
  context.renderSpendingTable();
  assert.equal(tbody.innerHTML, '');
});

test('PWA metadata, local dependencies and service worker registration are present', () => {
  assert.match(source, /rel="manifest" href="\/manifest\.webmanifest"/);
  assert.match(source, /rel="apple-touch-icon" href="\/icons\/apple-touch-icon\.png"/);
  assert.match(source, /navigator\.serviceWorker\.register\('\/service-worker\.js'\)/);
  assert.match(source, /src="\/vendor\/chart\.umd\.min\.js"/);
  assert.match(source, /src="\/vendor\/marked\.min\.js"/);
  assert.doesNotMatch(source, /cdn\.jsdelivr\.net/);
  const serviceWorker = fs.readFileSync('frontend/service-worker.js', 'utf8');
  const assetVersion = serviceWorker.match(/APP_ASSET_VERSION = '([^']+)'/)?.[1];
  assert.ok(assetVersion, 'service worker declares an application asset version');
  assert.match(serviceWorker, /'\/vendor\/chart\.umd\.min\.js'/);
  assert.match(serviceWorker, /'\/vendor\/marked\.min\.js'/);
  const appAssets = scriptPaths.map(file => `/${path.basename(file)}`).concat('/styles.css');
  for (const asset of appAssets) {
    assert.ok(serviceWorker.includes(`versioned('${asset}')`), `${asset} is precached with a version`);
    const attribute = asset.endsWith('.css') ? 'href' : 'src';
    assert.ok(htmlSource.includes(`${attribute}="${asset}?v=${assetVersion}"`), `${asset} uses the service worker version`);
  }
  assert.match(serviceWorker, /event\.waitUntil\(installShell\(\)\)/);
  assert.match(serviceWorker, /name\.startsWith\(CACHE_PREFIX\)/);
  assert.doesNotMatch(serviceWorker.slice(serviceWorker.indexOf("self.addEventListener('fetch'")), /cache\.put\(/);
  assert.ok(htmlSource.includes(`<meta name="app-asset-version" content="${assetVersion}">`));
  const unversionedHtml = htmlSource.replaceAll(`?v=${assetVersion}`, '');
  assert.match(unversionedHtml, /src="\/app-boot\.js"[\s\S]*src="\/app-state\.js"[\s\S]*src="\/app-api\.js"[\s\S]*src="\/app-auth\.js"[\s\S]*src="\/app-core\.js"[\s\S]*src="\/app-agent\.js"[\s\S]*src="\/app-reports\.js"[\s\S]*src="\/app-runs\.js"[\s\S]*src="\/app-strava\.js"[\s\S]*src="\/app-run-insights\.js"[\s\S]*src="\/app-shoes\.js"[\s\S]*src="\/app\.js"/);
});

test('every startup chooses the run-log home before authentication, ignoring legacy tabs', async () => {
  for (const mode of ['online', 'offline', 'logged-out']) {
    let active = 'agent', loads = 0, loginShown = false;
    const elements = new Proxy({}, { get: (target, id) => target[id] ||= { value: '' } });
    const context = vm.createContext({
      document: { getElementById: id => elements[id] }, authToken: mode === 'logged-out' ? null : 'synthetic',
      refreshDateLimits() {}, resetAppLayout() { active = 'runs'; },
      localDateISO: () => '2026-10-20', previousMonthValue: () => '2026-09',
      captureAuthSession: () => ({}), isCurrentAuthSession: () => true,
      API_BASE: '/api', authHeaders: () => ({}),
      authenticatedFetch: async () => {
        assert.equal(active, 'runs', 'home is selected before auth completes');
        if (mode === 'offline') throw new TypeError('offline');
        return { ok: true };
      },
      localStorage: { getItem() { assert.fail('startup must not read a saved tab'); } },
      showAppView() { assert.equal(active, 'runs'); }, restoreAgentChat() {}, loadAgentModels() {},
      loadData: async () => { loads++; }, hideAppBoot() {},
      showLoginView() { loginShown = true; }, console: { warn() {} },
    });
    vm.runInContext(extract('init'), context);
    await context.init();
    assert.equal(active, 'runs');
    assert.equal(loads, mode === 'logged-out' ? 0 : 1);
    assert.equal(loginShown, mode === 'logged-out');
  }
  assert.doesNotMatch(extract('switchTab'), /localStorage/);
  assert.match(extract('applyTheme'), /localStorage\.setItem\('theme', themePreference\)/);
});

test('persisted page restoration selects home without resetting ordinary visibility changes', () => {
  const bootstrap = fs.readFileSync('frontend/app.js', 'utf8');
  const listener = bootstrap.slice(bootstrap.indexOf('// Back/forward cache'), bootstrap.indexOf("if ('serviceWorker'"));
  let onShow, resets = 0, renders = 0;
  const context = vm.createContext({
    window: { addEventListener(name, callback) { assert.equal(name, 'pageshow'); onShow = callback; } },
    authToken: 'synthetic', resetAppLayout() { resets++; }, renderActivePanel() { renders++; },
  });
  vm.runInContext(listener, context);
  onShow({ persisted: false });
  assert.equal(resets, 0);
  onShow({ persisted: true });
  assert.equal(resets, 1); assert.equal(renders, 1);
  context.authToken = null;
  onShow({ persisted: true });
  assert.equal(resets, 2); assert.equal(renders, 1);
  assert.doesNotMatch(bootstrap, /visibilitychange/);
});

function fakeMarkdownDocument(tree) {
  // Minimal inert DOM: enough for the sanitizer's traversal and serialization.
  const doc = { createTextNode: text => ({ text, parent: null }) };
  const build = (spec, parent) => {
    if (typeof spec === 'string') return { text: spec, parent };
    const [tag, attrs = {}, ...children] = spec;
    const el = {
      tagName: tag.toUpperCase(), parent, attrs: new Map(Object.entries(attrs)),
      get attributes() { return [...this.attrs.keys()].map(name => ({ name })); },
      hasAttribute(name) { return this.attrs.has(name); },
      getAttribute(name) { return this.attrs.get(name); },
      setAttribute(name, value) { this.attrs.set(name, value); },
      removeAttribute(name) { this.attrs.delete(name); },
      get isConnected() { let node = this; while (node.parent) node = node.parent; return node === doc.body; },
      get textContent() { return this.children.map(child => child.text ?? child.textContent).join(''); },
      replaceWith(node) { const list = this.parent.children; node.parent = this.parent; list[list.indexOf(this)] = node; this.parent = null; },
    };
    el.children = children.map(child => build(child, el));
    return el;
  };
  const serialize = node => node.text !== undefined ? node.text
    : `<${node.tagName.toLowerCase()}${[...node.attrs].map(([k, v]) => ` ${k}="${v}"`).join('')}>${node.children.map(serialize).join('')}</${node.tagName.toLowerCase()}>`;
  doc.body = build(['body', {}, ...tree], null);
  doc.body.querySelectorAll = () => {
    const out = [];
    const walk = node => node.children?.forEach(child => { if (child.tagName) { out.push(child); walk(child); } });
    walk(doc.body);
    return out;
  };
  Object.defineProperty(doc.body, 'innerHTML', { get: () => doc.body.children.map(serialize).join('') });
  return doc;
}

test('markdown sanitizer parses untrusted HTML in an inert document and allowlists attributes', () => {
  const markdownSource = fs.readFileSync('frontend/app-markdown.js', 'utf8');
  const parsed = [];
  const tree = [
    ['p', { id: 'authToken', class: 'modal active', style: 'x', onclick: 'steal()' }, 'hi'],
    ['img', { src: 'x', onerror: 'steal()' }],
    ['a', { href: 'javascript:steal()', target: '_blank' }, 'bad'],
    ['a', { href: 'https://example.com/a', name: 'marked' }, 'ok'],
    ['div', {}, ['svg', {}, ['script', {}, 'steal()']]],
    ['td', { colspan: '2', align: 'center', href: 'https://example.com' }, 'cell'],
  ];
  const context = vm.createContext({
    window: { location: { origin: 'http://test.local' } }, URL,
    DOMParser: class { parseFromString(raw, type) { parsed.push([raw, type]); return fakeMarkdownDocument(tree); } },
  });
  // No `document` global: touching the live document would throw.
  require('node:vm').runInContext(markdownSource, context);
  const html = context.sanitizeMarkdownHtml('<raw>');
  assert.deepEqual(parsed, [['<raw>', 'text/html']]);
  assert.doesNotMatch(markdownSource, /\.innerHTML\s*=/);
  assert.doesNotMatch(html, /onclick|onerror|style=|class=|id=|name=|target=|javascript:|<img|<svg|<script/);
  assert.match(html, /<p>hi<\/p>/);
  assert.match(html, /<a href="https:\/\/example.com\/a" rel="noopener noreferrer">ok<\/a>/);
  assert.match(html, /<a>bad<\/a>/);
  assert.match(html, /<div>steal\(\)<\/div>/);
  assert.match(html, /<td colspan="2" align="center">cell<\/td>/);
});
