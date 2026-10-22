// Shared harness diagnostics: only synthetic contexts or anonymous release checks.
const fs = require('node:fs');
const path = require('node:path');

async function startArtifacts(context) {
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
}

async function saveFailure(context, page, label, error) {
  const directory = path.resolve(process.env.BROWSER_ARTIFACT_DIR || '.artifacts/browser');
  const stem = label.replace(/[^a-zA-Z0-9_-]/g, '-') + '-' + Date.now();
  try {
    fs.mkdirSync(directory, { recursive: true });
    await page?.screenshot({ path: path.join(directory, stem + '.png'), fullPage: true, timeout: 5000 }).catch(() => {});
    await context?.tracing.stop({ path: path.join(directory, stem + '.zip') }).catch(() => {});
    fs.writeFileSync(path.join(directory, stem + '.txt'), String(error.stack || error));
    console.error('Browser failure artifacts:', directory, stem);
    return { directory, stem };
  } catch { console.error('Could not save browser failure artifacts.'); }
}

module.exports = { startArtifacts, saveFailure };
