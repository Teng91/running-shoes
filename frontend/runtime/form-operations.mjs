// DOM-independent operation identity, session ownership and draft snapshots.
export function matchesSnapshot(expected, actual) {
  return Object.entries(expected).every(([key, value]) =>
    JSON.stringify(value) === JSON.stringify(actual[key]));
}

export function createFormOperations(session) {
  let epoch = 0;
  const pending = new Map(), latest = new Map();
  const current = operation => !!operation && operation.epoch === epoch && session.current(operation.session);
  return Object.freeze({
    capture: (form = {}) => ({ epoch, session: session.capture(), form: structuredClone(form) }),
    current,
    begin(key, form = {}) {
      if (pending.has(key)) return null;
      const operation = this.capture(form);
      pending.set(key, operation);
      latest.set(key, operation);
      return operation;
    },
    owns: (key, operation) => latest.get(key) === operation && current(operation),
    finish(key, operation) {
      if (pending.get(key) !== operation) return false;
      pending.delete(key);
      if (latest.get(key) === operation) latest.delete(key);
      return true;
    },
    reset() { epoch++; pending.clear(); latest.clear(); },
  });
}

// Baselines describe acknowledged server values; current values belong to the user.
export function createFormDraft() {
  let baseline = null;
  const merge = (server, current, previous) => {
    const values = Object.fromEntries(Object.entries(server).map(([key, value]) =>
      [key, previous && current[key] !== previous[key] ? current[key] : value]));
    baseline = { ...server };
    return values;
  };
  return Object.freeze({
    reconcile: (server, current) => merge(server, current, baseline),
    acknowledge: (server, sent, current) => merge(server, current, sent),
    reset() { baseline = null; },
  });
}
