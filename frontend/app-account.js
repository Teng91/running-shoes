// SPEC-075: invite-only sign-up, the admin's invite and password help, and account deletion.

// SPEC-079: whether the server can email codes (forgot password, email binding).
let mailEnabled = false;

async function loadRegistrationMode() {
  const group = document.getElementById('reg-invite-group');
  const note = document.getElementById('reg-mode-note');
  const submit = document.querySelector('#register-form button[type="submit"]');
  try {
    const response = await fetch(API_BASE + '/auth/registration');
    if (!response.ok) throw new Error('registration mode unavailable');
    const options = await response.json();
    registrationMode = options.mode;
    mailEnabled = options.mail_enabled === true;
  } catch {
    // Unknown (offline): keep the invite field so a code can still be entered.
    registrationMode = null;
    mailEnabled = false;
  }
  const forgot = document.getElementById('forgot-link');
  if (forgot) forgot.hidden = !mailEnabled;
  const closed = registrationMode === 'closed';
  group.hidden = registrationMode === 'open' || closed;
  note.hidden = !closed;
  note.textContent = closed ? '目前不開放註冊。' : '';
  if (submit) submit.disabled = closed;
}

let adminRequestId = 0;

// SPEC-077: the sidebar shows「邀請碼管理」only to admins; hidden until the server says so.
async function refreshAdminEntry() {
  const entry = document.getElementById('admin-entry');
  if (!entry) return;
  const requestId = ++adminRequestId;
  entry.hidden = true;
  let me = null;
  try { me = await apiGet('/auth/me'); } catch { me = null; }
  if (requestId !== adminRequestId) return;
  entry.hidden = !me?.is_admin;
}

function openAdminModal() {
  document.getElementById('admin-modal').classList.add('active');
  void loadInvites();
}

function closeAdminModal() {
  document.getElementById('admin-modal').classList.remove('active');
  // One-time codes and temporary passwords must not linger on screen.
  for (const id of ['invite-result', 'reset-result']) document.getElementById(id).textContent = '';
}

function inviteStatus(invite) {
  if (invite.revoked) return '已停用';
  if (invite.used_count >= invite.max_uses) return '已用完';
  if (!invite.active) return '已過期';
  return '可使用';
}

async function loadInvites() {
  const target = document.getElementById('invite-list');
  try {
    const invites = await apiGet('/admin/invites');
    target.innerHTML = invites.length ? `<div class="table-wrap" tabindex="0" role="region" aria-label="邀請碼"><table>
      <thead><tr><th>備註</th><th class="numeric">已用</th><th>到期</th><th>狀態</th><th></th></tr></thead>
      <tbody>${invites.map(invite => `<tr>
        <td>${esc(invite.note || '—')}</td>
        <td class="numeric">${Number(invite.used_count)}／${Number(invite.max_uses)}</td>
        <td>${esc(String(invite.expires_at || '').slice(0, 10))}</td>
        <td>${inviteStatus(invite)}</td>
        <td class="invite-actions">${invite.active ? `<button class="btn btn-sm btn-delete" data-click="revoke-invite" data-invite-id="${Number(invite.id)}">停用</button>` : ''}</td>
      </tr>`).join('')}</tbody></table></div>` : '<p class="workspace-help">還沒有邀請碼。</p>';
  } catch (error) {
    target.textContent = '邀請碼載入失敗：' + translateError(error.message);
  }
}

async function createInvite() {
  const result = document.getElementById('invite-result');
  const body = {
    code: document.getElementById('invite-code').value.trim(),
    note: document.getElementById('invite-note').value.trim(),
    max_uses: Math.min(20, Math.max(1, Number(document.getElementById('invite-uses').value) || 1)),
    days: Math.min(90, Math.max(1, Number(document.getElementById('invite-days').value) || 14)),
  };
  result.textContent = '產生中…';
  try {
    const invite = await apiPost('/admin/invites', body);
    result.textContent = `邀請碼：${invite.code}（可使用 ${invite.max_uses} 次，${String(invite.expires_at).slice(0, 10)} 到期；只顯示這一次，請現在複製）`;
    document.getElementById('invite-note').value = '';
    document.getElementById('invite-code').value = '';
    await loadInvites();
  } catch (error) {
    result.textContent = '產生失敗：' + translateError(error.message);
  }
}

async function revokeInvite(id) {
  if (!Number.isInteger(id) || !confirm('停用這組邀請碼？已經用它註冊的帳號不受影響。')) return;
  try {
    await apiDelete('/admin/invites/' + id);
  } catch (error) {
    document.getElementById('invite-result').textContent = '停用失敗：' + translateError(error.message);
  }
  await loadInvites();
}

async function adminResetPassword() {
  const input = document.getElementById('reset-username');
  const result = document.getElementById('reset-result');
  const username = input.value.trim();
  if (!username) { result.textContent = '請輸入對方的帳號。'; return; }
  if (!confirm(`替「${username}」產生臨時密碼？他目前的登入都會被登出。`)) return;
  try {
    const reset = await apiPost('/admin/reset-password', { username });
    result.textContent = `「${reset.username}」的臨時密碼：${reset.temporary_password}（只顯示這一次，請對方登入後馬上到「更改密碼」換掉）`;
    input.value = '';
  } catch (error) {
    result.textContent = '重設失敗：' + translateError(error.message);
  }
}

async function deleteAccount() {
  const input = document.getElementById('delete-account-password');
  const status = document.getElementById('delete-account-status');
  if (!input.value) { status.textContent = '請輸入密碼。'; return; }
  if (!confirm(`確定要永久刪除帳號「${currentUser}」和所有資料嗎？這個動作無法復原。`)) return;
  status.textContent = '刪除中…';
  try {
    await apiPost('/auth/delete-account', { password: input.value });
  } catch (error) {
    status.textContent = '刪除失敗：' + translateError(error.message);
    return;
  }
  input.value = '';
  status.textContent = '';
  // The server data is gone; drop this device's drafts and queue for the account too.
  try { await localWorkspace.controller?.clear(); } catch {}
  closeWorkspaceModal();
  clearAuth();
  showLoginView();
  showAuthError('帳號已刪除。');
}

// ===== SPEC-079: email binding and forgot password =====

async function publicPost(path, body) {
  const response = await fetch(API_BASE + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let data = {};
  try { data = await response.json(); } catch {}
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join('；') : data.detail;
    throw new Error(translateError(typeof detail === 'string' ? detail : `請求失敗（HTTP ${response.status}）`));
  }
  return data;
}

function showResetForm() {
  cancelAuthOperation();
  for (const id of ['login-form', 'register-form', 'change-form']) document.getElementById(id).style.display = 'none';
  document.getElementById('reset-form').style.display = '';
  document.getElementById('reset-error').style.display = 'none';
  document.getElementById('reset-sent').textContent = '';
  const login = document.getElementById('login-username').value.trim();
  if (login && !document.getElementById('reset-identifier').value) document.getElementById('reset-identifier').value = login;
}

function showResetError(message) {
  const element = document.getElementById('reset-error');
  element.textContent = message;
  element.style.display = 'block';
}

async function sendResetCode() {
  const identifier = document.getElementById('reset-identifier').value.trim();
  const sent = document.getElementById('reset-sent');
  document.getElementById('reset-error').style.display = 'none';
  if (!identifier) { showResetError('請輸入帳號或 email'); return; }
  sent.textContent = '寄送中…';
  try {
    await publicPost('/auth/password-reset/request', { identifier });
    // The server answers the same way for unknown accounts, so this text must too.
    sent.textContent = '如果這個帳號有綁定 email，驗證碼已經寄出，10 分鐘內有效。沒收到請檢查垃圾郵件匣。';
  } catch (error) {
    sent.textContent = '';
    showResetError(error.message);
  }
}

async function handleResetPassword() {
  const identifier = document.getElementById('reset-identifier').value.trim();
  const code = document.getElementById('reset-code').value.trim();
  const password = document.getElementById('reset-new-password').value;
  const password2 = document.getElementById('reset-new-password2').value;
  document.getElementById('reset-error').style.display = 'none';
  if (!identifier || !code) { showResetError('請輸入帳號或 email 與驗證碼'); return; }
  if (password.length < 8) { showResetError('密碼至少 8 個字元'); return; }
  if (password !== password2) { showResetError('兩次密碼不一致'); return; }
  try {
    await publicPost('/auth/password-reset/confirm', { identifier, code, new_password: password });
  } catch (error) {
    showResetError(error.message);
    return;
  }
  for (const id of ['reset-code', 'reset-new-password', 'reset-new-password2']) document.getElementById(id).value = '';
  showLoginForm();
  showAuthError('密碼已重設，請用新密碼登入');
}

let emailRequestId = 0;

async function renderEmailSection() {
  const section = document.getElementById('email-section');
  if (!section) return;
  const requestId = ++emailRequestId;
  let options = null, me = null;
  try {
    const response = await fetch(API_BASE + '/auth/registration');
    options = response.ok ? await response.json() : null;
    me = await apiGet('/auth/me');
  } catch { options = null; }
  if (requestId !== emailRequestId) return;
  section.hidden = !options?.mail_enabled;
  showBoundEmail(me?.email || null);
}

function showBoundEmail(email) {
  document.getElementById('email-current').textContent = email
    ? `目前綁定：${email}` : '還沒有綁定 email。';
  document.getElementById('email-remove').hidden = !email;
}

async function sendEmailCode() {
  const status = document.getElementById('email-status');
  const email = document.getElementById('email-address').value.trim();
  if (!email) { status.textContent = '請輸入 email。'; return; }
  status.textContent = '寄送中…';
  try {
    await apiPost('/auth/email/request', { email });
    status.textContent = `驗證碼已寄到 ${email}，10 分鐘內有效。沒收到請檢查垃圾郵件匣。`;
  } catch (error) {
    status.textContent = '寄送失敗：' + translateError(error.message);
  }
}

async function confirmEmailCode() {
  const status = document.getElementById('email-status');
  const input = document.getElementById('email-code');
  const code = input.value.trim();
  if (!code) { status.textContent = '請輸入驗證碼。'; return; }
  try {
    const result = await apiPost('/auth/email/confirm', { code });
    input.value = '';
    document.getElementById('email-address').value = '';
    showBoundEmail(result.email);
    status.textContent = '已綁定，忘記密碼時可以用這個 email 收驗證碼。';
  } catch (error) {
    status.textContent = '綁定失敗：' + translateError(error.message);
  }
}

async function removeEmail() {
  if (!confirm('移除綁定的 email？移除後忘記密碼就只能找管理員重設。')) return;
  const status = document.getElementById('email-status');
  try {
    await apiPost('/auth/email/remove', {});
    showBoundEmail(null);
    status.textContent = '已移除 email。';
  } catch (error) {
    status.textContent = '移除失敗：' + translateError(error.message);
  }
}
