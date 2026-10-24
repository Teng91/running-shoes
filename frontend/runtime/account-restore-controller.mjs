// Session/revision ownership and transport; presentation stays in the bridge.
export function createAccountRestoreController({ session, transport, newKey }) {
  const state = { revision: 0, preview: null, operationId: null, pending: false, refreshRequired: false, refreshing: false };
  let previewSession = null, applying = null, committed = null, refreshing = null;
  const sessionCurrent = operation => !!operation && session.current(operation.session);
  const current = operation => sessionCurrent(operation) && operation.revision === state.revision;
  function release(preview, captured) {
    if (!preview) return;
    void Promise.resolve().then(() => {
      if (captured && session.current(captured)) return transport.discard(preview.token);
    }).catch(() => {}); // Expiration bounds storage if cleanup is interrupted.
  }
  function forget() {
    const previous = state.preview, captured = previewSession;
    state.preview = null; state.operationId = null; previewSession = null;
    committed = null; refreshing = null; state.refreshRequired = false; state.refreshing = false;
    if (previous !== applying?.preview) release(previous, captured);
  }
  return Object.freeze({
    state, current, sessionCurrent,
    reset() { state.revision++; forget(); applying = null; state.pending = false; },
    beginPreview() {
      if (state.pending) return null;
      forget(); state.revision++;
      return { revision: state.revision, session: session.capture() };
    },
    async preview(operation, raw, mode) {
      if (!current(operation)) return null;
      const preview = await transport.preview(raw, mode);
      if (!current(operation)) { release(preview, operation.session); return null; }
      state.preview = preview; state.operationId = newKey(); previewSession = operation.session;
      return preview;
    },
    beginApply() {
      if (!state.preview || state.pending) return null;
      applying = { revision: state.revision, session: session.capture(), preview: state.preview, operationId: state.operationId };
      state.pending = true;
      return applying;
    },
    ownsApply: operation => applying === operation && current(operation),
    async apply(operation) {
      if (applying !== operation || !current(operation)) return false;
      await transport.apply(operation.preview.token, operation.operationId);
      if (applying === operation && current(operation)) {
        state.preview = null; state.operationId = null; previewSession = null;
        committed = operation; state.refreshRequired = true;
      }
      return true;
    },
    beginRefresh() {
      if (!state.refreshRequired || state.refreshing || !current(committed)) return null;
      refreshing = committed; state.refreshing = true;
      return refreshing;
    },
    ownsRefresh: operation => refreshing === operation && current(operation),
    async refresh(operation) {
      if (refreshing !== operation || !current(operation)) return false;
      await transport.refresh();
      if (refreshing !== operation || !current(operation)) return false;
      state.refreshRequired = false;
      return true;
    },
    finishRefresh(operation) {
      if (refreshing !== operation) return;
      refreshing = null; state.refreshing = false;
    },
    finishApply(operation) {
      if (applying !== operation) return false;
      applying = null; state.pending = false;
      return true;
    },
  });
}
