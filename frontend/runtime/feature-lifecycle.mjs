// Native ES module: no DOM, storage, application globals, or feature imports.
export function createLifecycle(onError = () => {}) {
  const features = new Map();
  return Object.freeze({
    register(name, reset) {
      if (!name || typeof reset !== 'function') throw new TypeError('Feature reset must be named and callable');
      if (features.has(name)) throw new Error(`Duplicate lifecycle feature: ${name}`);
      features.set(name, reset);
      return () => features.delete(name);
    },
    reset() {
      // Continue after one failed cleanup so unrelated private state is still cleared.
      const failed = [];
      for (const [name, reset] of [...features]) {
        try { reset(); } catch { failed.push(name); onError(name); }
      }
      return failed;
    },
    names() { return [...features.keys()]; },
  });
}
