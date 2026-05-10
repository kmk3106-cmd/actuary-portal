# 계리결산팀 운영관리포탈

미래에셋생명 계리결산팀 전용 운영·성과·지식관리 포탈.

## 시스템 구조

```
actuary-potal/
├── server/
│   ├── server.js              # Node.js 표준 http 서버 (8888 포트)
│   ├── lib/
│   │   ├── bizday.js          # 영업일 계산 유틸 (한국 공휴일 기반)
│   │   └── workload.js        # 부하율 계산 모듈
│   └── data/
│       ├── portal-db.json     # 메인 JSON DB (포탈 데이터)
│       ├── actuarial.db       # SQLite (Python 보고서/자동화 전용)
│       ├── kb_files/          # KB 첨부파일
│       └── uploads/           # 자동화 임시 업로드
├── js/
│   ├── auth.js                # 로그인/로그아웃
│   ├── rbac.js                # RBAC 클라이언트 엔진
│   └── portal.js              # 사이드바 + 공통 유틸 + fetch 인터셉터
├── css/main.css               # 글로벌 스타일
├── *.html                     # 페이지 (login, index, settings 등)
├── reports/                   # Python 보고서 생성 스크립트
├── automation/                # Python 자동화 스크립트 (엑셀 키인 등)
├── bot/                       # 텔레그램 봇 스크립트
├── scripts/                   # 재사용 유틸 스크립트
└── tmp/                       # 일회성 점검 스크립트
```

## 기술 스택

| 영역 | 사용 기술 |
|------|-----------|
| 백엔드 | Node.js 표준 `http` 모듈 (Express 미사용) |
| DB | JSON 파일 (`portal-db.json`) — 단일 파일 배열 기반 |
| 프론트엔드 | Vanilla JS + HTML + CSS, FontAwesome, Noto Sans KR |
| 차트 | ApexCharts (CDN) — heatmap / donut / radialBar / area / bar |
| 마크다운 | EasyMDE (에디터) + marked.js (렌더) |
| 인증 | SHA-256 해시 + sessionStorage 세션 |
| 외부 접근 | Cloudflare Named Tunnel (`portal.kkuks.com`) |
| 프로세스 관리 | PM2 (`ecosystem.config.js`) |
| Python 보고서 | openpyxl, python-docx (별도 SQLite) |

## 설치 및 실행

### 최초 설치
```powershell
cd "C:\Users\USER\actuary potal"
npm install                      # ESLint만 dev dep, 런타임은 표준 Node
```

### 개발 모드 (수동 실행)
```powershell
node server/server.js
# → http://127.0.0.1:8888/login.html
```

### 운영 모드 (PM2)
```powershell
pm2 start ecosystem.config.js
pm2 save
pm2 startup    # OS 부팅 시 자동 시작
```

### Cloudflare 터널 (외부 접근)
```powershell
.\start-cloudflare.bat   # 또는 cloudflared service install
```
설정: `C:\Users\USER\.cloudflared\config.yml`
- 터널: `actuary-portal`
- 호스트: `portal.kkuks.com` → `localhost:8888`

## 주요 모듈

### A. 결산 관리
- 결산 캘린더 (settlement.html) — 26개 결산업무 + D+N 영업일 자동 계산
- 결산 리뷰 (settlement-review.html)
- 결산업무는 `settle_items` 테이블에서 관리 (룰 설정에서 편집)

### B. 성과 관리 (performance.html)
- 정량 평가 4종 (지시수행/CSM/기한준수/임원회의) — DB 룰 기반 점수 환산
- 정성 KPI (KPI 정의 테이블에서 동적 렌더 — 수 무관)
- 기본/최종 점수 + 가산 + 등급 자동 계산

### C. 업무량 모니터링 (Phase 1~3, 신규)
- 팀 대시보드 (workload-team.html, **팀장/실장 전용**)
  - 30일 히트맵, 개인별 비교, 업무유형 도넛, 알림 패널
- 개인 대시보드 (workload-me.html)
  - 시계열, 부하율 게이지, 누적 MM, 일별 입력 폼
- **MM 환산** = 누적분 ÷ (해당 월 영업일 × 8h × 60)
- 임계값(과중 120%, 유휴 70%, 연속 3/5일)은 `workload_thresholds` 테이블

### D. 지식관리 (Phase 4~5, 신규)
- SOP 문서 (kb-sop.html) — 마크다운 + 자동 버전 관리 + 첨부파일 + 조회/유용성
- 이슈 사례집 (kb-issues.html) — severity / 태그 / 유사 이슈 추천
- 인수인계 / 온보딩 (테이블만 준비, UI 미구현)

### E. 룰 설정 (settings.html, **팀장 전용**)
5개 탭:
1. 결산업무 (settle_items)
2. 점수 규칙 (score_rules)
3. KPI 정의 (kpi_definitions, 정량/정성 + 연도별)
4. 기타 카테고리 (task_categories — 일별 업무 입력용)
5. 이슈 카테고리 (issue_categories — 이슈 사례집용)

⚠️ **모든 비즈니스 룰은 코드 수정 없이 이 페이지에서 관리** (규칙 11, SSOT)

## 권한 (RBAC)

| 역할 코드 | 한글 | 접근 |
|-----------|------|------|
| `team_leader` | 팀장 | 모든 기능 |
| `section_chief` | 실장 | 팀 모니터링 + KB 작성 (룰 설정 X) |
| `employee` / `member` | 팀원 | 본인 데이터 + KB 읽기 + 이슈 등록 |

권한 분기:
- 사이드바: `requiresLeader` (팀장만), `leaderOrChief` (팀장+실장)
- 페이지 내부: `RBAC.isTeamLeader()`, `user.role === 'section_chief'` 체크

## 감사 로그

모든 `/tables/*` 의 POST/PATCH/PUT/DELETE 는 `audit_logs` 에 자동 기록됩니다.
- 클라이언트가 `X-Actor-User` / `X-Actor-Username` / `X-Actor-Role` 헤더 자동 첨부 (portal.js fetch 인터셉터)
- 무한 누적 방지: 최근 5000건만 보관
- 캐시 테이블(workload_daily_cache, business_days_monthly, kb_document_versions, automation_logs, report_history) 및 sessions, audit_logs 자체는 기록 제외

## 백업

DB는 단일 JSON 파일이므로 파일 단위 백업.
```powershell
# 일일 백업 예시
Copy-Item "C:\Users\USER\actuary potal\server\data\portal-db.json" `
          "D:\backup\portal-db-$(Get-Date -Format yyyyMMdd).json"
```
KB 첨부파일도 함께 백업: `server/data/kb_files/`

## 배포 체크리스트 (운영 전)

- [x] 로그인 페이지 테스트 계정 노출 제거
- [x] 감사 로그 자동 기록
- [x] 룰 설정 페이지 권한 (팀장 전용)
- [x] 모바일 반응형
- [ ] 모든 기본 비밀번호 변경 (현재 SHA-256(`password`) — 김팀장만 별도 변경됨)
- [ ] DB 일일 백업 자동화
- [ ] 보안 점검: 첨부파일 확장자 화이트리스트 (이미 적용됨, 신규 확장자 필요 시 server.js 수정)
- [ ] 실장(section_chief) 활성 사용자 등록

## 작업 규칙

자세한 내용: `.claude/CLAUDE.md`
- 스크립트는 argparse로 인자 받기 (하드코딩 금지)
- 임시 점검 스크립트는 `tmp/_check_NN_*.py`
- 재사용 스크립트는 `scripts/`
- HTML 페이지 수정 후 curl 응답 200 확인
- JS for/while 루프 검증
- UI 작업은 `html-ui-designer` 서브에이전트에게 위임
- 기능 반영 시 SSOT 원칙 (단일 데이터 소스, 동적 렌더링)

## API 요약

### 일반 CRUD
```
GET    /tables/:table?limit=&search=&sort=&page=
GET    /tables/:table/:id
POST   /tables/:table         body: {...}
PATCH  /tables/:table/:id     body: {...}
PUT    /tables/:table/:id     body: {...}
DELETE /tables/:table/:id
```

### 업무량 모니터링
```
GET    /api/workload/team?from=&to=
GET    /api/workload/user/:memberName?period=week|month|quarter
GET    /api/workload/summary?date=
GET    /api/workload/by-type?from=&to=&scope=team|me
GET    /api/workload/alerts
POST   /api/workload/recompute
```

### KB
```
POST   /api/kb/documents/:id/helpful
POST   /api/kb/documents/:id/view
GET    /api/kb/documents/:id/versions
GET    /api/kb/issues/:id/similar
POST   /api/kb/upload                  body: { filename, content (base64) }
GET    /api/kb/download/:storedName
```

### 보고서 / 자동화
```
POST   /api/reports/generate           body: { type, ym, author }
GET    /api/reports/download/:filename
POST   /api/automate/:type             body: { filename, content (base64), ym }
GET    /api/bot-status
GET    /api/bot-heartbeat
```

## 문제 해결

| 증상 | 원인 / 해결 |
|------|-------------|
| 페이지 변경이 반영 안 됨 | 브라우저 캐시 — Ctrl+Shift+R 또는 main.css/portal.js의 `?v=` 버전 증가 |
| 영업일 수가 틀림 | `business_days` 테이블에 회사휴무 등록/삭제 후 자동 갱신됨 |
| 부하율이 0으로만 나옴 | `daily_work_entries` 미입력 — 개인 대시보드에서 일별 입력 |
| 첨부파일 다운로드 안 됨 | `server/data/kb_files/` 디렉토리 권한 / 디스크 용량 확인 |
| 한글 깨짐 (PowerShell curl) | 콘솔 표시 문제일 뿐 DB는 정상 — 브라우저에서 확인 |

## 라이선스 / 연락

내부용 시스템. 외부 배포 X.
운영 문의: 계리결산팀장 (김민국).
