// SPEC-075: invite-only sign-up, admin invites/password help and account deletion.
const { runContext, test, assert, vm, extract, htmlSource, authOperationContext } = require('./helpers.cjs');

function nodes() {
  return new Proxy({}, { get: (target, id) => target[id] ||= { id, value: '', textContent: '', innerHTML: '', hidden: false, style: {} } });
}

function accountContext(elements, globals = {}) {
  const submit = { disabled: false };
  const context = runContext({
    document: { getElementById: id => elements[id], querySelector: () => submit },
    API_BASE: '/api', translateError: value => value, esc: text => String(text).replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`),
    confirm: () => true, currentUser: 'Joy', ...globals,
  });
  vm.runInContext(`let registrationMode = null;\nlet adminRequestId = 0;\n${['loadRegistrationMode', 'renderAdminSection', 'inviteStatus',
    'loadInvites', 'createInvite', 'revokeInvite', 'adminResetPassword', 'deleteAccount'].map(extract).join('\n')}`, context);
  return { context, submit };
}

test('SPEC-075 the sign-up form asks for an invite only when the server requires one', async () => {
  for (const [mode, inviteHidden, closed] of [['invite', false, false], ['open', true, false], ['closed', true, true]]) {
    const elements = nodes();
    const { context, submit } = accountContext(elements, { fetch: async () => ({ ok: true, json: async () => ({ mode }) }) });
    await context.loadRegistrationMode();
    assert.equal(elements['reg-invite-group'].hidden, inviteHidden, mode);
    assert.equal(submit.disabled, closed, mode);
    assert.equal(elements['reg-mode-note'].hidden, !closed, mode);
  }
  const elements = nodes();
  const { context } = accountContext(elements, { fetch: async () => { throw new TypeError('offline'); } });
  await context.loadRegistrationMode();
  assert.equal(elements['reg-invite-group'].hidden, false, 'offline keeps the invite field');
  assert.match(htmlSource, /id="reg-invite"/);
  assert.equal((htmlSource.match(/<details class="auth-privacy">/g) || []).length, 2, 'login and sign-up show the privacy notice');
});

test('SPEC-075 registration sends the invite code and requires it in invite mode', async () => {
  const { context, elements, state } = authOperationContext();
  vm.runInContext('registrationMode = "invite"', context);
  elements['reg-username'].value = 'Xuan';
  elements['reg-password'].value = elements['reg-password2'].value = 'password';
  const bodies = [];
  context.fetch = async (_, options) => { bodies.push(JSON.parse(options.body)); return { ok: false, status: 400, json: async () => ({ detail: 'Invalid invite code' }) }; };
  await context.handleRegister();
  assert.deepEqual(bodies, [], 'an empty code is caught before the request');
  assert.equal(state.writes.at(-1), '請輸入邀請碼');
  elements['reg-invite'].value = ' k7qm-3xpa ';
  await context.handleRegister();
  assert.equal(bodies[0].invite_code, 'k7qm-3xpa');
});

test('SPEC-075 only admins see the invite panel; codes are escaped and spent ones cannot be revoked', async () => {
  const member = nodes();
  const asMember = accountContext(member, { apiGet: async () => ({ is_admin: false }) }).context;
  await asMember.renderAdminSection();
  assert.equal(member['admin-section'].hidden, true);

  const admin = nodes();
  const invites = [
    { id: 2, note: '<b>給 Xuan</b>', max_uses: 1, used_count: 0, expires_at: '2026-12-02T00:00:00Z', revoked: false, active: true },
    { id: 1, note: '', max_uses: 1, used_count: 1, expires_at: '2026-12-01T00:00:00Z', revoked: false, active: false },
  ];
  const posts = [];
  const { context } = accountContext(admin, {
    apiGet: async url => (url === '/auth/me' ? { is_admin: true } : invites),
    apiPost: async (url, body) => { posts.push([url, body]); return url === '/admin/invites'
      ? { code: 'K7QM-3XPA', max_uses: 2, expires_at: '2026-12-02T00:00:00Z' }
      : { username: 'Xuan', temporary_password: 'temp-pass-123' }; },
  });
  await context.renderAdminSection();
  assert.equal(admin['admin-section'].hidden, false);
  const html = admin['invite-list'].innerHTML;
  assert.doesNotMatch(html, /<b>/, 'notes are escaped');
  assert.equal((html.match(/data-click="revoke-invite"/g) || []).length, 1, 'only active invites can be revoked');
  assert.match(html, /已用完/);

  admin['invite-uses'].value = '99'; admin['invite-days'].value = '';
  await context.createInvite();
  assert.equal(JSON.stringify(posts[0]), JSON.stringify(['/admin/invites', { note: '', max_uses: 20, days: 14 }]));
  assert.match(admin['invite-result'].textContent, /K7QM-3XPA.*只顯示這一次/);

  admin['reset-username'].value = ' Xuan ';
  await context.adminResetPassword();
  assert.equal(JSON.stringify(posts[1]), JSON.stringify(['/admin/reset-password', { username: 'Xuan' }]));
  assert.match(admin['reset-result'].textContent, /temp-pass-123/);
});

test('SPEC-075 deleting the account needs the password and signs out only after the server confirms', async () => {
  const elements = nodes();
  const calls = [];
  let fail = true;
  const { context } = accountContext(elements, {
    apiPost: async (url, body) => { calls.push([url, body]); if (fail) throw new Error('Incorrect password'); return { ok: true }; },
    localWorkspace: { controller: { clear: async () => calls.push('clear') } },
    closeWorkspaceModal: () => calls.push('close'), clearAuth: () => calls.push('logout'),
    showLoginView: () => calls.push('login'), showAuthError: text => calls.push(text),
  });
  await context.deleteAccount();
  assert.deepEqual(calls, [], 'no password, no request');
  elements['delete-account-password'].value = 'wrong';
  await context.deleteAccount();
  assert.equal(elements['delete-account-status'].textContent, '刪除失敗：Incorrect password');
  assert.ok(!calls.includes('logout'), 'a wrong password keeps the session');
  fail = false;
  elements['delete-account-password'].value = 'pass1234';
  await context.deleteAccount();
  assert.deepEqual(calls.slice(-5), ['clear', 'close', 'logout', 'login', '帳號已刪除。']);
  assert.equal(elements['delete-account-password'].value, '');
});
