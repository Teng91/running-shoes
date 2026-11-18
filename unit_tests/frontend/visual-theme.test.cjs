const { test, assert, fs, vm, htmlSource, styleSource, scriptSource, extract } = require('./helpers.cjs');

// SPEC-051: the sports-tech theme is a token contract between CSS and the chart code.
function block(selector) {
  const start = styleSource.indexOf(`${selector} {`);
  assert.ok(start >= 0, `${selector} block exists`);
  return styleSource.slice(start, styleSource.indexOf('\n}', start));
}
const defined = css => new Set([...css.matchAll(/(--[\w-]+):/g)].map(match => match[1]));

test('SPEC-051 every theme token the charts read is defined for dark and light themes', () => {
  const read = new Set([...scriptSource.matchAll(/getThemeColor\('(--[\w-]+)'/g)].map(match => match[1]));
  for (const token of ['--chart-1', '--chart-2', '--chart-warn', '--wear-1', '--wear-5', '--card']) assert.ok(read.has(token), `${token} is read`);
  const dark = defined(block(':root'));
  const light = defined(block('body.light-theme'));
  for (const token of read) {
    assert.ok(dark.has(token), `dark theme defines ${token}`);
    assert.ok(light.has(token), `light theme defines ${token}`);
  }
  // Volt fills keep dark ink; the light theme darkens volt only where it is text or a line.
  assert.match(block(':root'), /--accent: #c8ff3c;[\s\S]*--accent-ink: #0b1100;/);
  assert.match(block('body.light-theme'), /--accent-light: #4a7400;[\s\S]*--chart-1: #78ad00;/);
  // Chart marks no longer hard-code the old indigo/green palette.
  assert.doesNotMatch(scriptSource, /(backgroundColor|borderColor): '#(6366f1|22c55e|94a3b8)'|strokeStyle = '#(22c55e|eab308)'|rgba\((99,102,241|34,197,94)/);
});

test('SPEC-051 shoe wear colors follow the theme ramp', () => {
  const context = vm.createContext({ getThemeColor: token => token });
  vm.runInContext(extract('progressColor'), context);
  assert.deepEqual([0, .19, .2, .45, .7, .8, 1.2].map(value => context.progressColor(value)),
    ['--wear-1', '--wear-1', '--wear-2', '--wear-3', '--wear-4', '--wear-5', '--wear-5']);
});

test('SPEC-051 calendar days carry their distance load instead of an inline color', () => {
  const nodes = new Proxy({}, { get: (target, id) => target[id] ||= { innerHTML: '' } });
  const context = vm.createContext({ document: { getElementById: id => nodes[id] },
    localDateISO: () => '2026-08-05', runShoe: () => ({ model: 'Daily Runner' }), esc: String });
  vm.runInContext(extract('renderRunCalendar'), context);
  context.renderRunCalendar([{ date: '2026-08-05', km: 12, shoes: [{ shoe_id: 1, count: 1 }] }], '2026-08');
  const html = nodes['run-calendar'].innerHTML;
  assert.match(html, /class="calendar-day has-run today" style="--day-load:0\.66" data-click="select-calendar-date" data-date="2026-08-05"/);
  assert.match(html, /class="calendar-day" style="--day-load:0\.00" data-click="select-calendar-date" data-date="2026-08-06"/);
  assert.doesNotMatch(html, /background:rgba/);
  assert.match(styleSource, /\.calendar-day\.has-run \{[^}]*var\(--day-load, 0\)/);
});

test('SPEC-051 navigation and brand use line icons, and English eyebrows stay decorative', () => {
  const sidebar = htmlSource.slice(htmlSource.indexOf('<aside class="app-sidebar">'), htmlSource.indexOf('</aside>'));
  const tabs = [...sidebar.matchAll(/<button class="tab[^"]*"[\s\S]*?<\/button>/g)].map(match => match[0]);
  assert.equal(tabs.length, 4);
  for (const tab of tabs) {
    // The visible label stays the last span: the mobile header copies it.
    assert.match(tab, /<span class="tab-icon" aria-hidden="true"><svg viewBox="0 0 24 24"[^>]*stroke="currentColor"[\s\S]*<\/svg><\/span><span>[^<]+<\/span><\/button>$/);
  }
  assert.match(sidebar, /<div class="app-brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="currentColor"/);
  assert.match(htmlSource, /<div class="app-boot-mark" aria-hidden="true"><svg/);
  assert.doesNotMatch(htmlSource, /[🏃👟📊✨🔄]/u);
  for (const [heading, eyebrow] of [['goal-title', 'ANNUAL GOAL'], ['trends-title', 'TRAINING LOAD'], ['run-table-title', 'ACTIVITIES']]) {
    assert.match(htmlSource, new RegExp(`id="${heading}" data-eyebrow="${eyebrow}"`));
  }
  // Alternative text "" keeps generated eyebrows and watermarks out of accessible names.
  assert.match(styleSource, /\[data-eyebrow\]::before \{\n  content: attr\(data-eyebrow\);\n  content: attr\(data-eyebrow\) \/ "";/);
  assert.match(styleSource, /\.run-intro\[data-mark\]::after \{\n  content: attr\(data-mark\);\n  content: attr\(data-mark\) \/ "";/);
});

test('SPEC-051 decoration never re-anchors the fixed phone tab bar or shifts measured layout', () => {
  const phone = styleSource.slice(styleSource.indexOf('@media (max-width: 800px) {\n  .app-shell { display: block; }'));
  const sidebar = phone.slice(phone.indexOf('  .app-sidebar {'), phone.indexOf('\n  }', phone.indexOf('  .app-sidebar {')));
  assert.ok(sidebar.includes('background: var(--sidebar-bg);'));
  assert.doesNotMatch(sidebar, /^\s*(-webkit-)?(backdrop-filter|filter|transform)\s*:/m, 'the tab bar lives inside the phone header');
  assert.match(styleSource, /@keyframes panel-in \{ from \{ opacity: 0; \} to \{ opacity: 1; \} \}/);
  assert.match(styleSource, /@media \(prefers-reduced-motion: reduce\) \{\n  \.tab-panel\.active \{ animation: none; \}/);
});

// SPEC-052: home-screen and tab icons carry the same volt mark as the in-app brand.
const pathData = svg => [...svg.matchAll(/<path d="([^"]+)"/g)].map(match => match[1]);
function pngSize(file) {
  const bytes = fs.readFileSync(file);
  assert.equal(bytes.subarray(1, 4).toString('latin1'), 'PNG', `${file} is a PNG`);
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

test('SPEC-052 home-screen icons are rendered at their declared sizes from the volt mark source', () => {
  const manifest = JSON.parse(fs.readFileSync('frontend/manifest.webmanifest', 'utf8'));
  assert.deepEqual(manifest.icons.map(icon => icon.src), ['/icons/icon-192.png', '/icons/icon-512.png']);
  for (const icon of manifest.icons) {
    const [width, height] = pngSize(`frontend${icon.src}`);
    assert.equal(`${width}x${height}`, icon.sizes);
    assert.match(icon.purpose, /\bmaskable\b/);
  }
  assert.deepEqual(pngSize('frontend/icons/apple-touch-icon.png'), [180, 180]);
  assert.equal(fs.existsSync('frontend/icons/app-icon-source.png'), false, 'the indigo raster source is retired');

  const source = fs.readFileSync('frontend/icons/app-icon.svg', 'utf8');
  const brand = htmlSource.slice(htmlSource.indexOf('<div class="app-brand-mark"'), htmlSource.indexOf('</svg>', htmlSource.indexOf('<div class="app-brand-mark"')));
  // The mark group (after the background grid pattern) reuses the in-app brand paths exactly.
  assert.deepEqual(pathData(source.slice(source.indexOf('<g filter='))), pathData(brand));
  assert.match(source, /<rect width="512" height="512" fill="#07090c"\/>/, 'full-bleed opaque background for iOS and masks');
  // Android masks may crop to a circle of radius 40% (204.8px of 512): the whole ring must fit inside.
  for (const ring of source.matchAll(/<circle cx="256" cy="256" r="(\d+)"[^>]*stroke-width="(\d+)"/g)) {
    assert.ok(Number(ring[1]) + Number(ring[2]) / 2 <= 204.8, `ring r=${ring[1]} stays in the maskable safe zone`);
  }
});

test('SPEC-052 the browser tab uses the volt SVG mark with a PNG fallback', () => {
  const favicon = fs.readFileSync('frontend/favicon.svg', 'utf8');
  const brand = htmlSource.slice(htmlSource.indexOf('<div class="app-brand-mark"'), htmlSource.indexOf('</svg>', htmlSource.indexOf('<div class="app-brand-mark"')));
  assert.deepEqual(pathData(favicon), pathData(brand));
  assert.match(favicon, /fill="#07090c"[\s\S]*fill="#c8ff3c"/);
  assert.doesNotMatch(favicon, /#818cf8|<text/);
  assert.match(htmlSource, /<link rel="icon" type="image\/svg\+xml" href="\/favicon\.svg">\n<link rel="icon" type="image\/png" sizes="192x192" href="\/icons\/icon-192\.png">\n<link rel="apple-touch-icon" href="\/icons\/apple-touch-icon\.png">/);
  const worker = fs.readFileSync('frontend/service-worker.js', 'utf8');
  for (const asset of ['/favicon.svg', '/icons/icon-192.png', '/icons/icon-512.png', '/icons/apple-touch-icon.png']) {
    assert.ok(worker.includes(`'${asset}',`), `${asset} is precached`);
  }
});

test('SPEC-082 the theme follows the system by default and remembers light, dark or system', () => {
  const pressed = {};
  const buttons = ['light', 'dark', 'system'].map(choice => ({ dataset: { themeChoice: choice },
    setAttribute(name, value) { pressed[choice] = value; } }));
  const stored = new Map();
  const classes = new Set();
  let meta = null;
  const redraws = [];
  const context = vm.createContext({
    THEME_PREFERENCES: ['light', 'dark', 'system'], themePreference: 'system', currentTheme: 'dark',
    localStorage: { setItem: (key, value) => stored.set(key, value) },
    systemLightQuery: { matches: true },
    document: {
      body: { classList: { toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)) } },
      querySelector: () => ({ setAttribute: (_, value) => { meta = value; } }),
      querySelectorAll: () => buttons,
    },
    invalidatePanels: () => redraws.push('invalidate'), renderActivePanel: () => redraws.push('render'),
  });
  vm.runInContext(['resolveTheme', 'applyTheme', 'setThemePreference'].map(extract).join('\n'), context);
  context.applyTheme('system');
  assert.equal(vm.runInContext('currentTheme', context), 'light', 'a light device shows the light theme');
  assert.ok(classes.has('light-theme'));
  assert.equal(meta, '#eef1f4');
  assert.equal(stored.get('theme'), 'system');
  assert.deepEqual({ ...pressed }, { light: 'false', dark: 'false', system: 'true' });

  context.setThemePreference('dark');
  assert.equal(vm.runInContext('currentTheme', context), 'dark');
  assert.ok(!classes.has('light-theme'));
  assert.deepEqual(redraws, ['invalidate', 'render'], 'charts redraw when the shown theme changes');
  context.setThemePreference('dark');
  assert.equal(redraws.length, 2, 'choosing the same theme again does not redraw');
  context.applyTheme('bogus');
  assert.equal(stored.get('theme'), 'system', 'unknown values fall back to following the system');

  assert.equal(context.resolveTheme('system', false), 'dark');
  assert.equal(context.resolveTheme('light', false), 'light');
  const boot = htmlSource.match(/<script>\s*try \{([\s\S]*?)\} catch/)[1];
  assert.match(boot, /theme !== 'dark' && window\.matchMedia\('\(prefers-color-scheme: light\)'\)\.matches/);
  assert.equal((htmlSource.match(/data-click="set-theme"/g) || []).length, 3);
  assert.doesNotMatch(htmlSource, /id="theme-toggle-btn"/);
});
