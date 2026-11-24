// Signed-in session identity shared by every script (SPEC-108). The token and user name start
// from storage; every sign-in and sign-out advances the generation, so work captured under one
// session can tell it no longer owns the screen. Sign-in itself lives in app-auth.js.
let authToken = readStoredValue('token');
let currentUser = readStoredValue('username');
let authGeneration = 0;

function captureAuthSession() {
  return { generation: authGeneration, token: authToken };
}

function isCurrentAuthSession(session) {
  return session.generation === authGeneration && session.token === authToken;
}

function requireAuthSession(session) {
  if (!isCurrentAuthSession(session)) throw new DOMException('登入工作階段已變更', 'AbortError');
}

// When the server rejects the token, app-api.js dispatches the window event 'auth-session-expired'
// and app-auth.js, which owns sign-in, signs out; neither names the other's functions.
