// Resource ownership and caches are independent of DOM, transport and auth storage.
export function dataRefreshPolicy(mutation) {
  const policies = { monthly: ['monthly'], shoe: ['shoes'],
    run: ['shoes', 'monthly', 'runs'], strava: ['shoes', 'monthly', 'runs'] };
  if (mutation && !policies[mutation]) throw new Error('Unknown mutation: ' + mutation);
  return { resources: [...(policies[mutation] || ['shoes', 'monthly', 'runs', 'goal'])],
    history: !mutation || mutation === 'strava' };
}

export function createResourceStore({ session }) {
  const records = new Map(), errors = new Map(), cacheHooks = new Map();
  let epoch = 0;
  const current = result => result && result.ticket.epoch === epoch
    && records.get(result.resource) === result.ticket && session.current(result.ticket.session);
  function invalidate(resources) {
    for (const resource of resources) { records.delete(resource); errors.delete(resource); }
  }
  function read(resource, { key = '', loader, refresh = true }) {
    const previous = records.get(resource);
    if (previous?.key === key && session.current(previous.session)) {
      if (previous.pending) return previous.pending;
      if (!refresh && previous.result?.status === 'fulfilled') return Promise.resolve(previous.result);
    }
    const ticket = { key, epoch, session: session.capture(), consumed: false };
    records.set(resource, ticket);
    // Deferring loader also coalesces calls made in the same synchronous turn.
    const promise = Promise.resolve().then(() => {
      // Dispatch in the same captured session even when auth changes before
      // this microtask. A discarded read must never borrow a new account token.
      if (ticket.epoch !== epoch || records.get(resource) !== ticket || !session.current(ticket.session)) {
        throw Object.assign(new Error('Resource owner expired'), { name: 'AbortError' });
      }
      return loader();
    }).then(
      value => ({ resource, key, ticket, status: 'fulfilled', value }),
      error => ({ resource, key, ticket, status: 'rejected', error }),
    ).then(result => {
      ticket.pending = null;
      ticket.result = result;
      if (current(result)) {
        if (result.status === 'rejected') errors.set(resource, { session: ticket.session, error: result.error });
        else errors.delete(resource);
      }
      return result;
    });
    ticket.pending = promise;
    return promise;
  }
  return Object.freeze({
    read, current, invalidate, policy: dataRefreshPolicy,
    peek(resource) {
      const result = records.get(resource)?.result;
      return result?.status === 'fulfilled' && current(result) ? result.value : undefined;
    },
    async refresh(mutation, readers, keys = {}, onResult = () => {}) {
      const policy = dataRefreshPolicy(mutation);
      if (mutation) invalidate(policy.resources);
      return Promise.all(policy.resources.map(resource => read(resource, {
        key: keys[resource] || '', loader: readers[resource],
      }).then(result => { onResult(result); return result; })));
    },
    accept(results, mutation = null) {
      const accepted = results.filter(result => current(result) && !result.ticket.consumed);
      const invalidations = new Set();
      for (const result of accepted) {
        result.ticket.consumed = true;
        if (result.status !== 'fulfilled') continue;
        if (result.resource === 'shoes') {
          invalidations.add('dashboard');
          if (!mutation || mutation === 'shoe') invalidations.add('spending');
        }
        if (result.resource === 'runs' || result.resource === 'goal') {
          invalidations.add('goal'); invalidations.add('dashboard');
        }
        if (result.resource === 'runs') invalidations.add('annual');
      }
      for (const name of invalidations) cacheHooks.get(name)?.();
      return accepted;
    },
    hasErrors: () => [...errors.values()].some(entry => session.current(entry.session)),
    getError(resource) {
      const entry = errors.get(resource);
      return entry && session.current(entry.session) ? entry.error : undefined;
    },
    registerCache(name, invalidateCache) { cacheHooks.set(name, invalidateCache); },
    reset() { epoch++; records.clear(); errors.clear(); },
  });
}
