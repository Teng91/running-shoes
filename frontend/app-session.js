// Signed-in session identity shared by every script (SPEC-108). The token and user name start
// from storage; every sign-in and sign-out advances the generation, so work captured under one
// session can tell it no longer owns the screen. Sign-in itself lives in app-auth.js.
let authToken = readStoredValue('token');
let currentUser = readStoredValue('username');
let authGeneration = 0;

// SPEC-129: the token's claims. `sub` is the account name as the server spells it (names
// ignore ASCII case) and `aid` the account's never-reused ID; a deleted account's name can
// come back as another account, so local data is keyed by `aid`. The signature is the
// server's to check; this only reads what the server already issued.
function authTokenClaims(token) {
  try {
    const part = String(token || '').split('.')[1] || '';
    const json = atob(part.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(part.length / 4) * 4, '='));
    const claims = JSON.parse(new TextDecoder().decode(Uint8Array.from(json, char => char.charCodeAt(0))));
    return claims && typeof claims === 'object' ? claims : {};
  } catch {
    return {};
  }
}

function captureAuthSession() {
  const claims = authTokenClaims(authToken);
  return {
    generation: authGeneration, token: authToken,
    account: typeof claims.aid === 'string' ? claims.aid : null,
    expiresAt: Number.isFinite(claims.exp) ? claims.exp * 1000 : null,
  };
}

// SPEC-143: a renewed token of the same account continues the session it replaced.
function isCurrentAuthSession(session) {
  if (session.generation !== authGeneration) return false;
  return session.token === authToken || (session.account !== null && session.account === captureAuthSession().account);
}

function requireAuthSession(session) {
  if (!isCurrentAuthSession(session)) throw new DOMException('登入工作階段已變更', 'AbortError');
}

// SPEC-109: the only writers of the identity; architecture-check rejects assignments elsewhere.
// Signing in stores the new token and user name for this and future page loads. A renewal
// (SPEC-143) swaps in a new token only when it names the same account, and keeps the
// generation, so work captured before it still owns the screen; it returns whether it did.
function startAuthSession(token, username, { renewal = false } = {}) {
  const claims = authTokenClaims(token);
  if (renewal) {
    const current = authTokenClaims(authToken);
    if (!authToken || typeof claims.aid !== 'string' || claims.aid !== current.aid || claims.sub !== current.sub) {
      return false;
    }
  }
  authToken = token;
  currentUser = typeof claims.sub === 'string' && claims.sub ? claims.sub : username;
  writeStoredValue('token', token);
  writeStoredValue('username', currentUser);
  return true;
}

// Signing out advances the generation first, so work captured before it is stale while
// beforeForget runs (feature resets), then forgets the identity; persist: false keeps storage
// untouched when another tab already changed it.
function endAuthSession(beforeForget, { persist = true } = {}) {
  authGeneration += 1;
  beforeForget();
  authToken = null;
  currentUser = null;
  if (persist) {
    removeStoredValue('token');
    removeStoredValue('username');
  }
}

// When the server rejects the token, app-api.js dispatches the window event 'auth-session-expired'
// and app-auth.js, which owns sign-in, signs out; neither names the other's functions.
