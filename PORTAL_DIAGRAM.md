# 계리결산팀 운영관리포탈 — 시스템 구조 문서

| 항목 | 내용 |
|------|------|
| **버전** | v1.4 |
| **최종 갱신** | 2026-05-10 |
| **작성** | Claude Sonnet 4.6 (kmk3106 검토) |
| **대상** | 신규 개발자 온보딩 · 인수인계 · 운영 참조 |

---

## 1. 전체 페이지 맵

```
index.html (대시보드)
│
├── [팀 관리]
│   ├── identity.html          팀 정체성 · 핵심가치
│   ├── goals-team.html        팀 목표
│   ├── goals-individual.html  개인 목표 (SMART)
│   ├── personnel.html         인사카드 (부임일·연차)
│   └── directives.html        팀장 지시사항            ← 팀장 전용 (입력)
│
├── [결산 관리]
│   ├── settlement.html        결산 캘린더 + 체크리스트  ← 핵심 데이터 생성
│   └── settlement-review.html 결산 리뷰                ← 팀장 전용
│
├── [성과 관리]
│   ├── performance.html       성과관리 종합표 · 개인카드
│   └── work-personal.html     개인별 업무입력 (정량평가)
│
├── [자동화 · 보고]
│   ├── automation.html        업무 자동화 로그
│   └── reports.html           보고서 자동생성 (계리/경영/재무)
│
└── [모니터링]
    └── bot-status.html        텔레그램 봇 상태
```

---

## 2. 데이터 흐름 (핵심 선후관계)

### 2-1. 결산기한준수 점수 흐름

```
[settlement.html] 결산 체크리스트
  ① 팀원이 완료일 입력 (date input)
  ② autoCalcDeadline()
       └ getRelativeBizDay() — 이전달 날짜 처리
           · 이전달 마지막 영업일 = 0
           · 그전 영업일 = -1, -2, ...
           · 당월 N번째 영업일 = N
       └ diff = task.due(D+N) - compBiz → 단축/지연일 자동산출
       └ 클램프: -3 이하 → -3, +2 이상 → +2
  ③ 저장(saveChecklist()) 클릭
       └→ work_tasks 테이블 저장
            settlement_deadline_days: { s01:2, s12:0, s20:-1, ... }
       └→ pushDeadlineToPerf() 자동 호출
            └ calcDeadlineAvgScore()
                 담당 업무 필터 → calcDeadlinePerfScore() 각각 → 동일가중치 평균
            └→ performance_records.score_deadline 갱신

[performance.html] score_deadline 자동 반영
```

### 2-2. 정량평가 전체 흐름

```
[work-personal.html] 개인별 업무입력
  ① 팀원이 정량 지표 입력:
       s1: 지시수행   (건수)
       s2: 재무수치안 (건수)
       s3: 결산기한준수 ← settlement.html에서 자동유입 (읽기전용)
       s4: 임원회의소스 (건수)
  ② "성과관리에 반영" 클릭 → pushQuantToPerf()
       └→ performance_records 갱신
            score_directive / score_csm / score_deadline / score_meeting

[performance.html] 점수 자동 계산
  기본점수 = Σ(score × weight)
  최종점수 = 기본점수 × (1 + bonus_rate)
  bonus_rate: 프로젝트 +10%, 승진대상 +10% (중복 가산 가능)
```

### 2-3. 텔레그램 봇 흐름

```
사용자 텔레그램 메시지
  └→ bot/app.py (polling)
       └ _is_allowed() — ALLOWED_USER_IDS 체크 (비어있으면 전체 허용)
       └ parser.py.parse_query() → ParsedQuery(intent, period, metric, scope, model)
       └ query_engine.py — actuarial.db 직접 쿼리
       └ formatters.py — 마크다운 포맷
       └ 텔레그램 응답 전송
       └ db.py.log_query() → actuarial.db 쿼리 로그 적재
```

### 2-4. 보고서 생성 흐름

```
[reports.html]
  ① 유형 선택 + 기준월 + 작성자
  ② POST /api/reports/generate
       └→ server.js → Python 스크립트 실행 (reports/make_*.py)
       └→ report_history 테이블 저장
  ③ GET /api/reports/download/:filename → reports/output/*.docx
  ④ DELETE /tables/report_history/:id → 이력 삭제
```

---

## 3. 점수 산출 규칙

### 3-1. 결산기한준수 (score_deadline)

| 단축/지연일 | 의미 | 점수 |
|------------|------|------|
| +2 이상 | 2영업일 이상 조기마감 | 100 |
| +1 | 1영업일 조기마감 | 90 |
| 0 | 기한 당일 준수 | 80 |
| -1 | 1영업일 지연 | 70 |
| -2 | 2영업일 지연 | 60 |
| -3 이하 | 3영업일 이상 지연 | 0 |

> **복수 업무 담당 예시 (한인석)**
> - 결산모델배포 +1일 → 90점
> - 후속측정보험부채산출 0일 → 80점
> - 최종 score_deadline = (90 × 0.5) + (80 × 0.5) = **85점**

### 3-2. 최종점수 가중치

| 항목 | 비중 | 입력 주체 |
|------|------|----------|
| 지시수행 | 5% | 팀원 (건수→자동환산) |
| 재무수치안 | 10% | 팀원 (건수→자동환산) |
| 기한준수 | 20% | 자동 (settlement.html) |
| 임원소스 | 15% | 팀원 (건수→자동환산) |
| KPI1 계리모델AI활용 | 20% | 팀장 직접 입력 |
| KPI2 재무수치분석 | 20% | 팀장 직접 입력 |
| KPI3 계리지원강화 | 10% | 팀장 직접 입력 |
| **합계** | **100%** | |

가산: 기본점수 × (1 + 0.1×프로젝트 + 0.1×승진대상)

---

## 4. RBAC 권한 매트릭스

역할: `team_leader(팀장)` / `section_chief(실장)` / `member(팀원)`

| 페이지 / 액션 | 팀장 | 실장 | 팀원 |
|--------------|------|------|------|
| 대시보드 조회 | O | O | O |
| 팀 정체성·목표 조회·편집 | O | O | O |
| 개인 목표 (본인) | O | O | O |
| 결산 캘린더 조회 | O | O | O |
| 결산 체크리스트 입력 | O (전원) | — | 본인만 |
| 결산 리뷰 | O | X | X |
| 팀장 지시사항 입력 | O | X | X (조회만) |
| 성과 종합표 전체 조회 | O | O | X |
| 성과 종합표 본인 조회 | O | O | O |
| 개인카드 가산 체크박스 | O | X | X |
| KPI1~3 점수 입력 | O | X | X |
| 개인별 업무입력 (본인) | O | O | O |
| 인사카드 편집 | O | O | X |
| 면담일지 작성·수정·삭제 | O | X | X |
| 면담일지 열람 (비밀 제외) | O | O | 본인만 |
| 면담일지 확인 서명 | O | O | 본인만 |
| 보고서 생성·이력 삭제 | O | O | O |
| 업무 자동화 실행 | O | O | O |

> **구현 위치**: `js/rbac.js`
> - `RBAC.isTeamLeader()` — 팀장 여부
> - `RBAC.checkInterviewAccess(action, log)` — 면담일지 세부 권한
> - 세션: `sessionStorage('rbac_session')` 저장, 만료시간 서버 발급

---

## 5. API 엔드포인트 목록

### 5-1. 전용 API (`/api/...`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/reports/generate` | 보고서 생성 (body: type, ym, author) |
| GET | `/api/reports/download/:filename` | 보고서 .docx 다운로드 |
| POST | `/api/automate/public_rate` | 공시이율 자동화 |
| POST | `/api/automate/assumption` | 가정 자동화 |
| POST | `/api/automate/expense_ratio` | 예정사업비율 자동화 |
| GET | `/api/bot-status` | 텔레그램 봇 쿼리 로그 조회 |
| GET | `/api/bot-heartbeat` | 봇 생존 상태 (last_alive, pid) |

### 5-2. 범용 테이블 CRUD (`/tables/:table[/:id]`)

모든 테이블에 동일 패턴 자동 지원 (`server.js → handleTablesRequest`):

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/tables/:table` | 전체 조회 (search, sort, page, limit 파라미터) |
| GET | `/tables/:table/:id` | 단건 조회 |
| POST | `/tables/:table` | 신규 생성 (id 자동 부여) |
| PUT / PATCH | `/tables/:table/:id` | 수정 |
| DELETE | `/tables/:table/:id` | 삭제 |

**테이블 목록:**
```
users, sessions, team_identity, core_values, team_goals,
individual_goals, performance_records, work_tasks,
settlement_calendar, settlement_reviews, team_directives,
automation_logs, report_history, interview_logs, audit_logs
```

---

## 6. DB 구조 (주요 테이블)

### work_tasks — 개인별 업무 입력값 (결산+정량 통합)

```
id, year, month, member_name

  [결산 체크리스트]
  settlement_done[]          완료 결산업무 id 목록 (e.g. ["s01","s12"])
  settlement_dates{}         taskId → 완료일 (YYYY-MM-DD)
  settlement_times{}         taskId → 소요시간(분)
  settlement_deadline_days{} taskId → 단축(+)/지연(-) 일수

  [정량평가 raw값]
  quantitative_data{}        { s1:건수, s2:건수, s4:건수 }
                             ※ s3(결산기한준수)는 settlement에서 자동유입
```

> 결산 체크리스트 컬럼과 정량평가 raw값이 **하나의 work_tasks 테이블**에 함께 저장됩니다.

### performance_records — 성과 평가

```
id, year, month, target_name, target_user_id

  [정량 — 자동유입]
  score_directive   지시수행 점수
  score_csm         재무수치안 점수
  score_deadline    기한준수 점수  ← settlement.html 저장 시 자동 갱신
  score_meeting     임원소스 점수

  [정성 — 팀장 직접 입력]
  score_kpi1 / score_kpi2 / score_kpi3

  [계산 결과]
  basic_score       기본점수 (가중치 합산)
  final_score       최종점수 = basic_score × (1 + bonus_rate)
  grade             S / A / B / C / D

  [가산]
  bonus_project / bonus_promotion   boolean

  [서술형]
  self_score, self_comment, leader_score, leader_comment
```

---

## 7. 동시성 · 장애 시나리오

### JSON 파일 DB (portal-db.json)

| 항목 | 현황 |
|------|------|
| **쓰기 방식** | `withDb()` 비동기 직렬 큐 — 동시 쓰기 충돌 방지 |
| **원자성** | 메모리 수정 후 파일 전체 덮어쓰기 (트랜잭션 없음) |
| **동시 읽기** | 잠금 없음, 읽기 경합 무해 |
| **백업** | 자동 백업 없음 → **주기적 수동 백업 필수** (`portal-db.json` 복사) |
| **롤백** | 장애 시 마지막 저장 파일 상태로만 복구 가능 |

### 봇 DB (actuarial.db — SQLite)

| 항목 | 현황 |
|------|------|
| **동시성** | WAL 모드 — 단일 쓰기 + 다중 읽기 허용 |
| **백업** | `server/data/actuarial.db` 파일 복사로 백업 |

### 장애 대응

```
1. 포탈 접속 불가
   → tasklist | findstr node  (node.exe 확인)
   → node server/server.js 재기동

2. 텔레그램 봇 응답 없음
   → tasklist | findstr python
   → bot/run.bat 또는 python bot/app.py
   → bot/data/bot.log 마지막 라인 확인

3. 데이터 저장 실패 토스트
   → server/server.log 확인
   → portal-db.json 파일 잠금 여부 확인

4. portal-db.json 손상
   → 최근 백업으로 교체
   → 없으면 서버 기동 시 빈 DB 자동 초기화 (데이터 유실 주의)
```

---

## 8. 텔레그램 봇 상세

### 명령어 목록

| 명령어 | 설명 | 예시 |
|--------|------|------|
| `/start` | 봇 소개 + 적재 기간 안내 | `/start` |
| `/help` | 문법 도움말 + 전체 예시 | `/help` |
| `/periods` | 적재된 기준월 목록 | `/periods` |
| `/query [기준월] [범위] [지표]` | 표준 데이터 조회 | `/query 202603 누적 보험손익` |
| `/조회 [기준월] [범위] [지표]` | 한글 명령 (위와 동일) | `/조회 202603 월말 csm잔액` |
| 자연어 텍스트 | 명령어 없이 조회 | `26년3월말 csm잔액은?` |

### 지원 Intent (조회 유형)

| Intent | 설명 |
|--------|------|
| `balance_single` | 단일 지표 잔액 (BEL, RA, CSM, LOSS 등) |
| `balance_by_model` | 회계모형별 잔액 |
| `balance_bundle_by_model` | BEL+RA+CSM 묶음 조회 |
| `pl_summary` | 손익 요약 |
| `pl_by_model` | 회계모형별 손익 (당월/누적 구분 필수) |
| `csm_movement_model` | 특정 모형 CSM 무브먼트 |
| `csm_movement_compare` | 전체 모형 CSM 무브먼트 비교 |

### 접근 제어 · 로그

```
[접근 제어]
bot/.env → ALLOWED_USER_IDS=
  · 비어있으면 전체 허용
  · 쉼표 구분 텔레그램 user_id 명시 시 해당 사용자만 허용

[로그]
bot/data/bot.log            현재 로그 (매일 자정 로테이션)
bot/data/bot_YYYYMMDD.log   과거 로그 (30일 보관)
server/data/bot-heartbeat.json  봇 생존 상태 (1시간마다 갱신)
```

---

## 9. SETTLE_SCHEDULE 담당자 매핑 (26개 항목)

| ID | 그룹 | 항목 | 담당자 | D+ |
|----|------|------|--------|-----|
| s01 | IFRS4 | 계리계약마감 | 오정택 | 1 |
| s02 | IFRS4 | 지급준비금마감(실효만기) | 이용우 | — |
| s03 | IFRS4 | 지급준비금마감(생존사고) | 이용우 | — |
| s04 | IFRS4 | 준비금마감 | 강세진 | — |
| s05 | IFRS4 | 보험료분해마감 | 김채린 | 9 |
| s06 | IFRS4 | 재보험마감 | 김예은 | — |
| s07 | IFRS4 | 보증준비금마감 | 강세진 | — |
| s08 | IFRS4 | 잉여금처리&계약자배당 | 이상현 | — |
| s09 | IFRS4 | 예금보험료 | 강세진 | — |
| s10 | IFRS17 BEL&RA | 결산모델배포 | 한인석 | — |
| s11 | IFRS17 BEL&RA | 계리모델입력데이터준비 | 김예은/이성원 | — |
| s12 | IFRS17 BEL&RA | 경제적가정산출 | 이상백 | — |
| s13 | IFRS17 BEL&RA | 최초/후속모델포인트생성 | 이성원 | — |
| s14 | IFRS17 BEL&RA | 최초인식보험부채산출 | 김예은 | — |
| s15 | IFRS17 BEL&RA | 후속측정보험부채산출 | 한인석/이성원 | 12 |
| s16 | IFRS17 BEL&RA | 사업비배부 | 마혜원 | — |
| s17 | IFRS17 부채결산 | 최초인식대상계약확정 | 이용우 | — |
| s18 | IFRS17 부채결산 | 결산대상계약확정 | 이용우 | — |
| s19 | IFRS17 부채결산 | 가중평균할인율산출 | 예대호 | — |
| s20 | IFRS17 부채결산 | BEL/RA data입수및계약그룹 | 이동민 | — |
| s21 | IFRS17 부채결산 | 결산대상계약및실제CF이관(재보험) | 김예은 | — |
| s22 | IFRS17 부채결산 | 실제CF Data이관(ETL) | 이동민 | — |
| s23 | IFRS17 부채결산 | 가중평균할인율산출(재보험) | 예대호 | — |
| s24 | IFRS17 부채결산 | BEL/RA data입수(재보험) | 김예은 | — |
| s25 | IFRS17 부채결산 | 부채결산무브먼트 | 이동민 | — |
| s26 | IFRS17 부채결산 | 부채결산무브먼트(재보험) | 김예은 | — |
| s27 | IFRS17 부채결산 | 회계팀결산Data전송 | 예대호 | — |

> `/` 구분 담당자 → 두 사람 모두 해당 업무 수행, 각자 결산기한준수 점수에 독립 반영

---

## 10. 서버 구동 순서

```bash
# 1. 포탈 서버 (port 8888)
node server/server.js

# 2. 텔레그램 봇 (별도 프로세스)
cd bot && python app.py
# Windows 편의: bot/run.bat (내부 venv 경로 지정됨)

# 접속
http://localhost:8888

# 상태 확인
curl http://localhost:8888/api/bot-heartbeat
```

---

## 11. 파일 구조

```
actuary potal/
├── index.html                  대시보드
├── settlement.html             결산캘린더+체크리스트 (핵심)
├── performance.html            성과관리
├── work-personal.html          개인별업무입력
├── reports.html                보고서생성
├── bot-status.html             봇상태
├── *.html                      기타 페이지
│
├── js/
│   ├── portal.js               공통 유틸 (showToast, confirm, formatDate 등)
│   ├── rbac.js                 역할기반접근제어
│   └── auth.js                 로그인·세션 처리
│
├── css/
│   └── main.css                공통 스타일
│
├── server/
│   ├── server.js               Node.js HTTP 서버 (port 8888)
│   └── data/
│       ├── portal-db.json      JSON 파일 DB ← 핵심 데이터, 백업 필수
│       ├── actuarial.db        SQLite (봇 조회용 결산 수치)
│       └── bot-heartbeat.json  봇 생존 상태
│
├── bot/                        텔레그램 봇 (Python)
│   ├── app.py                  메인 진입점 + 핸들러 등록
│   ├── parser.py               자연어 → ParsedQuery
│   ├── query_engine.py         SQLite 쿼리 실행
│   ├── formatters.py           응답 마크다운 포맷
│   ├── db.py                   DB 초기화 + 쿼리 로그
│   ├── settings.py             환경변수 로드
│   ├── .env                    봇 토큰 (git 추적 주의)
│   ├── run.bat                 Windows 기동 스크립트
│   └── data/
│       ├── bot.log             현재 로그 (30일 로테이션)
│       └── bot_YYYYMMDD.log    과거 로그
│
├── scripts/                    재사용 Python 스크립트 (argparse 필수)
├── reports/
│   ├── make_*.py               보고서 생성 스크립트
│   └── output/                 생성된 .docx 파일
├── automation/                 자동화 스크립트
├── tmp/                        임시 점검 스크립트 (_check_NN_설명.py)
│
├── PORTAL_DIAGRAM.md           본 파일 (시스템 구조 문서)
└── PORTAL_CODEMAP.md           코드맵 (함수별 위치)
```

---

## 12. 용어집

| 약어 / 용어 | 풀이 |
|-------------|------|
| **BEL** | Best Estimate Liability — 최선추정부채 |
| **RA** | Risk Adjustment — 위험조정 |
| **CSM** | Contractual Service Margin — 계약서비스마진 |
| **LOSS** | 손실부담계약 손실요소 |
| **IFRS17** | 국제회계기준 17호 — 보험계약 회계 기준 |
| **IFRS4** | 국제회계기준 4호 (IFRS17 전환 이전 기준) |
| **K-ICS** | 한국형 지급여력제도 (보험사 재무건전성 지표) |
| **ETL** | Extract-Transform-Load — 데이터 추출·변환·적재 |
| **D+N** | 결산 기준일로부터 N번째 영업일 (마감기한 표기) |
| **무브먼트** | Movement — 기초→기말 잔액 변동 내역 분해 |
| **모델포인트** | 계리 모델 입력 단위 — 유사 계약 집합 대표값 |
| **NP 모형** | Non-Participating — 무배당 상품 계리 회계모형 |
| **BEL&RA 산출** | 계리 모델로 최선추정부채·위험조정을 산출하는 작업 |
| **가중평균할인율** | 보험부채 현재가치 산출에 적용하는 할인율 |
| **RBAC** | Role-Based Access Control — 역할기반 접근제어 |
| **결산기한준수** | 담당 결산업무를 D+N 기한 내 완료한 실적 지표 |
| **WAL** | Write-Ahead Logging — SQLite 동시성 모드 |
