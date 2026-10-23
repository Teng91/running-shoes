const { test, assert, fs } = require('./helpers.cjs');
const os = require('node:os'), path = require('node:path');
const { withDeadline, saveFailure, closeBrowser } = require('../../scripts/browser_artifacts.cjs');

test('SPEC-024 stuck capture and cleanup preserve the error and finish within deadlines', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'rs-deadline-'));
  const previous = process.env.BROWSER_ARTIFACT_DIR; process.env.BROWSER_ARTIFACT_DIR = directory;
  const stuck = () => new Promise(() => {}); let closed = false;
  try {
    const saving = saveFailure({ tracing: { stop: stuck } }, { screenshot: stuck }, 'stuck', Error('original synthetic failure'), { timeoutMs: 20 });
    // The error is persisted before waiting for either stuck browser IPC.
    const file = fs.readdirSync(directory).find(name => name.endsWith('.txt'));
    assert.match(fs.readFileSync(path.join(directory, file), 'utf8'), /original synthetic failure/);
    const result = await saving; assert.ok(result.stem);
    await assert.rejects(closeBrowser({ close: stuck }, { close: async () => { closed = true; } }, { timeoutMs: 20 }), AggregateError);
    assert.equal(closed, true, 'browser close still runs after context deadline');
  } finally {
    if (previous === undefined) delete process.env.BROWSER_ARTIFACT_DIR; else process.env.BROWSER_ARTIFACT_DIR = previous;
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('SPEC-024 browser stages reject hangs and propagate ordinary failures', async () => {
  await assert.rejects(withDeadline(() => new Promise(() => {}), 20, 'synthetic stage'), { name: 'BrowserDeadlineError' });
  await assert.rejects(withDeadline(() => { throw Error('synthetic failure'); }, 100, 'stage'), /synthetic failure/);
  assert.equal(await withDeadline(() => 42, 100, 'stage'), 42);
});
