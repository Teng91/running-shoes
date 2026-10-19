// Authenticated HTTP helpers shared by feature modules.
const API_BASE = window.location.origin + '/api';

function authHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
  return headers;
}

async function apiGet(url) {
  const res = await fetch(API_BASE + url, { headers: authHeaders() });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) throw new Error('GET ' + url + ' failed: ' + res.status);
  return res.json();
}

async function apiPost(url, body) {
  const res = await fetch(API_BASE + url, {
    method: 'POST', headers: authHeaders(), body: JSON.stringify(body),
  });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || ('POST ' + url + ' failed: ' + res.status));
  }
  return res.json();
}

async function apiPut(url, body) {
  const res = await fetch(API_BASE + url, {
    method: 'PUT', headers: authHeaders(), body: JSON.stringify(body),
  });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : '儲存失敗：' + res.status);
  }
  return res.json();
}

async function apiDelete(url) {
  const res = await fetch(API_BASE + url, { method: 'DELETE', headers: authHeaders() });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || ('DELETE ' + url + ' failed: ' + res.status));
  }
  return res.json();
}

async function apiUpload(url, file, fields = {}, signal = undefined) {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  const headers = {};
  if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
  const res = await fetch(API_BASE + url, { method: 'POST', headers, body: form, signal });
  if (res.status === 401) { clearAuth(); showLoginView(); throw new Error('Unauthorized'); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = Array.isArray(err.detail)
      ? err.detail.map(item => item.msg || JSON.stringify(item)).join('；')
      : (typeof err.detail === 'string' ? err.detail : '');
    throw new Error(detail || ('POST ' + url + ' failed: ' + res.status));
  }
  return res.json();
}
