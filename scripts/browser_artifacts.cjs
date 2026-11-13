// Shared harness diagnostics: only synthetic contexts or anonymous release checks.
const fs = require('node:fs');
const path = require('node:path');

function withDeadline(action, timeoutMs, label) {
  let timer;
  const expired = new Promise((_, reject) => {
    timer = setTimeout(() => {
      const error = new Error(`${label} exceeded ${timeoutMs} ms`);
      error.name = 'BrowserDeadlineError';
      reject(error);
    }, timeoutMs);
  });
  return Promise.race([Promise.resolve().then(action), expired]).finally(() => clearTimeout(timer));
}

async function startArtifacts(context) {
  await withDeadline(() => context.tracing.start({ screenshots: true, snapshots: true, sources: true }), 10000, 'start trace');
}

async function saveFailure(context, page, label, error, { timeoutMs = 5000 } = {}) {
  const directory = path.resolve(process.env.BROWSER_ARTIFACT_DIR || '.artifacts/browser');
  const stem = label.replace(/[^a-zA-Z0-9_-]/g, '-') + '-' + Date.now();
  try {
    fs.mkdirSync(directory, { recursive: true });
    // Preserve the original error even if screenshot/trace IPC never settles.
    fs.writeFileSync(path.join(directory, stem + '.txt'), String(error.stack || error));
    await Promise.allSettled([
      withDeadline(() => page?.screenshot({ path: path.join(directory, stem + '.png'), fullPage: true, timeout: timeoutMs }), timeoutMs, 'failure screenshot'),
      withDeadline(() => context?.tracing.stop({ path: path.join(directory, stem + '.zip') }), timeoutMs, 'failure trace'),
    ]);
    console.error('Browser failure artifacts:', directory, stem);
    return { directory, stem };
  } catch { console.error('Could not save browser failure artifacts.'); }
}

// SPEC-054: report Content-Security-Policy violations from every page and
// navigation in the context, so a blocked inline script or asset fails a check
// instead of silently degrading the page.
async function trackCspViolations(context) {
  const violations = [];
  await context.exposeBinding('__reportCspViolation', (_source, detail) => violations.push(detail));
  await context.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', event => {
      window.__reportCspViolation(`${event.effectiveDirective || event.violatedDirective} blocked ${event.blockedURI || 'inline'} (${event.sourceFile || location.pathname}:${event.lineNumber})`);
    });
  });
  return violations;
}

async function closeBrowser(context, browser, { timeoutMs = 5000 } = {}) {
  const errors = [];
  for (const [label, target] of [['context close', context], ['browser close', browser]]) {
    if (!target) continue;
    try { await withDeadline(() => target.close(), timeoutMs, label); }
    catch (error) { errors.push(error); }
  }
  if (errors.length) throw new AggregateError(errors, 'Browser cleanup failed');
}

module.exports = { withDeadline, startArtifacts, saveFailure, closeBrowser, trackCspViolations };
