// IndexedDB transactions resolve only after commit, including lease compare/update.
// Browsers may close a live connection (WebKit/iOS Safari after backgrounding or under memory
// pressure, or a versionchange); the next operation reopens instead of failing until reload.
async function openLocalWorkspaceStore() {
  // SPEC-114: one connection handle shared by the open, transaction and record steps below.
  const handle = { database: null, opening: null };
  await openWorkspaceDatabase(handle);
  return workspaceStoreRecords((mode, job) => runWorkspaceTransaction(handle, mode, job));
}

function openWorkspaceDatabase(handle) {
  handle.opening ||= new Promise((resolve, reject) => {
    const request = indexedDB.open('running-shoes-workspace', 1);
    request.onupgradeneeded = () => {
      const store = request.result.createObjectStore('records', { keyPath: 'key' });
      store.createIndex('account', 'account');
    };
    let settled = false;
    const timer = setTimeout(() => { settled = true; reject(Error('本機資料庫開啟逾時')); }, 5000);
    request.onsuccess = () => { clearTimeout(timer); if (settled) request.result.close(); else { settled = true; resolve(request.result); } };
    request.onerror = () => { settled = true; clearTimeout(timer); reject(request.error); };
    request.onblocked = () => { settled = true; clearTimeout(timer); reject(Error('本機資料庫正在升級，請關閉其他舊分頁後重試')); };
  }).then(connection => {
    const forget = () => { if (handle.database === connection) handle.database = null; };
    connection.onversionchange = () => { connection.close(); forget(); };
    connection.onclose = forget;
    handle.database = connection;
    return connection;
  }).finally(() => { handle.opening = null; });
  return handle.opening;
}

async function runWorkspaceTransaction(handle, mode, job) {
  let tx;
  for (let attempt = 0; !tx; attempt++) {
    const connection = handle.database || await openWorkspaceDatabase(handle);
    try { tx = connection.transaction('records', mode); }
    catch (error) {
      // A closing connection cannot start transactions; nothing ran, so reopen and retry once.
      if (error?.name !== 'InvalidStateError' || attempt > 0) throw error;
      if (handle.database === connection) handle.database = null;
    }
  }
  return new Promise((resolve, reject) => {
    const store = tx.objectStore('records');
    let result, failure;
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(failure || tx.error || Error('無法存取本機資料'));
    tx.onabort = () => reject(failure || tx.error || Error('本機儲存已中止'));
    try { job(store, value => { result = value; }, error => { failure = error; tx.abort(); }); }
    catch (error) { failure = error; tx.abort(); }
  });
}

// Reads one record, applies change and lets write store the result; a throw aborts the transaction.
function changeWorkspaceRecord(store, key, change, write, done, fail) {
  const request = store.get(key);
  request.onsuccess = () => {
    try {
      const value = change(request.result);
      write(value);
      done(value);
    } catch (error) { fail(error); }
  };
}

// A queued run consumes the add-run draft it came from, in the same transaction.
function consumeRunDraft(store, account, draftId) {
  const draft = store.get([account, 'drafts', 'forms']);
  draft.onsuccess = () => {
    const record = draft.result || { key: [account, 'drafts', 'forms'], account, value: { forms: {} } };
    record.value.consumedRunDraftId = draftId;
    if (record.value.runDraftId === draftId) delete record.value.forms.run;
    store.put(record);
  };
}

function workspaceStoreRecords(transaction) {
  return Object.freeze({
    list(account, kind = null) {
      return transaction('readonly', (store, done) => {
        const request = store.index('account').getAll(account);
        request.onsuccess = () => done(request.result.filter(row => !kind || row.key[1] === kind));
      });
    },
    update(key, change) {
      return transaction('readwrite', (store, done, fail) => changeWorkspaceRecord(store, key, change, value => {
        if (value) store.put({ ...value, key, account: key[0] }); else store.delete(key);
      }, done, fail));
    },
    enqueue(key, change, draftId) {
      return transaction('readwrite', (store, done, fail) => changeWorkspaceRecord(store, key, change, value => {
        store.put({ ...value, key, account: key[0] });
        if (draftId) consumeRunDraft(store, key[0], draftId);
      }, done, fail));
    },
    move(key, change) {
      return transaction('readwrite', (store, done, fail) => changeWorkspaceRecord(store, key, change, value => {
        store.put({ ...value, account: key[0] }); store.delete(key);
      }, done, fail));
    },
    clear(account, validate = () => {}) {
      return transaction('readwrite', (store, done, fail) => {
        const request = store.index('account').getAll(account);
        request.onsuccess = () => {
          try {
            validate(request.result);
            request.result.forEach(row => store.delete(row.key)); done();
          } catch (error) { fail(error); }
        };
      });
    },
  });
}
