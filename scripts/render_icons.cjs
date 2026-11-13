#!/usr/bin/env node
// Rasterize frontend/icons/app-icon.svg into the PWA and iOS home-screen PNGs with Playwright Chromium.
// Usage: node scripts/render_icons.cjs [output-dir]   (PLAYWRIGHT_CHROMIUM_CHANNEL=chrome uses installed Chrome)
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ICONS = path.resolve(__dirname, '..', 'frontend', 'icons');
const TARGETS = [['icon-512.png', 512], ['icon-192.png', 192], ['apple-touch-icon.png', 180]];

async function main() {
  const outDir = path.resolve(process.argv[2] || ICONS);
  const svg = fs.readFileSync(path.join(ICONS, 'app-icon.svg'), 'utf8');
  const channel = process.env.PLAYWRIGHT_CHROMIUM_CHANNEL;
  const browser = await chromium.launch({ headless: true, timeout: 30000, ...(channel ? { channel } : {}) });
  try {
    for (const [name, size] of TARGETS) {
      // Render the vector at each target size instead of downscaling one bitmap.
      const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
      await page.setContent(`<!doctype html><style>html,body{margin:0;background:#07090c}`
        + `svg{display:block;width:${size}px;height:${size}px}</style>${svg}`);
      await page.screenshot({ path: path.join(outDir, name), clip: { x: 0, y: 0, width: size, height: size } });
      await page.close();
      console.log(`${name} ${size}x${size}`);
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
