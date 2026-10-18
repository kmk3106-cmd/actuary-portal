/**
 * 리포트 HTML → 포탈 문서(kb_documents.content) 임베드 공용 모듈
 * (docs/01_리포트_스타일가이드.md §5 · kb-sop.html / reg-history.html 공용, 규칙 11 SSOT)
 *
 *  - wrapForPortal(html, heightPx): 전체 HTML 을 <iframe srcdoc> 으로 감싼 한 줄짜리 HTML 문자열
 *      · &  → &amp;   " → &quot;   줄바꿈 → &#10;
 *      · 한 줄로 만드는 이유: kb-sop 본문은 marked(마크다운) 를 거친다. HTML 블록은 빈 줄에서 끝나므로
 *        원본의 빈 줄이 살아 있으면 뒤쪽이 마크다운으로 재해석된다.
 *      · sandbox="allow-same-origin" 만 준다 (allow-scripts 없음). 리포트는 스크립트 없이 동작해야 한다.
 *  - fitFrames(root): srcdoc iframe 의 높이를 내용 높이에 맞춘다 (same-origin 이라 contentDocument 접근 가능).
 *      고정 높이(등록 시 지정) 는 최소값으로만 쓰이고, 내용이 더 길면 늘어난다.
 *  - extractTitle(html): <title> 또는 첫 <h1> 텍스트
 *
 *  scripts/publish_regulation.py 의 wrap_for_portal() 과 동일 규칙을 유지할 것.
 */
(function (global) {
  'use strict';
  const DEFAULT_HEIGHT_PX = 1400;
  const MIN_HEIGHT_PX = 400;
  const FIT_MARGIN_PX = 24;

  function wrapForPortal(html, heightPx) {
    const h = Number(heightPx) || DEFAULT_HEIGHT_PX;
    const esc = String(html || '')
      .replace(/\r/g, '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/\n/g, '&#10;');
    return `<div class="report-embed" style="margin:0;"><iframe srcdoc="${esc}" `
         + `style="width:100%;height:${h}px;border:0;display:block;" `
         + `sandbox="allow-same-origin" loading="lazy" title="report"></iframe></div>`;
  }

  function isWrapped(content) {
    return /<iframe[^>]+srcdoc=/i.test(String(content || ''));
  }

  function extractTitle(html) {
    const s = String(html || '');
    const t = s.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
    if (t && t[1].trim()) return decode(t[1]);
    const h = s.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i);
    if (h) return decode(h[1].replace(/<[^>]+>/g, ''));
    return '';
  }
  function decode(s) {
    const d = document.createElement('textarea');
    d.innerHTML = s;
    return d.value.replace(/\s+/g, ' ').trim();
  }

  function fitOne(iframe) {
    try {
      const doc = iframe.contentDocument;
      if (!doc || !doc.documentElement) return;
      const base = parseInt(iframe.getAttribute('data-min-height') || iframe.style.height, 10) || MIN_HEIGHT_PX;
      const h = Math.max(doc.documentElement.scrollHeight, doc.body ? doc.body.scrollHeight : 0) + FIT_MARGIN_PX;
      if (h > MIN_HEIGHT_PX) iframe.style.height = Math.max(h, Math.min(base, h)) + 'px';
    } catch (_) { /* cross-origin 등 — 고정 높이 유지 */ }
  }

  function fitFrames(root) {
    const scope = root || document;
    scope.querySelectorAll('iframe[srcdoc]').forEach(iframe => {
      if (!iframe.getAttribute('data-min-height')) iframe.setAttribute('data-min-height', String(parseInt(iframe.style.height, 10) || MIN_HEIGHT_PX));
      fitOne(iframe);
      iframe.addEventListener('load', () => { fitOne(iframe); setTimeout(() => fitOne(iframe), 600); setTimeout(() => fitOne(iframe), 2000); });
      setTimeout(() => fitOne(iframe), 300);
    });
  }

  global.ReportEmbed = { wrapForPortal, fitFrames, extractTitle, isWrapped, DEFAULT_HEIGHT_PX };
})(window);
