// 미구현 페이지 공통 렌더러
function renderComingSoon(title, desc, phase, icon) {
  document.addEventListener('DOMContentLoaded', () => {
    if (typeof Portal !== 'undefined') Portal.init();
    const body = document.getElementById('comingSoonBody');
    if (!body) return;
    body.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;min-height:60vh;">
        <div style="text-align:center;max-width:480px;">
          <div style="width:80px;height:80px;border-radius:20px;background:linear-gradient(135deg,#4f86f7,#6c5ce7);
            display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:32px;color:white;
            box-shadow:0 8px 32px rgba(79,134,247,0.3);">
            <i class="fas ${icon}"></i>
          </div>
          <h2 style="font-size:22px;font-weight:700;color:#111827;margin-bottom:12px;">${title}</h2>
          <p style="font-size:14px;color:#6b7280;line-height:1.7;margin-bottom:24px;">${desc}</p>
          <span style="display:inline-flex;align-items:center;gap:6px;padding:6px 14px;background:#dbeafe;color:#1d4ed8;border-radius:20px;font-size:12px;font-weight:600;">
            <i class="fas fa-clock"></i> Phase ${phase} 구현 예정
          </span>
          <div style="margin-top:32px;">
            <a href="index.html" class="btn btn-secondary"><i class="fas fa-home"></i> 대시보드로</a>
          </div>
        </div>
      </div>`;
  });
}
