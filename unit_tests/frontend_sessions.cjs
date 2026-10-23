// Real DOM and application code, synthetic sessions and deterministic fetch/SSE.
// Never authenticates against, writes to, or calls an external account/model.
const assert = require('node:assert/strict');
const { startArtifacts, saveFailure, closeBrowser } = require('../scripts/browser_artifacts.cjs');

module.exports = async function checkSessionIsolation(browser, baseUrl) {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  await startArtifacts(context);
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  try {
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    const result = await page.evaluate(async () => {
      const check = (condition, message) => { if (!condition) throw new Error(message); };
      const tick = () => new Promise(resolve => setTimeout(resolve, 0));
      const json = body => new Response(JSON.stringify(body), {
        headers: { 'Content-Type': 'application/json' },
      });
      const insights = document.getElementById('dashboard-insights');
      setAuth('synthetic-A', 'user-A');
      window.fetch = async () => json({ recent_7_days: { km: 123.45 } });
      await loadDashboardAnalytics(selectedRunMonth());
      check(insights.textContent.includes('123.45'), 'A insights were rendered');
      check(dashboardAnalyticsCache.size > 0, 'A insights were cached');
      handleLogout();
      check(dashboardAnalyticsCache.size === 0, 'logout clears insight cache');
      check(insights.textContent === '', 'logout clears insight DOM');
      setAuth('synthetic-B', 'user-B');
      window.fetch = async () => new Response('{}', { status: 503 });
      showAppView();
      await loadData();
      check(!document.getElementById('data-load-error').hidden, 'failed B load is visible');
      check(!insights.textContent.includes('123.45'), 'failed B load cannot show A insights');

      setAuth('synthetic-A', 'user-A');
      let finishAnalytics;
      window.fetch = () => new Promise(resolve => { finishAnalytics = resolve; });
      const analytics = loadDashboardAnalytics(selectedRunMonth());
      await tick();
      setAuth('synthetic-B', 'user-B');
      finishAnalytics(json({ recent_7_days: { km: 987.65 } }));
      await analytics;
      check(!insights.textContent.includes('987.65'), 'late A analytics cannot render');
      check(dashboardAnalyticsCache.size === 0, 'late A analytics cannot refill cache');

      setAuth('synthetic-A', 'user-A');
      let oldSignal, oldStream, oldCancelled = false;
      window.fetch = async (_, options) => {
        oldSignal = options.signal;
        return new Response(new ReadableStream({ start(controller) { oldStream = controller; }, cancel() { oldCancelled = true; } }), {
          headers: { 'Content-Type': 'text/event-stream' },
        });
      };
      const input = document.getElementById('agent-input');
      input.value = 'private question A';
      const oldChat = sendAgentMessage();
      await tick();
      check(input.disabled, 'chat locks input while streaming');
      handleLogout();
      check(oldSignal.aborted, 'logout aborts the actual fetch signal');
      check(!input.disabled && lastUserText === '', 'logout clears retry and unlocks input');
      check(agentHistory.length === 0, 'logout clears chat history');
      setAuth('synthetic-B', 'user-B');
      let newStream;
      window.fetch = async () => new Response(new ReadableStream({
        start(controller) { newStream = controller; },
      }), { headers: { 'Content-Type': 'text/event-stream' } });
      input.value = 'question B';
      const newChat = sendAgentMessage();
      await tick();
      const token = text => new TextEncoder().encode(`data: ${JSON.stringify({ type: 'token', text })}\n\n`);
      // Deliberately ignore cancellation in the fake transport: generation checks
      // must protect B even if A's stream still resolves after its signal aborts.
      if (!oldCancelled) {
        oldStream.enqueue(token('private answer A'));
        oldStream.close();
      }
      await oldChat;
      check(input.disabled, 'old completion cannot unlock the new chat');
      check(agentHistory.length === 0, 'old completion cannot refill history');
      check(lastUserText === 'question B', 'old completion cannot restore retry text');
      check(!document.querySelector('.agent-retry-btn'), 'old completion cannot add retry UI');
      check(!document.getElementById('agent-messages').textContent.includes('private'), 'no A chat remains');
      newStream.enqueue(token('answer B'));
      newStream.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
      newStream.close();
      await newChat;
      check(!input.disabled, 'new chat completes normally');
      check(JSON.stringify(agentHistoryForRequest()) === JSON.stringify([
        { role: 'user', content: 'question B' }, { role: 'assistant', content: 'answer B' },
      ]), 'only B history is sent on the next request');

      setAuth('synthetic-A', 'user-A');
      let finish401;
      window.fetch = () => new Promise(resolve => { finish401 = resolve; });
      const oldRequest = apiGet('/synthetic-test').catch(error => error.name);
      setAuth('synthetic-B', 'user-B');
      finish401(new Response('{}', { status: 401 }));
      check(await oldRequest === 'AbortError', 'old 401 is discarded');
      check(authToken === 'synthetic-B' && currentUser === 'user-B', 'old 401 preserves B login');
      window.fetch = async () => new Response('{}', { status: 401 });
      await apiGet('/synthetic-test').catch(() => {});
      check(authToken === null, 'current 401 still logs out');
      check(document.getElementById('app-view').style.display === 'none', 'current 401 hides app');
      return { dashboard: true, streaming: true, authentication: true };
    });
    assert.deepEqual(result, { dashboard: true, streaming: true, authentication: true });
    assert.deepEqual(pageErrors, [], 'session isolation browser JavaScript errors');
    console.log(`PASS ${browser.browserType().name()} session isolation: stale analytics, failed account load, aborted/late chat, stale/current 401`);
  } catch (error) {
    await saveFailure(context, page, 'sessions-' + browser.browserType().name(), error);
    throw error;
  } finally {
    await closeBrowser(context);
  }
};
