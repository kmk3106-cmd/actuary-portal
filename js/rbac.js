/**
 * RBAC (Role-Based Access Control) Engine
 * 역할: team_leader(팀장) / section_chief(실장) / member(팀원)
 */

const RBAC = (() => {

  const ROLES = {
    MEMBER: 'member',
    TEAM_LEADER: 'team_leader',
    SECTION_CHIEF: 'section_chief'
  };

  const SESSION_KEY = 'rbac_session';

  function getCurrentUser() {
    const s = sessionStorage.getItem(SESSION_KEY);
    if (!s) return null;
    try {
      const session = JSON.parse(s);
      if (session.expires_at && Date.now() > session.expires_at) {
        sessionStorage.removeItem(SESSION_KEY);
        return null;
      }
      return session;
    } catch { return null; }
  }

  function isAuthenticated() { return getCurrentUser() !== null; }

  function hasRole(role) {
    const u = getCurrentUser();
    return u ? u.role === role : false;
  }

  function isTeamLeader() { return hasRole(ROLES.TEAM_LEADER); }
  function isSectionChief() { return hasRole(ROLES.SECTION_CHIEF); }
  function isMember() { return hasRole(ROLES.MEMBER) || hasRole('employee'); }
  function isEmployee() { return hasRole(ROLES.MEMBER) || hasRole('employee'); }

  // 실장(section_chief) = 전 화면 열람 가능하나 쓰기/삭제 금지(읽기 전용).
  // portal.js 전역 fetch 가드가 이 값을 보고 모든 변경 API를 차단한다.
  function isReadOnly() { return hasRole(ROLES.SECTION_CHIEF); }

  // 팀장 전용 화면(설정·결산리뷰 등)을 '열람'할 수 있는 역할.
  // 실장은 열람만 허용(쓰기는 isReadOnly 가드가 차단).
  function canViewLeaderScreens() { return isTeamLeader() || isSectionChief(); }

  // 면담일지 접근 권한
  function checkInterviewAccess(action, log = null) {
    const user = getCurrentUser();
    if (!user) return { allowed: false, message: '로그인이 필요합니다.' };
    const role = user.role;

    switch (action) {
      case 'create':
      case 'update':
      case 'delete':
        if (role !== ROLES.TEAM_LEADER)
          return { allowed: false, message: '팀장만 면담일지를 작성·수정·삭제할 수 있습니다.' };
        return { allowed: true };

      case 'read':
        if (!log) return { allowed: false, message: '면담일지 정보가 없습니다.' };
        if (role === ROLES.TEAM_LEADER) return { allowed: true };
        if (role === ROLES.SECTION_CHIEF) {
          if (log.is_confidential) return { allowed: false, message: '기밀 면담일지는 팀장만 열람 가능합니다.' };
          return { allowed: true };
        }
        if (role === ROLES.MEMBER || role === 'employee') {
          if (log.interviewee_id !== user.user_id)
            return { allowed: false, message: '본인의 면담일지만 열람 가능합니다.' };
          if (log.is_confidential)
            return { allowed: false, message: '기밀 면담일지는 열람 불가합니다.' };
          return { allowed: true };
        }
        return { allowed: false, message: '접근 권한이 없습니다.' };

      case 'confirm':
        if (!log) return { allowed: false, message: '면담일지 정보가 없습니다.' };
        if (log.interviewee_id !== user.user_id)
          return { allowed: false, message: '본인 면담일지만 확인 서명 가능합니다.' };
        if (log.is_confidential)
          return { allowed: false, message: '기밀 면담일지는 서명 불가합니다.' };
        return { allowed: true };

      case 'list':
        return { allowed: true };

      default:
        return { allowed: false, message: '알 수 없는 액션입니다.' };
    }
  }

  function filterInterviewList(logs) {
    const user = getCurrentUser();
    if (!user) return [];
    if (user.role === ROLES.TEAM_LEADER) return logs;
    if (user.role === ROLES.SECTION_CHIEF) return logs.filter(l => !l.is_confidential);
    // employee or member: own non-confidential only
    return logs.filter(l => l.interviewee_id === user.user_id && !l.is_confidential);
  }

  function getRoleLabel(role) {
    return { team_leader: '팀장', section_chief: '실장', member: '팀원', employee: '팀원' }[role] || role;
  }

  function getRoleBadgeClass(role) {
    return { team_leader: 'badge-team-leader', section_chief: 'badge-section-chief', member: 'badge-employee', employee: 'badge-employee' }[role] || 'badge-employee';
  }

  return {
    ROLES,
    SESSION_KEY,
    getCurrentUser,
    isAuthenticated,
    hasRole,
    isTeamLeader,
    isSectionChief,
    isMember,
    isEmployee,
    isReadOnly,
    canViewLeaderScreens,
    checkInterviewAccess,
    filterInterviewList,
    getRoleLabel,
    getRoleBadgeClass
  };
})();

function requireAuth() {
  if (!RBAC.isAuthenticated()) {
    window.location.href = 'login.html?redirect=' + encodeURIComponent(window.location.href);
    return false;
  }
  return true;
}
