// Run state and operation ownership; adapters inject transport, sessions and keys.
export function createRunController({ transport, session, newKey }) {
  const state = {
    rows: [], summary: null, offset: 0, hasMore: false, day: null,
    listRequest: 0, annualRequest: 0, annualCache: new Map(), retryOptions: {},
  };
  let epoch = 0, pending = null, latest = null, retry = null, editor = null;
  const current = operation => operation && operation.epoch === epoch && session.current(operation.session);
  return Object.freeze({
    state,
    get editor() { return editor; },
    get saving() { return pending !== null; },
    beginCreate(payload, form) {
      if (pending) return null;
      const fingerprint = JSON.stringify(payload);
      if (retry?.fingerprint !== fingerprint) retry = { fingerprint, key: newKey() };
      const operation = { epoch, session: session.capture(), retry, form };
      pending = latest = operation;
      return operation;
    },
    isCurrentCreate(operation) { return latest === operation && current(operation); },
    async submitCreate(operation, payload) {
      if (pending !== operation || !current(operation)) return false;
      try {
        await transport.post('/runs', payload, { idempotencyKey: operation.retry.key });
        if (latest !== operation || !current(operation)) return false;
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
    openEditor(run) { editor = { ...run, epoch, session: session.capture() }; return editor; },
    closeEditor() { editor = null; },
    isCurrentEditor(snapshot) { return editor === snapshot && current(snapshot); },
    async saveEditor(snapshot, payload) {
      if (!current(snapshot)) return false;
      await transport.put('/runs/' + snapshot.id, payload);
      return current(snapshot);
    },
    async deleteEditor(snapshot) {
      if (!current(snapshot)) return false;
      await transport.delete('/runs/' + snapshot.id + '?expected_version=' + (snapshot.version || 0));
      return current(snapshot);
    },
    reset() {
      epoch++;
      pending = latest = retry = editor = null;
      Object.assign(state, { rows: [], summary: null, offset: 0, hasMore: false, day: null, retryOptions: {} });
      state.annualCache.clear();
      state.listRequest++;
      state.annualRequest++;
    },
  });
}
