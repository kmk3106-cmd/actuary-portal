# 일일 자체점검 이력

매일 새벽 자동 점검(docs/QA_DAILY_CHECK.md) 결과를 한 줄씩 누적한다. 최신이 위.

| 날짜 | 범위 | 결함 | 수정 | 미해결 |
|---|---|---|---|---|
| 2026-10-22 | 화면 54 (팀장·직원) | 결함 0 → 0 | 수정 없음 · 점검이 만든 reports/output/finance_*.docx 삭제 | 없음 (환경 메모 1: interview-list 팀장 버튼이 페이지 새로고침) |
| 2026-10-21 | 화면 54 (팀장·직원) | 결함 0 → 0 | qa_smoke.js 보고서 날짜를 UTC → KST(`REPORT_TZ`, `QA_TZ` 환경변수) 기준으로 수정 (02:52 KST 실행 시 전날 날짜로 찍히던 문제) · 점검이 만든 reports/output/finance_*.docx 삭제 | 없음 (환경 메모 1: interview-list 팀장 버튼이 페이지 새로고침) |
| 2026-10-18 (초기 구축, 수동) | 화면 54 (팀장·직원) | 결함 17 → 0 | kb-sop 카테고리 onclick 따옴표 누락(카테고리 클릭 불가) · 새 DB 에서 audit_reports·weekly_settings·settlement_calendar_issues 404 · settlement/settlement-issues 가로 스크롤 · 규정 개정이력 "리포트 보기" 새 탭 세션 유실 | 없음 |
