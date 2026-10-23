// Serializable browser observer; also exercised with deterministic worker objects in Node.
async function observeWorkerUpdate({ registration, timeoutMs = 15000, trigger = true } = {}) {
  const reg = registration || await navigator.serviceWorker.getRegistration();
  if (!reg) throw Error('Missing service worker registration');
  const events = [], listeners = new Map();
  globalThis.__workerUpdateTimeline = events;
  const snapshot = phase => {
    const value = { phase, installing: reg.installing?.state || null, waiting: reg.waiting?.state || null,
      active: reg.active?.state || null };
    events.push(value);
    return value;
  };
  let timer, found, complete, candidate = null, updateDone = !trigger;
  const finished = new Promise(resolve => {
    complete = () => {
      if (updateDone && candidate && ['activated', 'redundant'].includes(candidate.state)) resolve(candidate.state);
    };
    const watch = worker => {
      if (!worker) return;
      candidate = worker;
      if (listeners.has(worker)) return;
      const changed = () => { snapshot('candidate:' + worker.state); complete(); };
      listeners.set(worker, changed); worker.addEventListener('statechange', changed); changed();
    };
    found = () => { snapshot('updatefound'); watch(reg.installing || reg.waiting); };
    reg.addEventListener('updatefound', found);
    snapshot('observe'); watch(reg.installing || reg.waiting);
  });
  try {
    const update = trigger ? reg.update().then(() => {
      snapshot('update-returned');
      // An older background candidate may have finished while update() was
      // queued. Select the latest candidate before allowing completion.
      found(); updateDone = true; complete();
    }) : Promise.resolve();
    // A single deadline also bounds registration.update(), even after a terminal state.
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error('worker update timed out')), timeoutMs);
    });
    const [, state] = await Promise.race([Promise.all([update, finished]), deadline]);
    return state;
  } catch (error) {
    snapshot('failure');
    error.message += '\nWorker registration timeline: ' + JSON.stringify(events);
    throw error;
  } finally {
    clearTimeout(timer); reg.removeEventListener('updatefound', found);
    for (const [worker, listener] of listeners) worker.removeEventListener('statechange', listener);
  }
}
module.exports = { observeWorkerUpdate };
