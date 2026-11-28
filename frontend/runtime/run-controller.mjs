// Preserve the shell revision on transitive imports for offline/upgraded clients.
const { createFormOperations } = await import(new URL(
  './form-operations.mjs' + new URL(import.meta.url).search, import.meta.url));

// Run state and operation ownership; adapters inject transport, sessions and keys.
export function createRunController({ transport, session, newKey }) {
  const state = {
    rows: [], summary: null, offset: 0, hasMore: false, day: null,
    listRequest: 0, lastCreateResult: null, retryOptions: {},
  };
  const operations = createFormOperations(session);
  let pending = null, latest = null, retry = null, editor = null;
  const current = operations.current;
  return Object.freeze({
    state,
    get editor() { return editor; },
    get saving() { return pending !== null; },
    beginCreate(payload, form) {
      if (pending) return null;
      const fingerprint = JSON.stringify(payload);
      if (retry?.fingerprint !== fingerprint) retry = { fingerprint, key: newKey() };
      const operation = { ...operations.capture(form), retry };
      pending = latest = operation;
      return operation;
    },
    isCurrentCreate(operation) { return latest === operation && current(operation); },
    async submitCreate(operation, payload) {
      if (pending !== operation || !current(operation)) return false;
      try {
        const result = await transport.post('/runs', payload, { idempotencyKey: operation.retry.key });
        if (latest !== operation || !current(operation)) return false;
        state.lastCreateResult = result || null;
        retry = null;
        return true;
      } catch (error) {
        if (latest !== operation || !current(operation)) return false;
        throw error;
      }
    },
    finishCreate(operation) {
      if (pending !== operation) return false;
      pending = null;
      return true;
    },
    openEditor(run) { editor = { ...run, ...operations.capture() }; return editor; },
    closeEditor() { editor = null; },
    isCurrentEditor(snapshot) { return editor === snapshot && current(snapshot); },
    async saveEditor(snapshot, payload) {
      if (!current(snapshot)) return false;
      const saved = await transport.put('/runs/' + snapshot.id, payload);
      if (current(snapshot) && editor === snapshot && saved?.version !== undefined) snapshot.version = saved.version;
      return current(snapshot);
    },
    async deleteEditor(snapshot) {
      if (!current(snapshot)) return false;
      await transport.delete('/runs/' + snapshot.id + '?expected_version=' + (snapshot.version || 0));
      return current(snapshot);
    },
    reset() {
      operations.reset();
      pending = latest = retry = editor = null;
      Object.assign(state, { rows: [], summary: null, offset: 0, hasMore: false, day: null, retryOptions: {} });
      state.lastCreateResult = null;
      state.listRequest++;
    },
  });
}
