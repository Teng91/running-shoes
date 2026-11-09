#!/usr/bin/env node
// Exit 0 only when the pinned Chromium and WebKit can actually start on this host.
// Downloaded binaries are not enough: Linux hosts also need system libraries
// (`npx playwright install-deps`). The last stderr line explains a failure.
const fs = require('node:fs');

let playwright;
try {
  playwright = require('playwright');
} catch {
  console.error('Playwright is not installed; run npm ci.');
  process.exit(1);
}

(async () => {
  for (const name of ['chromium', 'webkit']) {
    const browserType = playwright[name];
    if (!fs.existsSync(browserType.executablePath())) {
      console.error(`${name} binary is not installed; run npx playwright install chromium webkit.`);
      process.exit(1);
    }
    try {
      const browser = await browserType.launch({ timeout: 30000 });
      await browser.close();
    } catch (error) {
      const text = String(error && error.message || error);
      console.error(/missing dependencies|error while loading shared libraries/i.test(text)
        ? `${name} cannot start: host system libraries are missing; run sudo npx playwright install-deps chromium webkit.`
        : `${name} cannot start: ${text.split('\n').find(line => line.trim()) || 'unknown error'}`);
      process.exit(1);
    }
  }
})();
