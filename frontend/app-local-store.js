// IndexedDB transactions resolve only after commit, including lease compare/update.
async function openLocalWorkspaceStore() {
  const database = await new Promise((resolve, reject) => {
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
  });
  database.onversionchange = () => database.close();
  function transaction(mode, job) {
    return new Promise((resolve, reject) => {
      const tx = database.transaction('records', mode);
      const store = tx.objectStore('records');
      let result, failure;
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(failure || tx.error || Error('無法存取本機資料'));
      tx.onabort = () => reject(failure || tx.error || Error('本機儲存已中止'));
      try { job(store, value => { result = value; }, error => { failure = error; tx.abort(); }); }
      catch (error) { failure = error; tx.abort(); }
    });
  }
  return Object.freeze({
    list(account, kind = null) {
      return transaction('readonly', (store, done) => {
        const request = store.index('account').getAll(account);
        request.onsuccess = () => done(request.result.filter(row => !kind || row.key[1] === kind));
      });
    },
    update(key, change) {
      return transaction('readwrite', (store, done, fail) => {
        const request = store.get(key);
        request.onsuccess = () => {
          try {
            const value = change(request.result);
            if (value) store.put({ ...value, key, account: key[0] }); else store.delete(key);
            done(value);
          } catch (error) { fail(error); }
        };
      });
    },
    enqueue(key, change, draftId) {
      return transaction('readwrite', (store, done, fail) => {
        const request = store.get(key);
        request.onsuccess = () => {
          try {
            const value = change(request.result);
            store.put({ ...value, key, account: key[0] });
            if (draftId) {
              const draft = store.get([key[0], 'drafts', 'forms']);
              draft.onsuccess = () => {
                const record = draft.result || { key: [key[0], 'drafts', 'forms'], account: key[0], value: { forms: {} } };
                record.value.consumedRunDraftId = draftId;
                if (record.value.runDraftId === draftId) delete record.value.forms.run;
                store.put(record);
              };
            }
            done(value);
          } catch (error) { fail(error); }
        };
      });
    },
    move(key, change) {
      return transaction('readwrite', (store, done, fail) => {
        const request = store.get(key);
        request.onsuccess = () => {
          try {
            const value = change(request.result);
            store.put({ ...value, account: key[0] }); store.delete(key); done(value);
          } catch (error) { fail(error); }
        };
      });
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
