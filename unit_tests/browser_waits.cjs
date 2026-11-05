// Playwright's page.waitForFunction does not await a Promise returned by the predicate:
// an async predicate is a truthy Promise, so the wait resolves immediately. Poll with
// page.evaluate (which awaits) for page state that needs IndexedDB, service workers, etc.
async function waitForAsync(page, predicate, arg = null, { timeout = 30000, interval = 50, describe = null } = {}) {
  const deadline = Date.now() + timeout;
  let lastError = null;
  for (;;) {
    try {
      if (await page.evaluate(predicate, arg)) return;
      lastError = null;
    } catch (error) {
      // A navigation can destroy the execution context mid-poll; retry until the deadline.
      if (!/Execution context was destroyed|Target closed|navigation/i.test(String(error?.message))) throw error;
      lastError = error;
    }
    if (Date.now() >= deadline) {
      let state = '';
      if (describe) {
        try { state = ' state=' + JSON.stringify(await page.evaluate(describe, arg)); }
        catch (error) { state = ' state unavailable: ' + error.message; }
      }
      throw new Error(`waitForAsync: Timeout ${timeout}ms exceeded` + (lastError ? ` (${lastError.message})` : '') + state);
    }
    await new Promise(resolve => setTimeout(resolve, interval));
  }
}

module.exports = { waitForAsync };
