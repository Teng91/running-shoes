// SPEC-079: forgot password with emailed codes and email binding.
const { runContext, test, assert, vm, extract, htmlSource } = require('./helpers.cjs');

function nodes() {
  return new Proxy({}, { get: (target, id) => target[id] ||= { id, value: '', textContent: '', innerHTML: '', hidden: false, style: {}, dataset: {} } });
}

function emailContext(elements, globals = {}) {
  const context = runContext({
    document: { getElementById: id => elements[id], querySelector: () => ({ disabled: false }) },
    API_BASE: '/api', translateError: value => value, confirm: () => true, ...globals,
  });
  const names = ['publicPost', 'showResetForm', 'showResetError', 'sendResetCode', 'handleResetPassword', 'renderEmailSection',
    'showBoundEmail', 'sendEmailCode', 'confirmEmailCode', 'removeEmail', 'loadRegistrationMode'];
  vm.runInContext(['let registrationMode = null;', 'let mailEnabled = false;', 'let emailRequestId = 0;',
    ...names.map(extract)].join('\n'), context);
  return context;
}

test('SPEC-079 the forgot-password form checks for email only when opened and explains when it is off', async () => {
  for (const enabled of [true, false]) {
    const elements = nodes();
    const context = emailContext(elements, { cancelAuthOperation() {},
      fetch: async () => ({ ok: true, json: async () => ({ mode: 'invite', mail_enabled: enabled }) }) });
    await context.showResetForm();
    assert.equal(elements['reset-form'].style.display, '');
    assert.equal(/請找管理員/.test(elements['reset-sent'].textContent), !enabled);
  }
  // No request at startup: the login page stays network-free for the PWA shell.
  assert.match(htmlSource, /id="forgot-link" data-click="show-reset-form">忘記密碼？</);
  assert.match(htmlSource, /id="reset-code" inputmode="numeric" autocomplete="one-time-code"/);
});

test('SPEC-079 password reset sends the code request, answers neutrally and needs matching passwords', async () => {
  const elements = nodes();
  const calls = [];
  const context = emailContext(elements, {
    fetch: async (url, options) => {
      if (!options) return { ok: true, json: async () => ({ mode: 'invite', mail_enabled: true }) };
      const body = JSON.parse(options.body);
      calls.push([url, body]);
      return url.endsWith('/confirm') && body.code === '000000'
        ? { ok: false, status: 400, json: async () => ({ detail: 'Incorrect or expired code' }) }
        : { ok: true, json: async () => ({ ok: true }) };
    },
    translateError: value => (value === 'Incorrect or expired code' ? '驗證碼錯誤或已過期' : value),
    cancelAuthOperation() {}, showLoginNotice: text => calls.push('login', text),
  });
  elements['login-username'].value = 'Friend';
  await context.showResetForm();
  assert.equal(elements['reset-form'].style.display, '');
  assert.equal(elements['reset-identifier'].value, 'Friend', 'the typed username carries over');
  await context.sendResetCode();
  assert.equal(JSON.stringify(calls[0]), JSON.stringify(['/api/auth/password-reset/request', { identifier: 'Friend' }]));
  assert.match(elements['reset-sent'].textContent, /如果這個帳號有綁定 email/);

  elements['reset-code'].value = '000000';
  elements['reset-new-password'].value = 'new-pass-1';
  elements['reset-new-password2'].value = 'different';
  await context.handleResetPassword();
  assert.equal(elements['reset-error'].textContent, '兩次密碼不一致');
  elements['reset-new-password2'].value = 'new-pass-1';
  await context.handleResetPassword();
  assert.equal(elements['reset-error'].textContent, '驗證碼錯誤或已過期');
  elements['reset-code'].value = '123456';
  await context.handleResetPassword();
  assert.equal(JSON.stringify(calls.slice(-2)), JSON.stringify(['login', '密碼已重設，請用新密碼登入']));
  assert.equal(elements['reset-new-password'].value, '', 'passwords are cleared');
});

test('SPEC-079 the email section binds only after the code and can remove the address', async () => {
  const elements = nodes();
  const posts = [];
  const context = emailContext(elements, {
    fetch: async () => ({ ok: true, json: async () => ({ mode: 'invite', mail_enabled: true }) }),
    apiGet: async () => ({ email: null }),
    apiPost: async url => { posts.push(url); return url.endsWith('/confirm') ? { email: 'me@example.com' } : { ok: true }; },
  });
  await context.renderEmailSection();
  assert.equal(elements['email-section'].hidden, false);
  assert.equal(elements['email-current'].textContent, '還沒有綁定 email。');
  assert.equal(elements['email-remove'].hidden, true);
  elements['email-address'].value = 'me@example.com';
  await context.sendEmailCode();
  assert.match(elements['email-status'].textContent, /驗證碼已寄到 me@example.com/);
  assert.equal(elements['email-current'].textContent, '還沒有綁定 email。', 'not bound before the code');
  elements['email-code'].value = '123456';
  await context.confirmEmailCode();
  assert.equal(elements['email-current'].textContent, '目前綁定：me@example.com');
  assert.equal(elements['email-remove'].hidden, false);
  await context.removeEmail();
  assert.equal(JSON.stringify(posts), JSON.stringify(['/auth/email/request', '/auth/email/confirm', '/auth/email/remove']));
  assert.equal(elements['email-current'].textContent, '還沒有綁定 email。');

  const off = nodes();
  const disabled = emailContext(off, {
    fetch: async () => ({ ok: true, json: async () => ({ mode: 'invite', mail_enabled: false }) }),
    apiGet: async () => ({ email: null }),
  });
  await disabled.renderEmailSection();
  assert.equal(off['email-section'].hidden, true, 'hidden while email is not configured');
});

test('SPEC-080 the login page has no change-password form; signed-in users change it in「資料與同步」', async () => {
  assert.doesNotMatch(htmlSource, /id="change-form"|data-click="show-change-form"/);
  assert.match(htmlSource, /<summary>更改密碼<\/summary>[\s\S]*id="account-old-password" type="password" autocomplete="current-password"/);
  const elements = nodes();
  const calls = [];
  const context = emailContext(elements, {
    currentUser: 'Demo',
    fetch: async (url, options) => {
      const body = JSON.parse(options.body);
      calls.push([url, body]);
      return body.old_password === 'wrong-pass'
        ? { ok: false, status: 401, json: async () => ({ detail: 'Incorrect username or old password' }) }
        : { ok: true, json: async () => ({ ok: true }) };
    },
    closeDialog: id => calls.push(`close ${id}`), signOutWithNotice: text => calls.push('logout', 'login', text),
  });
  vm.runInContext(extract('changePassword'), context);
  elements['account-old-password'].value = 'wrong-pass';
  elements['account-new-password'].value = elements['account-new-password2'].value = 'brand-new-pass';
  await context.changePassword();
  assert.equal(elements['password-status'].textContent, '更改失敗：目前密碼不正確');
  assert.ok(!calls.includes('logout'), 'a wrong current password keeps the session');
  elements['account-old-password'].value = 'pass1234';
  await context.changePassword();
  assert.equal(JSON.stringify(calls[1][1]), JSON.stringify({ username: 'Demo', old_password: 'pass1234', new_password: 'brand-new-pass' }));
  assert.equal(JSON.stringify(calls.slice(-4)), JSON.stringify(['close workspace-modal', 'logout', 'login', '密碼已更改，請用新密碼重新登入']));
  assert.equal(elements['account-new-password'].value, '', 'password fields are cleared');
});
