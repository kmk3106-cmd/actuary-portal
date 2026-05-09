# 계리결산팀 운영관리포탈 코드맵
> 마지막 업데이트: 2026-05-09

---

## 1. 기술 스택

| 구분 | 내용 |
|------|------|
| Frontend | Vanilla HTML + CSS + JavaScript (no framework) |
| Backend | Node.js HTTP server (`server/server.js`, port **8888**) |
| DB | JSON 파일 (`server/data/portal-db.json`) — REST API 자동 지원 |
| 인증 | `js/rbac.js` + `js/auth.js` (세션스토리지 기반 RBAC) |

---

## 2. 서버 실행

```bash
cd "C:\Users\USER\actuary potal\server"
node server.js
```
접속: http://localhost:8888

---

## 3. 파일 구조

```
actuary potal/
├── index.html              대시보드 메인
├── login.html              로그인 페이지
├── identity.html           팀 정체성·핵심가치
├── personnel.html          인사카드 (13명 팀원 카드 그리드)
├── goals-team.html         팀 목표 (KPI1/2/3)
├── goals-individual.html   개인 목표 (SMART)
├── performance.html        성과 관리 (월별/연간집계)
├── directives.html         팀장 지시사항 (신규)
├── interview-list.html     면담일지 목록
├── interview.html          면담일지 뷰어
├── interview-editor.html   면담일지 편집기
├── settlement.html         결산 캘린더 + 체크리스트
├── settlement-review.html  결산 리뷰 (팀장 전용)
├── work-personal.html      개인별 업무입력
├── automation.html         업무 자동화
├── reports.html            보고서 생성
├── bot-status.html         텔레그램 봇 상태
│
├── js/
│   ├── rbac.js             RBAC 엔진 (역할 권한 제어)
│   ├── auth.js             로그인/로그아웃/세션 관리
│   ├── portal.js           공통 유틸 (사이드바 주입, 토스트, 날짜 포맷)
│   └── coming-soon.js      준비중 페이지 유틸
│
├── css/
│   └── main.css            전역 스타일시트
│
├── server/
│   ├── server.js           Node.js HTTP 서버 (REST API 자동 생성)
│   └── data/
│       └── portal-db.json  JSON 파일 DB
│
└── PORTAL_CODEMAP.md       ← 이 파일
```

---

## 4. RBAC 역할 체계

| 역할 | role 값 | 권한 |
|------|---------|------|
| 팀장 | `team_leader` | 모든 기능 + 지시사항 작성 + 결산리뷰 작성 |
| 팀원 | `employee` | 조회/본인 업무입력, 자기 면담일지만 열람 |

**현재 팀장:** 김민국 (`employee_id: 00132526`)

---

## 5. DB 테이블 목록

| 테이블 | 설명 |
|--------|------|
| `users` | 13명 팀원 계정 (id, username, password_hash, role, employee_id 등) |
| `sessions` | 로그인 세션 |
| `team_identity` | 팀 정체성·핵심가치 |
| `core_values` | 핵심가치 항목 |
| `team_goals` | 팀 목표 (KPI) |
| `individual_goals` | 개인 SMART 목표 |
| `performance_records` | 성과 기록 (year, month, target_name, score_* 필드) |
| `work_tasks` | 개인별 업무입력 (결산체크리스트 + 기타업무 + KPI) |
| `settlement_calendar` | 결산 캘린더 일정 |
| `settlement_reviews` | 결산 리뷰 (팀장 전용) |
| `team_directives` | 팀장 지시사항 |
| `automation_logs` | 자동화 실행 로그 |
| `report_history` | 보고서 생성 이력 |
| `interview_logs` | 면담일지 |
| `audit_logs` | 감사 로그 |

---

## 6. 페이지별 주요 기능 상세

### `settlement.html` — 결산 캘린더
- **월별 일정 관리**: 카테고리 필터, 일정 CRUD (팀장만 추가/수정/삭제)
- **D+N 영업일 마감일 자동 표시**: `SETTLE_SCHEDULE` 24개 업무, 한국 공휴일 계산
- **결산업무 체크리스트** (26항목): 완료체크 + 소요시간(분) + 완료일 입력
  - 상태 자동 계산: 조기완료 / 기한준수 / 지연
  - 버튼: `취소` (DB 재로드) / `초기화` (전체 리셋) / `저장`
  - 완료율 → `performance_records.score_deadline` 자동 반영

### `settlement-review.html` — 결산 리뷰 (**팀장 전용**)
- 비팀장 접근 시 잠금 화면 표시
- 탭 전환: 목록뷰 / 캘린더뷰 (12개월 그리드)
- 월별 리뷰 작성: 특이사항, 손익(당기/전월대비/전년동기), 현재이슈, 향후이슈, 팀메모
- 우측 사이드바: 결산체크리스트 진행현황 + 리뷰 이력

### `performance.html` — 성과 관리
- 월별 / 연간집계 선택
- **연간집계 계산**: 각 월 점수 × 1/12 합산 (소수점 1자리 반올림)
- 점수 항목: 팀장평가, 고객만족, 기한준수, 미팅, KPI1/2/3, 자기평가
- 팀장만 기록 추가/수정/삭제 가능

### `work-personal.html` — 개인별 업무입력
- 팀장은 드롭다운에서 본인 제외 (열람/조회만)
- **성과목표업무 (KPI)**: KPI1/2/3 별 업무내용·달성% + 자기평가점수
  - 버튼: `취소` / `저장` / `성과관리에 반영`
- **결산외 업무**: 카테고리, 내용, 난이도, 소요시간
  - 버튼: `취소` / `저장` / `팀 성과에 반영`

### `personnel.html` — 인사카드
- 13명 팀원 카드 그리드 (G1~G4 색상 구분)
- **연차**: 부임일(`dept_date`) 기준 → "XX년 XX개월" 자동 계산
- 팀장만 인사정보 수정 모달

### `directives.html` — 팀장 지시사항
- 팀장: 지시사항 작성/수정/삭제, 전체/개인 대상 지정
- 팀원: 본인 + 전체 공지 열람, 완료 처리
- 우선순위: 긴급(빨강) / 중요(주황) / 보통(회색)
- 필터: 연도 + 대상자

### `js/portal.js` — 공통 유틸
- 사이드바 NAV 구성 (buildSidebar)
- 토스트 알림, 확인 모달, 날짜 포맷 함수
- **현재 NAV 구조**:
  - 메인: 대시보드, **인사카드**
  - 팀 관리: 팀 정체성, 팀 목표, 개인 목표, 성과 관리, **팀장 지시사항**, 면담일지
  - 결산: 결산 캘린더, 결산 리뷰
  - 업무: 개인별 업무입력
  - 자동화: 업무 자동화, 보고서 생성
  - 시스템: 텔레그램 봇

---

## 7. 팀원 계정 목록

| 이름 | 아이디 | 초기 비밀번호 | 역할 |
|------|--------|--------------|------|
| 김민국 | 김민국 | 00132526 | 팀장 |
| 한인석 | 한인석 | 00124137 | 팀원 |
| 이동민 | 이동민 | 00127797 | 팀원 |
| 이상현 | 이상현 | 00128580 | 팀원 |
| 마혜원 | 마혜원 | 00133429 | 팀원 |
| 예대호 | 예대호 | 00134537 | 팀원 |
| 이성원 | 이성원 | 00139804 | 팀원 |
| 고인수 | 고인수 | 00139824 | 팀원 |
| 김예은 | 김예은 | 00139855 | 팀원 |
| 강세진 | 강세진 | 00140782 | 팀원 |
| 이용우 | 이용우 | 00142352 | 팀원 |
| 오정택 | 오정택 | 00142393 | 팀원 |
| 김채린 | 김채린 | 00142811 | 팀원 |

---

## 8. REST API 패턴

서버는 `portal-db.json`의 최상위 키를 테이블로 인식하여 자동으로 CRUD API 제공:

| Method | URL | 설명 |
|--------|-----|------|
| GET | `/tables/:table?limit=N&offset=M` | 목록 조회 |
| GET | `/tables/:table/:id` | 단건 조회 |
| POST | `/tables/:table` | 신규 생성 (id 자동 생성) |
| PUT | `/tables/:table/:id` | 전체 수정 |
| DELETE | `/tables/:table/:id` | 삭제 |

---

## 9. 변경 이력

| 날짜 | 변경 내용 |
|------|-----------|
| 2026-05-09 | 초기 Phase 완료: 전체 페이지 구조, RBAC, 13명 계정 |
| 2026-05-09 | settlement.html: D+N 마감일 캘린더, 체크리스트 26항목, 취소/저장 버튼 |
| 2026-05-09 | settlement-review.html: 팀장 전용, 캘린더뷰 탭 추가 |
| 2026-05-09 | performance.html: 월별 세분화, 연간집계 1/12 가중치 |
| 2026-05-09 | work-personal.html: KPI 섹션, 취소 버튼, 팀장 업무자 제외 |
| 2026-05-09 | personnel.html: 인사카드, 부임일 기준 연차(XX년 XX개월), 메인 메뉴 이동 |
| 2026-05-09 | directives.html: 팀장 지시사항 신규 페이지 |
| 2026-05-09 | portal.js: 인사카드→메인, 팀장지시사항 추가 |
| 2026-05-09 | 보고서 자동생성: generator.py 엑셀 연동 완성 (계리보고서 6섹션) |
