// Native operation ownership. Closing UI does not imply rolling back a committed upload.
export function createStravaController({ session, transport }) {
  let windowId = 0, revision = 0, previewOperation = null, importOperation = null;
  const state = { preview: null, key: '' };
  const sessionCurrent = operation => operation && session.current(operation.session);
  const current = operation => sessionCurrent(operation)
    && operation.windowId === windowId && operation.revision === revision;
  function clearPreview() {
    previewOperation?.controller.abort(); previewOperation = null;
    revision++; state.preview = null; state.key = '';
  }
  function close() { windowId++; clearPreview(); importOperation = null; }
  return Object.freeze({
    state, current, sessionCurrent, close, open: close, reset: close,
    windowCurrent: operation => sessionCurrent(operation) && operation.windowId === windowId,
    preview: (operation, file, fields) => transport.upload('/runs/import/strava/preview', file, fields, operation.controller.signal),
    import: (operation, file, fields) => {
      if (importOperation !== operation || !current(operation)) throw new Error('Inactive Strava operation');
      return transport.upload('/runs/import/strava', file, fields);
    },
    beginPreview() {
      clearPreview();
      const operation = { windowId, revision, session: session.capture(), controller: new AbortController() };
      previewOperation = operation;
      return operation;
    },
    acceptPreview(operation, preview, key) {
      if (!current(operation)) return false;
      state.preview = preview; state.key = key;
      return true;
    },
    finishPreview(operation) { if (previewOperation === operation) previewOperation = null; },
    beginImport(key) {
      if (!state.preview || key !== state.key || importOperation) return null;
      importOperation = { windowId, revision, session: session.capture() };
      return importOperation;
    },
    ownsImport: operation => importOperation === operation && current(operation),
    finishImport(operation) { if (importOperation === operation) importOperation = null; },
    importing: () => Boolean(importOperation),
  });
}
