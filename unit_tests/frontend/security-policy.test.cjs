const crypto = require('node:crypto');
const os = require('node:os');
const { test, assert, fs, path, vm, htmlSource, scriptSource, readText } = require('./helpers.cjs');
const { trackCspViolations } = require('../../scripts/browser_artifacts.cjs');

function pagePolicy(html) {
  const meta = html.match(/<meta http-equiv="Content-Security-Policy" content="([^"]+)">/);
  assert.ok(meta, 'the page declares a Content-Security-Policy');
  return {
    index: meta.index,
    directives: new Map(meta[1].split(';').map(part => part.trim().split(/\s+/)).map(([name, ...values]) => [name, values])),
  };
}

const inlineScripts = html => [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
const sha256 = text => `'sha256-${crypto.createHash('sha256').update(text, 'utf8').digest('base64')}'`;

test('SPEC-054 the shell CSP allows inline scripts only by the hash of their exact text', () => {
  const { index, directives } = pagePolicy(htmlSource);
  assert.ok(index < htmlSource.indexOf('<script'), 'the policy is declared before the first script');
  const scripts = inlineScripts(htmlSource);
  assert.equal(scripts.length, 3, 'theme bootstrap, stylesheet loader and boot watchdog');
  const scriptSources = directives.get('script-src');
  assert.deepEqual(scriptSources.filter(value => !value.startsWith("'sha256-")), ["'self'"]);
  assert.deepEqual(scriptSources.filter(value => value.startsWith("'sha256-")).sort(), scripts.map(sha256).sort());
  for (const value of ["'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'", '*', 'data:', 'http:', 'https:']) {
    assert.ok(!scriptSources.includes(value), `script-src must not allow ${value}`);
  }
  assert.deepEqual(directives.get('default-src'), ["'self'"]);
  assert.deepEqual(directives.get('connect-src'), ["'self'"]);
  assert.deepEqual(directives.get('object-src'), ["'none'"]);
  assert.deepEqual(directives.get('base-uri'), ["'none'"]);
  assert.deepEqual(directives.get('frame-src'), ["'none'"]);
  // Browsers ignore frame-ancestors in <meta>; the server header carries it.
  assert.equal(directives.has('frame-ancestors'), false);
  for (const tag of htmlSource.match(/<script\b[^>]*>/g)) {
    assert.ok(tag === '<script>' || /^<script src="\/[^"]+"><\/?/.test(tag + '<'), `same-origin script only: ${tag}`);
  }
});

test('SPEC-054 markup, generated rows and the offline page carry no inline handlers or javascript: URLs', () => {
  const handler = /\son[a-z]+\s*=/gi;
  assert.deepEqual(htmlSource.match(handler) || [], []);
  assert.deepEqual(scriptSource.match(/\son[a-z]+=["'`$]/gi) || [], []);
  assert.doesNotMatch(htmlSource, /href="javascript:/i);
  const offline = readText('frontend/offline.html');
  assert.deepEqual(offline.match(handler) || [], []);
  assert.doesNotMatch(offline, /<script/i, 'the offline page needs no script');
  const { directives } = pagePolicy(offline);
  assert.deepEqual(directives.get('default-src'), ["'none'"]);
  assert.equal(directives.has('script-src'), false, 'scripts fall back to default-src none');
  assert.match(offline, /<a class="retry" href="">重新連線<\/a>/, 'an empty link reloads the page without script');
});

function runStylesheetLoader({ finishedBeforeScript }) {
  const loader = inlineScripts(htmlSource).find(script => script.includes("getElementById('app-styles')"));
  assert.ok(loader, 'the stylesheet loader is an inline script');
  const href = 'http://localhost/styles.css?v=1';
  const listeners = [];
  const link = { rel: 'preload', href, dataset: {}, addEventListener: (type, listener) => { if (type === 'load') listeners.push(listener); } };
  const dispatched = [];
  class Event { constructor(type) { this.type = type; } }
  const context = {
    Event,
    document: { getElementById: id => (id === 'app-styles' ? link : null) },
    performance: { getEntriesByName: name => (finishedBeforeScript && name === href ? [{ responseEnd: 12 }] : []) },
    window: { dispatchEvent: event => dispatched.push(event.type) },
  };
  vm.runInNewContext(loader, context);
  return { link, dispatched, fireLoad: () => listeners.forEach(listener => listener()) };
}

test('SPEC-054 the stylesheet loader applies the preload exactly once, even if its load event already fired', () => {
  const pending = runStylesheetLoader({ finishedBeforeScript: false });
  assert.equal(pending.link.rel, 'preload', 'nothing is applied before the preload arrives');
  assert.deepEqual(pending.dispatched, []);
  pending.fireLoad();
  assert.equal(pending.link.rel, 'stylesheet');
  assert.equal(pending.link.dataset.ready, 'true');
  pending.fireLoad(); // switching rel to stylesheet fires load again
  assert.deepEqual(pending.dispatched, ['appstylesready']);

  const missed = runStylesheetLoader({ finishedBeforeScript: true });
  assert.equal(missed.link.rel, 'stylesheet', 'a finished preload is applied without waiting for an event');
  assert.equal(missed.link.dataset.ready, 'true');
  missed.fireLoad();
  assert.deepEqual(missed.dispatched, ['appstylesready']);
});

test('SPEC-054 every real-browser check fails on a Content-Security-Policy violation', async () => {
  const bindings = new Map();
  const initScripts = [];
  const context = {
    exposeBinding: async (name, callback) => bindings.set(name, callback),
    addInitScript: async script => initScripts.push(script),
  };
  const violations = await trackCspViolations(context);
  assert.equal(initScripts.length, 1);
  const listeners = [];
  const page = {
    document: { addEventListener: (type, listener) => listeners.push([type, listener]) },
    location: { pathname: '/' },
    __reportCspViolation: detail => bindings.get('__reportCspViolation')({}, detail),
  };
  page.window = page;
  vm.runInNewContext(`(${initScripts[0]})()`, page);
  assert.deepEqual(listeners.map(([type]) => type), ['securitypolicyviolation']);
  listeners[0][1]({ effectiveDirective: 'script-src-elem', blockedURI: 'inline', sourceFile: '', lineNumber: 7 });
  assert.deepEqual(violations, ['script-src-elem blocked inline (/:7)']);

  for (const file of ['unit_tests/frontend_e2e.cjs', 'unit_tests/frontend_layout.cjs', 'scripts/release_browser.cjs']) {
    const source = readText(file);
    assert.match(source, /const cspViolations = await trackCspViolations\(/, `${file} tracks violations`);
    assert.match(source, /assert\.deepEqual\(cspViolations, \[\], 'Content-Security-Policy violations \(SPEC-054\)'\)/, `${file} fails on them`);
  }
});

test('SPEC-053 shared test sources are read with LF line endings on every platform', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'running-shoes-crlf-'));
  try {
    const file = path.join(directory, 'sample.html');
    fs.writeFileSync(file, '<link>\r\n<script>\r\n</script>\r\n');
    assert.equal(readText(file), '<link>\n<script>\n</script>\n');
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
  assert.equal(htmlSource.includes('\r'), false);
  assert.equal(scriptSource.includes('\r'), false);
});
