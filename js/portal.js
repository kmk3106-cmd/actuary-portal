/**
 * Portal 공통 유틸리티
 * - 사이드바 동적 주입
 * - 토스트 알림
 * - 날짜 포맷
 * - 감사 로그용 X-Actor-* 헤더 자동 첨부 (모든 fetch에 적용)
 */

// ── 글로벌 fetch 인터셉터: 모든 /tables/, /api/ 요청에 actor 헤더 자동 첨부 ──
(function installAuditHeaders() {
  if (typeof window === 'undefined' || !window.fetch || window.__auditFetchInstalled) return;
  const origFetch = window.fetch.bind(window);
  window.fetch = function(input, init) {
    init = init || {};
    try {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const isInternal = url.startsWith('/') || url.includes(window.location.host);
      if (isInternal) {
        const session = (typeof RBAC !== 'undefined' && RBAC.getCurrentUser) ? RBAC.getCurrentUser() : null;
        if (session) {
          const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined) || {});
          if (!headers.has('X-Actor-User'))     headers.set('X-Actor-User', String(session.user_id || session.id || ''));
          if (!headers.has('X-Actor-Username')) headers.set('X-Actor-Username', encodeURIComponent(session.username || ''));
          if (!headers.has('X-Actor-Role'))     headers.set('X-Actor-Role', String(session.role || ''));
          init.headers = headers;
        }
      }
    } catch (_) { /* 헤더 첨부 실패해도 원래 요청은 진행 */ }
    return origFetch(input, init);
  };
  window.__auditFetchInstalled = true;
})();

const Portal = (() => {

  const NAV = [
    {
      section: '메인',
      items: [
        { href: 'index.html',     icon: 'fa-home',    label: '대시보드' },
        { href: 'personnel.html', icon: 'fa-id-card', label: '인사카드' }
      ]
    },
    {
      section: '팀 관리',
      items: [
        { href: 'identity.html',          icon: 'fa-flag',       label: '팀 정체성·핵심가치' },
        { href: 'goals-team.html',         icon: 'fa-bullseye',   label: '팀 목표' },
        { href: 'goals-individual.html',   icon: 'fa-user-check', label: '개인 목표 (SMART)' },
        { href: 'performance.html',        icon: 'fa-chart-bar',  label: '성과 관리' },
        { href: 'directives.html',         icon: 'fa-bullhorn',   label: '팀장 지시사항' },
        { href: 'interview-list.html',     icon: 'fa-comments',   label: '면담일지' }
      ]
    },
    {
      section: '결산',
      items: [
        { href: 'settlement.html',        icon: 'fa-calendar-alt', label: '결산 캘린더' },
        { href: 'settlement-review.html', icon: 'fa-clipboard-list', label: '결산 리뷰' }
      ]
    },
    {
      section: '업무',
      items: [
        { href: 'work-personal.html',  icon: 'fa-tasks',      label: '개인별 업무입력' },
        { href: 'workload-me.html',    icon: 'fa-chart-line', label: '내 업무량' },
        { href: 'workload-team.html',  icon: 'fa-users',      label: '팀 업무량 모니터링', leaderOrChief: true }
      ]
    },
    {
      section: '자동화',
      items: [
        { href: 'automation.html', icon: 'fa-robot',     label: '업무 자동화' },
        { href: 'reports.html',    icon: 'fa-file-word', label: '보고서 생성' }
      ]
    },
    {
      section: '지식관리',
      items: [
        { href: 'kb-sop.html',    icon: 'fa-book',                  label: 'SOP 문서' },
        { href: 'kb-issues.html', icon: 'fa-exclamation-triangle',  label: '이슈 사례집' }
      ]
    },
    {
      section: '시스템',
      items: [
        { href: 'bot-status.html', icon: 'fa-paper-plane', label: '텔레그램 봇' },
        { href: 'settings.html',   icon: 'fa-sliders-h',   label: '룰 설정', requiresLeader: true }
      ]
    }
  ];

  function buildSidebar() {
    const user = RBAC.getCurrentUser();
    if (!user) return;

    const currentPage = window.location.pathname.split('/').pop() || 'index.html';

    const isLeader = user.role === 'team_leader';
    const isLeaderOrChief = isLeader || user.role === 'section_chief';
    let navHtml = '';
    for (const section of NAV) {
      const visibleItems = section.items.filter(it => {
        if (it.requiresLeader) return isLeader;
        if (it.leaderOrChief) return isLeaderOrChief;
        return true;
      });
      if (!visibleItems.length) continue;
      navHtml += `<div class="nav-section-title">${section.section}</div>`;
      for (const item of visibleItems) {
        const active = (currentPage === item.href || currentPage === '' && item.href === 'index.html') ? ' active' : '';
        navHtml += `
          <a href="${item.href}" class="nav-item${active}" onclick="Portal.closeSidebar()">
            <i class="fas ${item.icon}"></i>
            <span>${item.label}</span>
          </a>`;
      }
    }

    const initials = (user.full_name || user.username || '?').slice(0, 1);
    const roleLabel = RBAC.getRoleLabel(user.role);
    const roleBadge = RBAC.getRoleBadgeClass(user.role);

    const html = `
      <div class="sidebar-overlay" id="sidebarOverlay" onclick="Portal.closeSidebar()"></div>
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-brand">
          <div class="brand-icon"><i class="fas fa-calculator"></i></div>
          <div>
            <div class="brand-name">계리결산팀</div>
            <div class="brand-sub">운영관리포탈</div>
          </div>
        </div>
        <div class="sidebar-user">
          <div class="user-card">
            <div class="user-avatar">${initials}</div>
            <div class="user-info">
              <div class="user-name">${user.full_name || user.username}</div>
              <div class="user-dept">${user.department || '계리결산팀'}</div>
            </div>
          </div>
          <span class="role-badge ${roleBadge}"><i class="fas fa-circle" style="font-size:6px;margin-right:4px;"></i>${roleLabel}</span>
        </div>
        <nav class="sidebar-nav">${navHtml}</nav>
        <div class="sidebar-footer">
          <button class="nav-item danger" onclick="Auth.logout()">
            <i class="fas fa-sign-out-alt"></i>
            <span>로그아웃</span>
          </button>
        </div>
      </aside>`;

    const layout = document.querySelector('.app-layout');
    if (layout) layout.insertAdjacentHTML('afterbegin', html);

    // 페이지 헤더에 햄버거 버튼 주입
    const pageHeader = document.querySelector('.page-header');
    if (pageHeader) {
      const hamburger = document.createElement('button');
      hamburger.className = 'hamburger-btn';
      hamburger.id = 'hamburgerBtn';
      hamburger.setAttribute('aria-label', '메뉴 열기');
      hamburger.innerHTML = '<i class="fas fa-bars"></i>';
      hamburger.onclick = Portal.toggleSidebar;
      pageHeader.insertBefore(hamburger, pageHeader.firstChild);
    }
  }

  function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (!sidebar) return;
    const isOpen = sidebar.classList.toggle('open');
    if (overlay) overlay.classList.toggle('show', isOpen);
    document.body.classList.toggle('sidebar-open', isOpen);
  }

  function closeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (sidebar) sidebar.classList.remove('open');
    if (overlay) overlay.classList.remove('show');
    document.body.classList.remove('sidebar-open');
  }

  // ── 토스트 ────────────────────────────────────────────────

  function ensureToastContainer() {
    if (!document.getElementById('toastContainer')) {
      const el = document.createElement('div');
      el.id = 'toastContainer';
      el.className = 'toast-container';
      document.body.appendChild(el);
    }
  }

  const TOAST_ICONS = {
    success: 'fa-check-circle',
    error:   'fa-exclamation-circle',
    warning: 'fa-exclamation-triangle',
    info:    'fa-info-circle'
  };

  function showToast(message, type = 'info') {
    ensureToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<i class="fas ${TOAST_ICONS[type] || TOAST_ICONS.info}"></i><span class="toast-msg">${message}</span>`;
    document.getElementById('toastContainer').appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
  }

  // ── 날짜 포맷 ─────────────────────────────────────────────

  function formatDate(ts) {
    if (!ts) return '-';
    const d = new Date(typeof ts === 'number' ? ts : ts);
    if (isNaN(d)) return String(ts);
    return d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  function formatDateTime(ts) {
    if (!ts) return '-';
    const d = new Date(typeof ts === 'number' ? ts : ts);
    if (isNaN(d)) return String(ts);
    return d.toLocaleString('ko-KR');
  }

  function todayStr() {
    return new Date().toISOString().split('T')[0];
  }

  function currentYearMonth() {
    const d = new Date();
    return String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0');
  }

  // ── 확인 모달 ─────────────────────────────────────────────

  function confirm(message, onConfirm) {
    const id = 'portalConfirmModal';
    let existing = document.getElementById(id);
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = id;
    overlay.className = 'modal-overlay show';
    overlay.innerHTML = `
      <div class="modal" style="max-width:400px">
        <div class="modal-header">
          <span class="modal-title"><i class="fas fa-exclamation-triangle" style="color:#f59e0b;margin-right:8px;"></i>확인</span>
        </div>
        <div class="modal-body">
          <p style="color:#374151;line-height:1.6;">${message}</p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="document.getElementById('${id}').remove()">취소</button>
          <button class="btn btn-danger" id="${id}Confirm">확인</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    document.getElementById(`${id}Confirm`).onclick = () => {
      overlay.remove();
      onConfirm();
    };
  }

  // ── 초기화 ────────────────────────────────────────────────

  function init() {
    if (!requireAuth()) return false;
    buildSidebar();
    ensureToastContainer();
    return true;
  }

  return { init, buildSidebar, toggleSidebar, closeSidebar, showToast, formatDate, formatDateTime, todayStr, currentYearMonth, confirm };
})();
