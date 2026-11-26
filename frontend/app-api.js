// Authenticated HTTP helpers shared by feature modules.
const API_BASE = window.location.origin + '/api';
const authenticatedResponses = new WeakMap();
const JSON_TIMEOUT_MS = 20_000;
const activeHttpRequests = new Set();
// SPEC-135: a request in flight postpones an automatic update (SPEC-059).
registerBusyCheck(() => activeHttpRequests.size > 0);
const mutationKeys = new Map();
function newOperationKey() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}-${Math.random()}`;
}
function mutationRequest(url, method, body, suppliedKey) {
  const fingerprint = JSON.stringify([captureAuthSession().generation, url, method, body, suppliedKey || null]);
  if (!mutationKeys.has(fingerprint)) mutationKeys.set(fingerprint, suppliedKey || newOperationKey());
  return { fingerprint, key: mutationKeys.get(fingerprint) };
}
registerFeatureReset('http-requests', () => {
  for (const controller of activeHttpRequests) controller.abort();
  mutationKeys.clear();
});

async function withRequestDeadline(job, { signal, timeoutMs = JSON_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  activeHttpRequests.add(controller);
  let timer, abort;
  const cancelled = new Promise((_, reject) => {
    abort = () => reject(controller.signal.reason || new DOMException('請求已取消', 'AbortError'));
    controller.signal.addEventListener('abort', abort, { once: true });
  });
  const forward = () => controller.abort(signal.reason);
  signal?.addEventListener('abort', forward, { once: true });
  if (signal?.aborted) forward();
  timer = setTimeout(() => {
    const error = new Error('連線逾時，請重試。若剛才正在儲存，請沿用原表單重試以確認結果。');
    error.name = 'TimeoutError';
    controller.abort(error);
  }, timeoutMs);
  try {
    const pending = controller.signal.aborted ? Promise.reject(controller.signal.reason) : job(controller.signal);
    return await Promise.race([cancelled, pending]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', forward);
    controller.signal.removeEventListener('abort', abort);
    activeHttpRequests.delete(controller);
  }
}

async function authRequest(url, options) {
  return withRequestDeadline(async signal => {
    const response = await fetch(url, { ...options, signal });
    let body = {};
    try { body = await response.json(); } catch (error) {
      if (signal.aborted) throw signal.reason;
      if (response.ok) throw new Error('登入服務回傳格式錯誤，請稍後重試。');
    }
    return { ok: response.ok, status: response.status, json: async () => body };
  }, { signal: options.signal });
}

async function authenticatedFetch(url, options = {}) {
  const session = captureAuthSession();
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    requireAuthSession(session);
    throw error;
  }
  requireAuthSession(session);
  if (response.status === 401) {
    // This response is already complete; let its explicit 401 error win over
    // session teardown, which cancels all other pending requests.
    for (const controller of activeHttpRequests) {
      if (controller.signal === options.signal) activeHttpRequests.delete(controller);
    }
    // SPEC-108: app-auth.js signs out (synchronously) when it hears this.
    window.dispatchEvent(new Event('auth-session-expired'));
    const error = new Error('登入已過期，請重新登入。');
    error.status = 401;
    throw error;
  }
  authenticatedResponses.set(response, session);
  return response;
}

async function readAuthenticatedBody(response, method = 'json') {
  const session = authenticatedResponses.get(response);
  requireAuthSession(session);
  let body;
  try {
    body = await response[method]();
  } catch (error) {
    requireAuthSession(session);
    throw error;
  }
  requireAuthSession(session);
  return body;
}

async function readAuthenticatedError(response) {
  try {
    return await readAuthenticatedBody(response);
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    return {};
  }
}

function authHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
  return headers;
}

async function jsonRequest(url, options = {}, deadline = {}) {
  const session = captureAuthSession();
  const method = options.method || 'GET';
  for (let attempt = 0; ; attempt++) {
    try {
      return await withRequestDeadline(async signal => {
        const res = await authenticatedFetch(API_BASE + url, { ...options, signal });
        if (!res.ok) {
          const body = await readAuthenticatedError(res);
          const detail = Array.isArray(body.detail) ? body.detail.map(item => item.msg).join('；') : body.detail;
          const error = new Error(typeof detail === 'string' ? detail : `請求失敗（HTTP ${res.status}）`);
          error.status = res.status;
          error.code = body.error?.code || '';
          throw error;
        }
        return readAuthenticatedBody(res);
      }, { ...deadline, signal: options.signal });
    } catch (error) {
      if (error.status === 401) throw error;
      requireAuthSession(session);
      if (method === 'GET' && attempt === 0 && !options.signal?.aborted &&
          (error.name === 'TimeoutError' || error.name === 'TypeError' || [502, 503, 504].includes(error.status))) continue;
      throw error;
    }
  }
}

async function apiGet(url, options = {}) {
  return jsonRequest(url, { headers: authHeaders(), signal: options.signal }, options);
}

async function apiPost(url, body, options = {}) {
  const headers = authHeaders();
  const tracked = ['/runs', '/shoes', '/monthly-mileage'].includes(url);
  const operation = tracked ? mutationRequest(url, 'POST', body, options.idempotencyKey) : null;
  if (operation || options.idempotencyKey) headers['Idempotency-Key'] = operation?.key || options.idempotencyKey;
  const value = await jsonRequest(url, { method: 'POST', headers, body: JSON.stringify(body), signal: options.signal }, options);
  if (operation) mutationKeys.delete(operation.fingerprint);
  return value;
}

async function apiPut(url, body) {
  const operation = mutationRequest(url, 'PUT', body);
  const value = await jsonRequest(url, { method: 'PUT', headers: { ...authHeaders(), 'Idempotency-Key': operation.key }, body: JSON.stringify(body) });
  mutationKeys.delete(operation.fingerprint); return value;
}

async function apiDelete(url) {
  const operation = mutationRequest(url, 'DELETE');
  const value = await jsonRequest(url, { method: 'DELETE', headers: { ...authHeaders(), 'Idempotency-Key': operation.key } });
  mutationKeys.delete(operation.fingerprint); return value;
}

async function apiUpload(url, file, fields = {}, signal = undefined) {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  const headers = {};
  if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
  return jsonRequest(url, { method: 'POST', headers, body: form, signal }, { timeoutMs: 90_000 });
}
