// Account partitions, durable drafts and an at-least-once queue with atomic leases.
// Storage and transport are injected; no browser globals or credentials are stored.
// attach(account, isLegacy) first moves older partitions of the same account in (SPEC-129).
export function createWorkspaceController({ storage, session, clock, newKey, send, changed = () => {}, committed = () => {} }) {
  let owner = null, generation = 0;
  const valid = ticket => owner === ticket && ticket && session.current(ticket.session);
  const key = (account, kind, id = 'current') => [account, kind, id];
  const notify = ticket => { if (valid(ticket)) changed(); };
  const deps = { storage, clock, newKey, send, committed };
  async function read(kind) {
    const ticket = owner;
    if (!valid(ticket)) return [];
    const rows = await storage.list(ticket.account, kind);
    return valid(ticket) ? rows : [];
  }
  async function flush() {
    const ticket = owner;
    if (!valid(ticket)) return { synced: 0 };
    let synced = 0;
    for (const item of await storage.list(ticket.account, 'queue')) {
      if (!valid(ticket)) break;
      const outcome = await syncQueueItem(deps, ticket, item, valid);
      if (outcome === 'synced') synced++;
      if (outcome === 'blocked' || outcome === 'stop') notify(ticket);
      if (outcome === 'stop') break;
    }
    notify(ticket);
    return { synced };
  }
  let flushing = null;
  return Object.freeze({
    get account() { return valid(owner) ? owner.account : null; },
    async attach(account, isLegacy = null) {
      const ticket = { account, session: session.capture(), generation: ++generation };
      owner = ticket;
      if (isLegacy) await storage.adopt(account, isLegacy);
      const records = await storage.list(account);
      return valid(ticket) ? records : [];
    },
    detach() { owner = null; generation++; flushing = null; },
    read,
    async save(kind, id, value) {
      const ticket = owner;
      if (!valid(ticket)) return;
      const recordKey = key(ticket.account, kind, id);
      await storage.update(recordKey, old => savedRecord(recordKey, kind, old, value, clock));
    },
    async enqueue(payload, operationId = newKey(), draftId = null) {
      const ticket = owner;
      if (!valid(ticket)) throw Error('帳號工作區尚未就緒');
      const recordKey = key(ticket.account, 'queue', operationId);
      await storage.enqueue(recordKey, old => queuedRecord(recordKey, operationId, payload, old, clock), draftId);
      notify(ticket);
      return operationId;
    },
    flush() {
      if (flushing) return flushing;
      const promise = flush().finally(() => { if (flushing === promise) flushing = null; });
      flushing = promise;
      return promise;
    },
    async resolve(operationId, shoeId) {
      const ticket = owner;
      if (!valid(ticket)) return;
      const newId = newKey();
      await storage.move(key(ticket.account, 'queue', operationId),
        current => repairedRecord(current, key(ticket.account, 'queue', newId), newId, shoeId, clock));
      notify(ticket);
    },
    async remove(operationId) {
      const ticket = owner;
      if (!valid(ticket)) return;
      await storage.update(key(ticket.account, 'queue', operationId), current => removedRecord(current, clock));
      notify(ticket);
    },
    async clear() {
      const ticket = owner;
      if (!valid(ticket)) return;
      await storage.clear(ticket.account, rows => refuseLeasedQueue(rows, clock));
      notify(ticket);
    },
  });
}

// SPEC-114: the controller's record rules and its per-run sync step, outside the factory.
const BLOCKING_STATUSES = [400, 403, 404, 409, 422];

// Sends one queued run under a lease. Returns 'synced', 'skipped' (leased elsewhere, blocked or
// stale), 'blocked' (the server refused it; keep going) or 'stop' (try the queue again later).
async function syncQueueItem({ storage, clock, newKey, send, committed }, ticket, item, valid) {
  let acquired = false;
  const lease = newKey();
  const claimed = await storage.update(item.key, current => {
    if (!current || current.status === 'blocked' || current.leaseUntil > clock()) return current;
    acquired = true;
    return { ...current, lease, leaseUntil: clock() + 120000 };
  });
  if (!acquired || !claimed || claimed.lease !== lease || !valid(ticket)) return 'skipped';
  try {
    await send(claimed.operation);
    // A response can complete after account switch; deletion stays in A's partition.
    await storage.update(item.key, current => current?.lease === lease ? null : current);
    // Notifications are best effort and cannot undo a confirmed server write.
    try { committed(ticket.account); } catch { /* The next foreground/manual read recovers. */ }
    return 'synced';
  } catch (error) {
    await storage.update(item.key, current => {
      if (current?.lease !== lease) return current;
      return { ...current, lease: null, leaseUntil: 0,
        status: BLOCKING_STATUSES.includes(error.status) ? 'blocked' : 'pending',
        message: error.message || '同步尚未完成', code: error.code || '', attempts: current.attempts + 1 };
    });
    return BLOCKING_STATUSES.includes(error.status) ? 'blocked' : 'stop';
  }
}

// A saved draft keeps the run draft a queued run already consumed out of the add-run form.
function savedRecord(recordKey, kind, old, value, clock) {
  if (value === null) return null;
  const saved = structuredClone(value);
  if (kind === 'drafts' && old?.value.consumedRunDraftId) {
    saved.consumedRunDraftId = old.value.consumedRunDraftId;
    if (saved.runDraftId === saved.consumedRunDraftId) delete saved.forms.run;
  }
  return { key: recordKey, value: saved, updated: clock() };
}

// Re-enqueueing the same operation is a no-op; the same ID with other content is refused.
function queuedRecord(recordKey, operationId, payload, old, clock) {
  if (old && JSON.stringify(old.operation.payload) !== JSON.stringify(payload)) throw Error('操作識別碼與內容不符');
  return old || { key: recordKey, operation: { operation_id: operationId, kind: 'run.create', payload: structuredClone(payload) },
    status: 'pending', lease: null, leaseUntil: 0, created: clock(), attempts: 0, message: '' };
}

// A blocked run re-paired with a shoe becomes a new pending operation.
function repairedRecord(current, newRecordKey, newId, shoeId, clock) {
  if (!current || current.status !== 'blocked' || current.leaseUntil > clock()) throw Error('請先確認這筆紀錄的同步結果');
  return { ...current, key: newRecordKey, operation: { ...current.operation, operation_id: newId,
    payload: { ...current.operation.payload, shoe_id: shoeId } }, status: 'pending', message: '', lease: null, leaseUntil: 0 };
}

// A run being synced right now cannot be removed or cleared.
function removedRecord(current, clock) {
  if (current?.leaseUntil > clock()) throw Error('紀錄正在同步，請稍後再試');
  return null;
}

function refuseLeasedQueue(rows, clock) {
  if (rows.some(row => row.key[1] === 'queue' && row.leaseUntil > clock())) throw Error('紀錄正在同步，請完成後再清除');
}
