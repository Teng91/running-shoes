// SPEC-137: frontend review cleanup: theme tokens, dead code, the shoe form, shared markup and preloads.
const { test, assert, fs, htmlSource, styleSource, readText, scriptPaths } = require('./helpers.cjs');

const templates = fs.readdirSync('frontend/templates').filter(name => name.endsWith('.html'))
  .map(name => readText(`frontend/templates/${name}`)).join('\n');
const scripts = scriptPaths.map(readText).join('\n');

function block(css, selector) {
  const start = css.indexOf(`${selector} {`);
  return css.slice(start, css.indexOf('\n}', start));
}

function contrast(foreground, background) {
  const luminance = hex => {
    const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

test('SPEC-137 every color token the styles use is defined, and every defined one is used', () => {
  const css = styleSource + htmlSource;
  const defined = new Set([...css.matchAll(/(--[\w-]+):/g)].map(match => match[1]));
  const used = new Set([...css.matchAll(/var\((--[\w-]+)/g)].map(match => match[1]));
  // A few layout values (heatmap columns, a calendar day's load) are set by the scripts at runtime.
  const runtime = new Set([...scripts.matchAll(/(--[\w-]+)(?=['":])/g)].map(match => match[1]));
  assert.deepEqual([...used].filter(name => !defined.has(name) && !runtime.has(name)), [], 'no var() falls back to a fixed color');
  const unused = [...defined].filter(name => !used.has(name) && !scripts.includes(`'${name}'`));
  assert.deepEqual(unused, [], 'no token is defined only to sit unused');
  for (const name of ['--cyan', '--green', '--yellow', '--radius-sm', '--boot-card']) assert.equal(defined.has(name), false, name);
});

test('SPEC-137 light-theme text that used fixed or volt colors is readable', () => {
  const light = block(styleSource, 'body.light-theme');
  const token = name => new RegExp(`${name}: (#[0-9a-f]{6});`).exec(light)[1];
  const surfaces = [token('--card'), token('--card-raised')];
  for (const name of ['--warning-text', '--danger-text', '--accent-light']) {
    for (const surface of surfaces) assert.ok(contrast(token(name), surface) >= 4.5, `${name} on ${surface}`);
  }
  // The Strava badge sits on its own 16% orange tint over the card.
  assert.ok(contrast(token('--strava-text'), '#fee5d9') >= 4.5);
  assert.match(styleSource, /\.onboarding-steps li\.current \.onboarding-check \{ border-color: var\(--accent-line\); color: var\(--accent-light\); \}/);
  assert.match(styleSource, /\.run-source\.strava \{[^}]*color:var\(--strava-text\)/);
  assert.match(styleSource, /\.strava-conflicts-status\.strava-date-warning \{ color: var\(--warning-text\); \}/);
  for (const selector of ['.auth-error', '.inline-error', '.report-status.is-error']) {
    assert.match(styleSource, new RegExp(`${selector.replace(/\./g, '\\.')} \\{ color: var\\(--danger-text\\)`), selector);
  }
  assert.doesNotMatch(styleSource, /color: ?#0b1015|#ff7a3d;? ?}|var\(--warning,/);
});

test('SPEC-137 unused rules and functions are gone and [hidden] is declared once', () => {
  assert.doesNotMatch(styleSource + htmlSource, /inline-add|metric-source|agent-config input\[type="text"\]/);
  assert.equal((styleSource.match(/\[hidden\][^{]*\{/g) || []).length, 1, 'the global [hidden] rule hides everything');
  assert.match(styleSource, /\.sidebar-actions \{ display: grid; \}/);
  assert.doesNotMatch(scripts, /fetchRunPages/);
  assert.doesNotMatch(htmlSource, /id="personal-bests-note"/);
  // The stylesheet only adds the theme to the boot screen; its layout lives in the inline critical style.
  assert.doesNotMatch(styleSource, /@keyframes app-boot-run|\.app-boot-card \{/);
  assert.match(htmlSource, /\.app-boot-card \{ width: min\(100%, 320px\)/);
});

test('SPEC-137 the shoe form saves with Enter and closes only through the registries', () => {
  const modal = readText('frontend/templates/shoe-modal.html');
  assert.match(modal, /<form class="modal" data-submit="save-shoe" novalidate>/);
  assert.match(modal, /<button type="button" class="btn btn-delete" id="btn-delete" data-click="delete-shoe" hidden>/);
  assert.match(modal, /<button type="button" class="btn btn-edit" id="btn-move" data-click="move-shoe" hidden>/);
  assert.match(modal, /<button type="button" class="btn btn-cancel" data-click="close-shoe-modal">取消<\/button>\s*<button type="submit" class="btn btn-primary">儲存<\/button>/);
  // The nickname has its own row; brand and model share the next one.
  assert.match(modal, /<h2 id="modal-title">新增跑鞋<\/h2>\n {4}<div class="form-group"><label for="f-nickname">[^\n]*\n {4}<div class="form-row">\n[^\n]*f-brand[^\n]*\n[^\n]*f-model[^\n]*\n {4}<\/div>/);
  const shoes = readText('frontend/app-shoes.js');
  assert.doesNotMatch(shoes, /\.onclick|style\.display/);
  assert.match(shoes, /registerDialog\('modal', \{ close: closeModal, backdrop: true \}\)/);
  assert.match(shoes, /'save-shoe': \(\) => shoeModal\.submit\(\)/);
});

test('SPEC-137 templates carry no inline styles, and the sign-in screens share one notice and one mark', () => {
  assert.doesNotMatch(templates.replace(/<style>[\s\S]*?<\/style>/g, ''), /\sstyle="/);
  assert.equal((templates.match(/<!-- include:auth-privacy\.html -->/g) || []).length, 2);
  assert.equal((templates.match(/<details class="auth-privacy">/g) || []).length, 1, 'one source for the notice');
  for (const id of ['auth-view', 'app-view', 'register-form', 'reset-form']) {
    assert.match(htmlSource, new RegExp(`id="${id}" hidden`), id);
    assert.doesNotMatch(scripts, new RegExp(`getElementById\\('${id}'\\)\\.style\\.display`), id);
  }
  assert.match(styleSource, /\.auth-switch a \{ color: var\(--accent-light\); font-size: 13px; \}/);
  assert.match(styleSource, /\.modal\.run-dialog \{ width: 520px; \}/);
  // Copy matches the current tab names and the AI pages call the model menu the same.
  assert.doesNotMatch(htmlSource + scripts, /本日免費模型|「跑量與目標」/);
  assert.equal((htmlSource.match(/>今日免費模型</g) || []).length, 2);
});

test('SPEC-137 every native module is preloaded at the URL its import builds', () => {
  const manifest = JSON.parse(readText('frontend/assets.json'));
  const version = encodeURIComponent(manifest.version);
  const preloads = [...htmlSource.matchAll(/<link rel="modulepreload" href="\/([^"?]+)\?v=([^"]+)">/g)];
  assert.deepEqual(preloads.map(match => match[1]), manifest.modules);
  assert.ok(preloads.every(match => match[2] === version));
  const imported = [...scripts.matchAll(/import\('\.\/(runtime\/[\w-]+\.mjs)\?v=' \+ encodeURIComponent\(version\)\)/g)].map(match => match[1]);
  assert.deepEqual([...new Set(imported)].sort(), [...manifest.modules].sort(), 'every import uses the preloaded URL');
  // The stylesheet loader still runs first; the preloads follow it in <head>.
  assert.ok(htmlSource.indexOf('rel="modulepreload"') > htmlSource.indexOf("link.rel = 'stylesheet'"));
  assert.ok(htmlSource.indexOf('rel="modulepreload"') < htmlSource.indexOf('</head>'));
  assert.match(readText('frontend/app-lifecycle.js'), /await Promise\.all\(\[\n\s+import\('\.\/runtime\/feature-lifecycle\.mjs/);
  assert.match(readText('frontend/app-resources.js'), /await Promise\.all\(\[\n\s+import\('\.\/runtime\/resource-store\.mjs/);
});
