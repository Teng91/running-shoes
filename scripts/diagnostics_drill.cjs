// Intentional, caught browser assertion. No server, accounts, network or credentials.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const { startArtifacts, saveFailure, closeBrowser } = require('./browser_artifacts.cjs');

async function main() {
  const directory = path.resolve('.artifacts/browser/roundtrip');
  process.env.BROWSER_ARTIFACT_DIR = directory;
  const browser = await chromium.launch({ headless: true, timeout: 30000 });
  try {
    const context = await browser.newContext();
    await startArtifacts(context);
    const page = await context.newPage();
    const marker = 'SPEC023_SYNTHETIC_DIAGNOSTIC';
    await page.setContent(`<html><body><h1>${marker}</h1><p>Synthetic browser diagnostics exercise</p></body></html>`);
    let failure;
    try { assert.equal(await page.locator('h1').textContent(), 'intentional mismatch', marker); }
    catch (error) { failure = error; }
    assert.ok(failure, 'the synthetic assertion must fail');
    const saved = await saveFailure(context, page, 'synthetic-roundtrip', failure);
    assert.ok(saved, 'diagnostics capture must complete');
    const files = ['png', 'zip', 'txt'].map(extension => {
      const name = saved.stem + '.' + extension;
      const bytes = fs.readFileSync(path.join(directory, name));
      return { name, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
    });
    fs.writeFileSync(path.join(directory, 'manifest.json'), JSON.stringify({ format: 'synthetic-browser-diagnostics-v1', marker, files }, null, 2));
    console.log('Synthetic failure captured:', files.map(file => file.name).join(', '));
    await closeBrowser(context);
  } finally { await closeBrowser(null, browser); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
