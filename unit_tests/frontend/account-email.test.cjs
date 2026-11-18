// SPEC-079: forgot password with emailed codes and email binding.
const { runContext, test, assert, vm, extract, htmlSource } = require('./helpers.cjs');

function nodes() {
  return new Proxy({}, { get: (target, id) => target[id] ||= { id, value: '', textContent: '', innerHTML: '', hidden: false, style: {} } });
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

test('SPEC-079 the login page offers「忘記密碼」only when the server can email codes', async () => {
  for (const enabled of [true, false]) {
    const elements = nodes();
    const context = emailContext(elements, { fetch: async () => ({ ok: true, json: async () => ({ mode: 'invite', mail_enabled: enabled }) }) });
    await context.loadRegistrationMode();
    assert.equal(elements['forgot-link'].hidden, !enabled);
  }
  assert.match(htmlSource, /id="forgot-link" data-click="show-reset-form" hidden/);
  assert.match(htmlSource, /id="reset-code" inputmode="numeric" autocomplete="one-time-code"/);
});

test('SPEC-079 password reset sends the code request, answers neutrally and needs matching passwords', async () => {
  const elements = nodes();
  const calls = [];
  const context = emailContext(elements, {
    fetch: async (url, options) => {
      const body = JSON.parse(options.body);
      calls.push([url, body]);
      return url.endsWith('/confirm') && body.code === '000000'
        ? { ok: false, status: 400, json: async () => ({ detail: 'Incorrect or expired code' }) }
        : { ok: true, json: async () => ({ ok: true }) };
    },
    translateError: value => (value === 'Incorrect or expired code' ? '驗證碼錯誤或已過期' : value),
    cancelAuthOperation() {}, showLoginForm: () => calls.push('login'), showAuthError: text => calls.push(text),
  });
  elements['login-username'].value = 'Xuan';
  context.showResetForm();
  assert.equal(elements['reset-form'].style.display, '');
  assert.equal(elements['reset-identifier'].value, 'Xuan', 'the typed username carries over');
  await context.sendResetCode();
  assert.equal(JSON.stringify(calls[0]), JSON.stringify(['/api/auth/password-reset/request', { identifier: 'Xuan' }]));
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
