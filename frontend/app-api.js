// Authenticated HTTP helpers shared by feature modules.
const API_BASE = window.location.origin + '/api';
const authenticatedResponses = new WeakMap();

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
    clearAuth();
    showLoginView();
    throw new Error('登入已過期，請重新登入。');
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

async function apiGet(url) {
  const res = await authenticatedFetch(API_BASE + url, { headers: authHeaders() });
  if (!res.ok) throw new Error('GET ' + url + ' failed: ' + res.status);
  return readAuthenticatedBody(res);
}

async function apiPost(url, body) {
  const res = await authenticatedFetch(API_BASE + url, {
    method: 'POST', headers: authHeaders(), body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await readAuthenticatedError(res);
    throw new Error(err.detail || ('POST ' + url + ' failed: ' + res.status));
  }
  return readAuthenticatedBody(res);
}

async function apiPut(url, body) {
  const res = await authenticatedFetch(API_BASE + url, {
    method: 'PUT', headers: authHeaders(), body: JSON.stringify(body),
  });
  if (!res.ok) {
    const error = await readAuthenticatedError(res);
    throw new Error(typeof error.detail === 'string' ? error.detail : '儲存失敗：' + res.status);
  }
  return readAuthenticatedBody(res);
}

async function apiDelete(url) {
  const res = await authenticatedFetch(API_BASE + url, { method: 'DELETE', headers: authHeaders() });
  if (!res.ok) {
    const err = await readAuthenticatedError(res);
    throw new Error(err.detail || ('DELETE ' + url + ' failed: ' + res.status));
  }
  return readAuthenticatedBody(res);
}

async function apiUpload(url, file, fields = {}, signal = undefined) {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  const headers = {};
  if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
  const res = await authenticatedFetch(API_BASE + url, { method: 'POST', headers, body: form, signal });
  if (!res.ok) {
    const err = await readAuthenticatedError(res);
    const detail = Array.isArray(err.detail)
      ? err.detail.map(item => item.msg || JSON.stringify(item)).join('；')
      : (typeof err.detail === 'string' ? err.detail : '');
    throw new Error(detail || ('POST ' + url + ' failed: ' + res.status));
  }
  return readAuthenticatedBody(res);
}
