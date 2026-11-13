const { test, assert, vm, htmlSource, styleSource, scriptSource, extract } = require('./helpers.cjs');

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
