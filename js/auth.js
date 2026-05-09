/**
 * Authentication Module
 * 로그인/로그아웃/세션 관리
 */

const Auth = (() => {
  const SESSION_DURATION_MS = 8 * 60 * 60 * 1000; // 8시간

  async function sha256(message) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(message));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
  }

  function generateToken() {
    const arr = new Uint8Array(32);
    crypto.getRandomValues(arr);
    return Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('');
  }

  async function login(username, password) {
    try {
      const res = await fetch(`tables/users?search=${encodeURIComponent(username)}&limit=50`);
      if (!res.ok) return { success: false, message: '서버에 연결할 수 없습니다. start.bat으로 서버를 실행해주세요.' };

      const data = await res.json();
      const user = (data.data || []).find(u => u.username === username && u.is_active !== false);

      if (!user) {
        await writeAuditLog(null, username, null, 'login', 'denied', `존재하지 않는 사용자: ${username}`);
        return { success: false, message: '아이디 또는 비밀번호가 올바르지 않습니다.' };
      }

      const hash = await sha256(password);
      if (user.password_hash !== hash) {
        await writeAuditLog(user.id, username, user.role, 'login', 'denied', '비밀번호 불일치');
        return { success: false, message: '아이디 또는 비밀번호가 올바르지 않습니다.' };
      }

      if (user.is_active === false)
        return { success: false, message: '비활성화된 계정입니다. 팀장에게 문의하세요.' };

      const token = generateToken();
      const expires = Date.now() + SESSION_DURATION_MS;

      const sessionData = {
        session_token: token,
        user_id: user.id,
        username: user.username,
        role: user.role,
        full_name: user.full_name,
        department: user.department || '',
        expires_at: expires
      };

      await fetch('tables/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: token, ...sessionData })
      }).catch(() => {});

      sessionStorage.setItem(RBAC.SESSION_KEY, JSON.stringify(sessionData));
      await writeAuditLog(user.id, username, user.role, 'login', 'allowed', '로그인 성공');

      return { success: true, message: '로그인 성공', user };
    } catch (err) {
      console.error('로그인 오류:', err);
      return { success: false, message: '로그인 중 오류가 발생했습니다.' };
    }
  }

  async function logout() {
    const user = RBAC.getCurrentUser();
    if (user) {
      try {
        const r = await fetch(`tables/sessions?search=${user.session_token}&limit=5`);
        if (r.ok) {
          const d = await r.json();
          for (const s of (d.data || []).filter(s => s.id === user.session_token)) {
            await fetch(`tables/sessions/${s.id}`, { method: 'DELETE' });
          }
        }
      } catch {}
      await writeAuditLog(user.user_id, user.username, user.role, 'logout', 'allowed', '로그아웃');
    }
    sessionStorage.removeItem(RBAC.SESSION_KEY);
    window.location.href = 'login.html';
  }

  async function writeAuditLog(userId, username, role, action, result, detail) {
    try {
      await fetch('tables/audit_logs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId || 'anonymous',
          username: username || 'anonymous',
          role: role || 'unknown',
          action,
          result,
          detail: detail || ''
        })
      });
    } catch {}
  }

  return { login, logout, sha256, writeAuditLog };
})();
