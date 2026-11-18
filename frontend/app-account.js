// SPEC-075: invite-only sign-up, the admin's invite and password help, and account deletion.

async function loadRegistrationMode() {
  const group = document.getElementById('reg-invite-group');
  const note = document.getElementById('reg-mode-note');
  const submit = document.querySelector('#register-form button[type="submit"]');
  try {
    const response = await fetch(API_BASE + '/auth/registration');
    if (!response.ok) throw new Error('registration mode unavailable');
    registrationMode = (await response.json()).mode;
  } catch {
    // Unknown (offline): keep the invite field so a code can still be entered.
    registrationMode = null;
  }
  const closed = registrationMode === 'closed';
  group.hidden = registrationMode === 'open' || closed;
  note.hidden = !closed;
  note.textContent = closed ? '目前不開放註冊。' : '';
  if (submit) submit.disabled = closed;
}

let adminRequestId = 0;

async function renderAdminSection() {
  const section = document.getElementById('admin-section');
  if (!section) return;
  const requestId = ++adminRequestId;
  let me = null;
  try { me = await apiGet('/auth/me'); } catch { me = null; }
  if (requestId !== adminRequestId) return;
  section.hidden = !me?.is_admin;
  if (me?.is_admin) await loadInvites();
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
    note: document.getElementById('invite-note').value.trim(),
    max_uses: Math.min(20, Math.max(1, Number(document.getElementById('invite-uses').value) || 1)),
    days: Math.min(90, Math.max(1, Number(document.getElementById('invite-days').value) || 14)),
  };
  result.textContent = '產生中…';
  try {
    const invite = await apiPost('/admin/invites', body);
    result.textContent = `邀請碼：${invite.code}（可使用 ${invite.max_uses} 次，${String(invite.expires_at).slice(0, 10)} 到期；只顯示這一次，請現在複製）`;
    document.getElementById('invite-note').value = '';
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
