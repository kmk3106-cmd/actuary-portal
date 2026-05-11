/**
 * Portal 공통 유틸리티
 * - 사이드바 동적 주입
 * - 토스트 알림
 * - 날짜 포맷
 * - 감사 로그용 X-Actor-* 헤더 자동 첨부 (모든 fetch에 적용)
 * - 카카오톡 인앱 브라우저 → 외부 브라우저 자동 전환
 */

// ── 카카오톡 인앱 브라우저 회피 (전역 즉시 실행) ──
// 카카오톡 인앱 WebView는 storage/crypto 제약으로 portal 로그인·세션 동작 불가.
// userAgent에 'KAKAOTALK' 포함 시 iOS=Safari, Android=Chrome 으로 강제 외부 전환.
// login.html은 별도 inline script로도 처리 (페이지 콘텐츠 그리기 전 실행 보장).
(function redirectFromKakaoInapp() {
  if (typeof navigator === 'undefined' || !navigator.userAgent) return;
  var ua = navigator.userAgent.toUpperCase();
  if (ua.indexOf('KAKAOTALK') === -1) return;
  var url = window.location.href;
  var isIos = /iPhone|iPad|iPod/i.test(navigator.userAgent);
  try {
    if (isIos) {
      window.location.href = 'kakaotalk://web/openExternal?url=' + encodeURIComponent(url);
    } else {
      var stripped = url.replace(/^https?:\/\//, '');
      var scheme = url.indexOf('https://') === 0 ? 'https' : 'http';
      window.location.href = 'intent://' + stripped + '#Intent;scheme=' + scheme + ';package=com.android.chrome;end';
    }
  } catch (_) { /* 일부 환경에서 URL 스킴 차단되면 아래 안내로 fallback */ }
  // 1.5초 후에도 페이지가 살아있으면 안내 배너 (외부 전환 실패한 경우)
  setTimeout(function() {
    if (document.querySelector('.kakao-inapp-notice')) return;
    var notice = document.createElement('div');
    notice.className = 'kakao-inapp-notice';
    notice.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#fef3c7;border-bottom:2px solid #f59e0b;padding:14px 18px;text-align:center;z-index:99999;font-size:13px;color:#92400e;font-family:sans-serif;line-height:1.5;';
    notice.innerHTML = '<strong>⚠ 카카오톡 인앱 브라우저는 일부 기능이 제한됩니다.</strong><br>우측 상단 메뉴(⋮ 또는 ⋯) → <strong>"다른 브라우저로 열기"</strong> 권장.';
    if (document.body) document.body.appendChild(notice);
    else document.addEventListener('DOMContentLoaded', function(){ document.body.appendChild(notice); });
  }, 1500);
})();

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
        { href: 'bot-status.html',   icon: 'fa-paper-plane', label: '텔레그램 봇' },
        { href: 'audit-report.html', icon: 'fa-shield-alt',  label: '운영 점검' },
        { href: 'settings.html',     icon: 'fa-sliders-h',   label: '룰 설정', requiresLeader: true }
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
    let sectionIdx = 0;
    for (const section of NAV) {
      const visibleItems = section.items.filter(it => {
        if (it.requiresLeader) return isLeader;
        if (it.leaderOrChief) return isLeaderOrChief;
        return true;
      });
      if (!visibleItems.length) continue;
      sectionIdx++;
      const num = String(sectionIdx).padStart(2, '0');
      navHtml += `<div class="nav-section">
        <div class="nav-section-title">
          <span class="nav-section-num">${num}</span>
          <span class="nav-section-label">${section.section}</span>
        </div>`;
      for (const item of visibleItems) {
        const active = (currentPage === item.href || currentPage === '' && item.href === 'index.html') ? ' active' : '';
        navHtml += `
          <a href="${item.href}" class="nav-item${active}" onclick="Portal.closeSidebar()">
            <i class="fas ${item.icon}"></i>
            <span>${item.label}</span>
          </a>`;
      }
      navHtml += `</div>`;
    }

    const initials = (user.full_name || user.username || '?').slice(0, 1);
    const roleLabel = RBAC.getRoleLabel(user.role);

    const html = `
      <div class="sidebar-overlay" id="sidebarOverlay" onclick="Portal.closeSidebar()"></div>
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-brand">
          <div class="brand-icon"></div>
          <div>
            <div class="brand-name">계리결산팀</div>
            <div class="brand-sub">OPERATIONS PORTAL</div>
          </div>
        </div>
        <div class="sidebar-user">
          <div class="user-card">
            <div class="user-avatar">${initials}</div>
            <div class="user-info">
              <div class="user-name-row">
                <span class="user-name">${user.full_name || user.username}</span>
                <span class="role-badge">${roleLabel}</span>
              </div>
              <div class="user-dept">${user.department || '계리결산팀'}</div>
            </div>
          </div>
        </div>
        <nav class="sidebar-nav">${navHtml}</nav>
        <div class="sidebar-footer">
          <button class="logout-btn" onclick="Auth.logout()">
            <i class="fas fa-power-off"></i>
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

    // 자동 점검 알림 배지 — 비동기로 가져와서 사용자 카드 아래에 삽입
    refreshAuditBadge();
  }

  /**
   * 최신 audit_reports를 fetch하여 사이드바 사용자 영역 아래에 알림 배지를 그린다.
   * - 'issues' 상태: 빨간 배지
   * - 'clean' 상태: 초록 배지 (옅게)
   * - 데이터 없음/실패: 표시 안 함
   */
  async function refreshAuditBadge() {
    try {
      const r = await fetch('/tables/audit_reports?limit=1');
      if (!r.ok) return;
      const data = await r.json();
      const reports = data.rows || data.data || [];
      if (!reports.length) return;
      // 가장 최근 run_at으로 정렬
      reports.sort((a, b) => (b.run_at || 0) - (a.run_at || 0));
      const latest = reports[0];
      const issuesCount = latest.summary?.total_issues || 0;
      const isHigh = (latest.summary?.by_severity?.high || 0) > 0;
      const status = latest.status || 'unknown';
      const isClean = status === 'clean' || issuesCount === 0;
      const runAt = latest.run_at ? new Date(latest.run_at) : null;
      const timeLabel = runAt
        ? `${runAt.getMonth() + 1}/${runAt.getDate()} ${String(runAt.getHours()).padStart(2,'0')}:${String(runAt.getMinutes()).padStart(2,'0')}`
        : '?';
      const badgeHtml = `
        <a href="audit-report.html" class="audit-badge ${isClean ? 'clean' : (isHigh ? 'danger' : 'warn')}" onclick="Portal.closeSidebar()">
          <i class="fas ${isClean ? 'fa-shield-alt' : 'fa-exclamation-triangle'}"></i>
          <span class="audit-badge-text">
            ${isClean ? '점검 정상' : `점검 이상 ${issuesCount}건`}
          </span>
          <span class="audit-badge-time">${timeLabel}</span>
        </a>`;
      const userBox = document.querySelector('.sidebar-user');
      if (userBox) {
        const existing = document.querySelector('.audit-badge');
        if (existing) existing.remove();
        userBox.insertAdjacentHTML('afterend', badgeHtml);
      }
    } catch (_) { /* 실패 시 배지 표시 안 함 — 사이드바 동작에 영향 없게 */ }
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
    // 로컬 시간 기준 (toISOString은 UTC 변환되어 한국 자정~09시에 일자가 하루 빨라짐)
    const d = new Date();
    return d.getFullYear() + '-' +
           String(d.getMonth() + 1).padStart(2, '0') + '-' +
           String(d.getDate()).padStart(2, '0');
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
