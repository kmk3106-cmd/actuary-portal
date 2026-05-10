# 계리결산팀 운영관리포탈 — 업무 모니터링 & 지식관리 모듈 구현 요구사항

> Claude Code 작업 지시서. 이 문서를 그대로 첨부하거나 붙여넣은 뒤 "이 요구사항대로 구현 시작해줘"라고 지시하면 됩니다.

---

## 0. 작업 개요

기존 actuary-portal에 **두 개의 신규 모듈**을 추가합니다.

- **모듈 A**: 개인별 업무량 모니터링 대시보드 (과중/유휴 판단)
- **모듈 B**: 지식관리(Knowledge Base) — SOP, 이슈 사례집, 인수인계, 온보딩

기존 시스템에는 이미 다음이 구현되어 있다고 가정:
- 개인별 업무 기입 기능 (업무명, 담당자, 일자 등)
- 소요시간 기입 필드
- RBAC (팀장/실장 등 역할 구분)
- 감사 로그

⚠️ **이 가정이 틀리면 0단계에서 자동 수정**하도록 작업 절차에 포함되어 있음.

---

## 1. 0단계: 사전 분석 (Claude Code가 가장 먼저 할 일)

코드 수정 시작 전에 **반드시 다음을 파악**하고 결과를 사용자에게 보고할 것:

### 1.1 환경 파악
```
[ ] 백엔드 프레임워크 (Express? Fastify? 기타?)
[ ] DB 종류 (SQLite / MySQL / PostgreSQL / 기타)
[ ] ORM 사용 여부 (Sequelize / Prisma / Knex / Raw SQL)
[ ] 프론트엔드 스택 (Vanilla JS / React / Vue / 기타)
[ ] 차트 라이브러리 사용 여부 (Chart.js / ECharts / Recharts 등)
[ ] 인증 방식 (Session / JWT / 기타)
```

### 1.2 기존 스키마 분석
다음 테이블/컬럼이 있는지 확인하고 **현재 구조를 출력**할 것:
- 사용자 테이블 (users 등) → id, name, role, department 등
- 업무 기입 테이블 (tasks / works / activities 등) → 어떤 필드가 있는지
- 업무 유형/카테고리 테이블 존재 여부
- 일자 필드 형식 (DATE? DATETIME? 문자열?)
- 소요시간 필드 단위 (분? 시간? 0.5시간 단위?)

### 1.3 보고 후 진행
위 분석 결과를 사용자에게 보여주고 **"이 분석 기반으로 진행해도 되는지" 확인 받은 뒤** 다음 단계로 진행.

---

## 2. 모듈 A: 업무량 모니터링 대시보드

### 2.1 핵심 지표 정의

#### 환경변수로 빼야 할 기준값 (`.env` 또는 config)
```
WORK_HOURS_PER_DAY=8           # 표준 1일 근무시간
OVERLOAD_THRESHOLD=1.2         # 과중 판단 (표준 대비 120% 초과)
IDLE_THRESHOLD=0.7             # 유휴 판단 (표준 대비 70% 미만)
```

⚠️ **MM은 고정값이 아니라 매월 동적 계산**:
- 1MM = `해당 월 영업일 수 × WORK_HOURS_PER_DAY`
- 예: 2026년 2월 영업일 19일 → 1MM = 152시간
- 예: 2026년 7월 영업일 23일 → 1MM = 184시간
- 영업일 = 평일 - 공휴일 - 회사 지정 휴무일

#### 영업일 산정 정책
- **한국 법정공휴일**: 자동 반영 (DB 시드 + 매년 갱신 가능 구조)
- **회사 지정 휴무**: 창립기념일, 임시휴무 등 → 관리자가 직접 등록
- **반차/연차**: 개인 휴가는 영업일에서 제외하지 **않음** (개인 휴가는 별도 트래킹)
  - 단, 향후 휴가 시스템 연동 시 개인별 분모 보정 가능하도록 확장 여지 남김

#### 산출 지표
| 지표 | 정의 | 산식 |
|---|---|---|
| 일 투입시간 | 특정 일자 개인 총 소요시간 합 | `SUM(소요시간) WHERE user=A AND date=D` |
| 주 투입시간 | 주간 합산 | `SUM(소요시간) WHERE user=A AND date BETWEEN [주시작, 주끝]` |
| 월 투입시간 | 월간 합산 | 위와 동일, 월 단위 |
| 월 표준시간 | 해당 월 영업일 × 8h | `business_days(YYYY-MM) × 8` |
| MM 환산 | 월 투입시간 ÷ 월 표준시간 | 표준시간 만큼 입력 = 1.0 MM |
| 일 부하율 | 일 투입시간 ÷ 8 | 8h = 100%, 10h = 125% |
| 월 부하율 | 월 투입시간 ÷ 월 표준시간 | 영업일 19일인 달에 152h = 100% |
| 과중 플래그 | 일 부하율 > 120% (3 영업일 연속) | 주말/공휴일은 카운트 제외 |
| 유휴 플래그 | 일 부하율 < 70% (5 영업일 연속) | 주말/공휴일은 카운트 제외 |
| 미입력 플래그 | 영업일인데 입력 0건 | 주말/공휴일은 알림 제외 |
| 업무유형별 점유율 | 유형별 시간 합 / 전체 시간 | 파이차트 데이터 |

⚠️ **연속일 카운트는 반드시 "영업일 연속"** — 금요일 과중 + 월요일 과중이면 주말 건너뛰고 2일 연속으로 카운트.

### 2.2 화면 구성

#### A. 팀 전체 대시보드 (`/dashboard/team`) — 팀장/실장 권한
1. **상단 KPI 카드 4개**
   - 이번 주 팀 전체 투입시간 / 표준 대비 %
   - 과중 인원 수 (빨간 뱃지)
   - 유휴 인원 수 (회색 뱃지)
   - 미입력 인원 수 (어제 입력 0건인 사람)

2. **팀 히트맵** (가장 중요)
   - X축: 최근 30일 (영업일/주말/공휴일 시각적 구분)
   - Y축: 팀원
   - 셀 색상: 부하율 — 초록(정상) / 노랑(약간 과중) / 빨강(과중) / 회색(유휴) / 흰색(미입력)
   - 주말/공휴일 컬럼: **빗금 패턴 + 휴일명 툴팁** (예: "어린이날")
   - 셀 클릭 시 해당 일자 업무 상세 모달
   - 미입력 알림 계산은 영업일만 대상

3. **개인별 비교 막대 차트**
   - 이번 주 / 이번 달 / 이번 분기 토글
   - 정렬: 시간 많은 순 / 적은 순

4. **업무 유형별 팀 분포 도넛 차트**
   - 결산 / 검증 / 보고서 작성 / 회의 / 기타 등 유형별 시간 비중

#### B. 개인 대시보드 (`/dashboard/me`) — 모든 사용자
1. **본인 시계열 라인 차트** (최근 90일, 주말/공휴일은 회색 배경 표시)
2. **부하율 게이지** (이번 주 / 이번 달 토글)
   - 이번 달 게이지 계산: 누적 입력시간 ÷ (지나간 영업일 × 8)
   - 월말 시점 예상 MM도 표시 (현재 페이스 유지 시)
3. **업무 유형별 본인 분포**
4. **누적 MM** (분기/연 단위) — 각 월마다 영업일 다르므로 합산 시 주의
5. **이번 달 기준 정보 카드**
   - 이번 달 영업일 수 (예: "2026년 5월 영업일 20일")
   - 이번 달 표준시간 (예: "표준 160시간")
   - 현재까지 입력시간 / 잔여 영업일
6. **본인 입력 누락일 알림** (영업일만 카운트, 주말 미입력은 알림 X)

### 2.3 알림/임계치
- 매일 오전 9시: 전일 미입력자에게 알림 (이메일 또는 인앱)
- 과중 3일 연속: 본인 + 팀장에게 알림
- 유휴 5일 연속: 팀장에게만 알림 (본인은 자동 알림 X)
- 알림 채널은 우선 **인앱 + 이메일**, 추후 슬랙/팀즈 확장 가능하게 모듈화

### 2.4 데이터 내보내기
- 월간 리포트 Excel 다운로드
- 컬럼: 사번/이름/일자/업무유형/업무명/소요시간/비고
- 권한: 팀장만 전체 / 본인은 본인 것만

---

## 3. 모듈 B: 지식관리 (Knowledge Base)

### 3.1 SOP 문서 모듈 (`/kb/sop`)
- 카테고리 트리 구조 (예: 결산 > 월결 > 책임준비금 산출)
- 마크다운 에디터 (작성/수정)
- 버전 관리: 수정 시 이전 버전 보관, diff 보기
- 첨부파일 지원 (Excel, PDF)
- **검색**: 제목 + 본문 + 태그 풀텍스트 검색
- 권한: 작성/수정 = 책임자 이상, 읽기 = 전원
- 조회수/유용성 평가(👍) 기록 → 자주 참조되는 SOP 식별

### 3.2 이슈 사례집 (`/kb/issues`)
필드 구조:
```
- 제목
- 발생일자
- 카테고리 (시스템/회계/규정/기타)
- 영향도 (High/Medium/Low)
- 증상 설명
- 원인 분석
- 해결 방법
- 재발방지 조치
- 담당자
- 관련 SOP 링크
- 첨부파일
- 태그
```
- 검색은 모든 필드 대상
- "유사 이슈 보기" 기능 (태그/카테고리 기반)

### 3.3 인수인계 체크리스트 (`/kb/handover`)
- 템플릿 기반 (체크리스트 항목 미리 정의)
- 인계자/인수자/인계일자 메타데이터
- 항목별: 설명 / 관련 문서 링크 / 완료 여부 / 비고
- PDF 출력 (기록 보관용)

### 3.4 온보딩 트랙 (`/kb/onboarding`)
- 신규 입사자 등록 시 자동 생성
- 단계: D+1 / W+1 / M+1 / M+3 / M+6
- 각 단계별: 학습 자료 / 미팅 일정 / 체크포인트 / 멘토 코멘트
- 진행률 시각화 (프로그레스 바)
- 멘토 + 본인 + 팀장 3자 뷰

---

## 4. 데이터 모델 (제안)

> ⚠️ 0단계 분석 후 기존 테이블이 있으면 **기존 것 활용 + 컬럼 추가**, 없으면 신규 생성

### 4.1 신규/확장 필요 테이블

```sql
-- 기존 tasks(또는 동등 테이블)에 컬럼 추가가 필요한 경우
ALTER TABLE tasks ADD COLUMN task_type_id INT;
ALTER TABLE tasks ADD COLUMN duration_minutes INT;  -- 소요시간 (분 단위 권장)

-- 업무 유형 마스터
CREATE TABLE task_types (
  id INTEGER PRIMARY KEY,
  name VARCHAR(100) NOT NULL,           -- 결산, 검증, 보고서, 회의 등
  parent_id INTEGER,                     -- 계층 구조 가능
  is_active BOOLEAN DEFAULT TRUE,
  display_order INT
);

-- 일별 부하율 캐시 (실시간 계산이 무거우면 사용)
CREATE TABLE workload_daily_cache (
  user_id INT,
  work_date DATE,
  total_minutes INT,
  load_ratio DECIMAL(5,2),               -- 부하율
  status VARCHAR(20),                    -- normal/overload/idle/empty
  computed_at DATETIME,
  PRIMARY KEY (user_id, work_date)
);

-- 영업일 마스터 (휴일 관리)
CREATE TABLE business_days (
  calendar_date DATE PRIMARY KEY,
  is_business_day BOOLEAN NOT NULL,      -- TRUE=영업일, FALSE=휴일
  day_type VARCHAR(20),                  -- 'workday'/'weekend'/'public_holiday'/'company_holiday'
  holiday_name VARCHAR(100),             -- 예: '설날', '창립기념일'
  note VARCHAR(255),
  updated_by INT,
  updated_at DATETIME
);

-- 월별 영업일 수 캐시 (조회 성능용)
CREATE TABLE business_days_monthly (
  year_month CHAR(7) PRIMARY KEY,        -- 'YYYY-MM'
  business_day_count INT NOT NULL,
  standard_hours INT NOT NULL,           -- business_day_count × 8
  computed_at DATETIME
);

-- SOP 문서
CREATE TABLE kb_documents (
  id INTEGER PRIMARY KEY,
  category_id INT,
  title VARCHAR(255),
  content TEXT,                          -- 마크다운
  version INT DEFAULT 1,
  author_id INT,
  view_count INT DEFAULT 0,
  helpful_count INT DEFAULT 0,
  is_published BOOLEAN DEFAULT FALSE,
  created_at DATETIME,
  updated_at DATETIME
);

CREATE TABLE kb_document_versions (
  id INTEGER PRIMARY KEY,
  document_id INT,
  version INT,
  content TEXT,
  modified_by INT,
  modified_at DATETIME,
  change_note TEXT
);

CREATE TABLE kb_categories (
  id INTEGER PRIMARY KEY,
  name VARCHAR(100),
  parent_id INT,
  display_order INT
);

-- 이슈 사례
CREATE TABLE kb_issues (
  id INTEGER PRIMARY KEY,
  title VARCHAR(255),
  occurred_at DATE,
  category VARCHAR(50),
  severity VARCHAR(20),                  -- high/medium/low
  symptom TEXT,
  root_cause TEXT,
  resolution TEXT,
  prevention TEXT,
  owner_id INT,
  related_sop_id INT,
  tags VARCHAR(255),                     -- 콤마 구분
  created_at DATETIME
);

-- 인수인계
CREATE TABLE kb_handovers (
  id INTEGER PRIMARY KEY,
  from_user_id INT,
  to_user_id INT,
  handover_date DATE,
  status VARCHAR(20),                    -- in_progress/completed
  created_at DATETIME
);

CREATE TABLE kb_handover_items (
  id INTEGER PRIMARY KEY,
  handover_id INT,
  item_text TEXT,
  related_doc_id INT,
  is_completed BOOLEAN,
  note TEXT
);

-- 온보딩
CREATE TABLE kb_onboarding_tracks (
  id INTEGER PRIMARY KEY,
  user_id INT,
  mentor_id INT,
  start_date DATE,
  status VARCHAR(20)
);

CREATE TABLE kb_onboarding_milestones (
  id INTEGER PRIMARY KEY,
  track_id INT,
  stage VARCHAR(20),                     -- D+1 / W+1 / M+1 / M+3 / M+6
  title VARCHAR(255),
  description TEXT,
  due_date DATE,
  is_completed BOOLEAN,
  completed_at DATETIME,
  mentor_comment TEXT
);
```

### 4.2 인덱스 권장
- `tasks(user_id, work_date)` — 일별/주별 조회 핵심
- `tasks(task_type_id)` — 유형별 집계
- `workload_daily_cache(work_date)` — 팀 히트맵
- `kb_documents(category_id, is_published)` — SOP 트리 조회
- 풀텍스트 인덱스 (DB 종류에 따라): `kb_documents.title, content`, `kb_issues.title, symptom`

---

## 5. API 엔드포인트 (제안)

### 5.1 모니터링 API
```
GET  /api/workload/team?from=YYYY-MM-DD&to=YYYY-MM-DD
     → 팀 전체 히트맵 데이터 (영업일/휴일 정보 포함)

GET  /api/workload/user/:userId?period=week|month|quarter
     → 개인 시계열

GET  /api/workload/summary?date=YYYY-MM-DD
     → 상단 KPI 카드 4개 데이터

GET  /api/workload/by-type?from=...&to=...&scope=team|me
     → 업무 유형별 분포

GET  /api/workload/alerts
     → 현재 본인/팀의 알림 목록 (과중/유휴/미입력)

GET  /api/workload/export?month=YYYY-MM
     → Excel 다운로드 (팀장만)

POST /api/workload/recompute
     → 부하율 캐시 재계산 트리거 (관리자)
```

### 5.1.1 영업일 관리 API (관리자/팀장)
```
GET    /api/business-days?from=YYYY-MM-DD&to=YYYY-MM-DD
       → 기간 내 영업일/휴일 목록

GET    /api/business-days/monthly/:yearMonth
       → 'YYYY-MM' 영업일 수 + 표준시간 (예: {days:19, hours:152})

POST   /api/business-days/holidays
       → 회사 휴무일 추가 (예: 창립기념일)
       Body: { date, day_type, holiday_name, note }

PUT    /api/business-days/:date
       → 특정 일자 영업일/휴일 토글

DELETE /api/business-days/holidays/:date
       → 회사 휴무 해제

POST   /api/business-days/import-public-holidays?year=YYYY
       → 한국 법정공휴일 일괄 시드 (관리자)
```

### 5.2 KB API
```
GET    /api/kb/categories
GET    /api/kb/sop?categoryId=&search=&page=
GET    /api/kb/sop/:id
POST   /api/kb/sop
PUT    /api/kb/sop/:id
GET    /api/kb/sop/:id/versions
POST   /api/kb/sop/:id/helpful

GET    /api/kb/issues?search=&category=&severity=
GET    /api/kb/issues/:id
POST   /api/kb/issues
GET    /api/kb/issues/:id/similar

GET    /api/kb/handovers
POST   /api/kb/handovers
PUT    /api/kb/handovers/:id/items/:itemId

GET    /api/kb/onboarding/:userId
PUT    /api/kb/onboarding/milestones/:id
```

모든 API는 기존 인증 미들웨어 + 권한 체크 통과해야 함.

---

## 6. 권한 매트릭스

| 기능 | 팀장 | 실장 | 책임자 | 담당자 |
|---|---|---|---|---|
| 팀 대시보드 조회 | ✅ | ✅ | ❌ | ❌ |
| 개인 대시보드(본인) | ✅ | ✅ | ✅ | ✅ |
| 다른 사람 부하율 조회 | ✅ | ✅(읽기) | ❌ | ❌ |
| Excel 내보내기 | ✅ | ❌ | ❌ | ❌ |
| 영업일/휴무 관리 | ✅ | ❌ | ❌ | ❌ |
| 영업일 조회 | ✅ | ✅ | ✅ | ✅ |
| SOP 작성/수정 | ✅ | ✅ | ✅ | ❌ |
| SOP 읽기 | ✅ | ✅ | ✅ | ✅ |
| 이슈 사례 등록 | ✅ | ✅ | ✅ | ✅ |
| 이슈 사례 삭제 | ✅ | ❌ | ❌ | ❌ |
| 인수인계 생성 | ✅ | ✅ | ❌ | ❌ |
| 온보딩 멘토 코멘트 | (멘토 지정자만) | | | |

기존 RBAC 구조에 맞춰 조정. 0단계 분석 결과에 따라 역할명 매핑 변경.

---

## 7. 구현 단계 (Phase별 진행)

### Phase 0: 사전 분석 & 합의 (1단계 — 코드 수정 X)
- 위 1.1, 1.2 항목 분석 → 사용자 보고
- 기존 구조와 충돌 지점 식별
- 본 문서에서 조정이 필요한 부분 협의

### Phase 1: 데이터 모델 (모듈 A 기반)
- 신규/변경 테이블 마이그레이션 작성
- 시드 데이터:
  - 업무 유형 마스터: 결산/검증/보고서/회의/교육/기타
  - **영업일 마스터: 한국 법정공휴일 시드 (현재 연도 ± 2년 권장)**
    - 옵션 A: npm 패키지 (`holiday-kr`, `@hyunbinseo/holidays-kr` 등) 활용
    - 옵션 B: 공공데이터포털 API 연동 (정확하지만 인증키 필요)
    - 옵션 C: 하드코딩 시드 (가장 단순, 매년 갱신 필요)
    - → Claude Code가 환경에 맞는 옵션 추천 후 사용자 승인 받고 진행
  - 회사 지정 휴무 (창립기념일 등)는 사용자에게 직접 입력 받기
- 월별 영업일 캐시 자동 생성 (트리거 또는 배치)
- 기존 데이터가 있다면 마이그레이션 전략 (예: NULL 허용 후 점진 채우기)

### Phase 2: 모니터링 백엔드
- **영업일 계산 유틸 (최우선)**
  - `getBusinessDaysInMonth(yearMonth)` → 해당 월 영업일 수
  - `getStandardHoursForMonth(yearMonth)` → 해당 월 표준시간 (영업일 × 8)
  - `isBusinessDay(date)` → 단일 일자 판단
  - `getConsecutiveBusinessDays(from, n)` → 영업일 연속 카운트 (주말/공휴일 스킵)
- 부하율 계산 로직 (위 유틸 기반)
  - **MM 환산은 반드시 해당 월 표준시간으로 나눌 것** (고정값 X)
  - 과중/유휴 연속 카운트는 영업일 기준
- API 5.1, 5.1.1 전체 구현
- 캐시 갱신 배치 (매일 자정 또는 입력 시 트리거)

### Phase 3: 모니터링 프론트엔드
- 팀 대시보드 페이지 + 히트맵 컴포넌트
- 개인 대시보드 페이지
- 알림 UI (벨 아이콘 + 드롭다운)

### Phase 4: KB 데이터 모델 + 백엔드
- 테이블 생성
- API 5.2 구현
- 검색 기능 (DB 종류에 따라 LIKE 또는 풀텍스트)

### Phase 5: KB 프론트엔드
- SOP 트리 + 마크다운 에디터 + 검색
- 이슈 사례집 (CRUD)
- 인수인계 / 온보딩 (이건 시간 되면)

### Phase 6: 마무리
- 권한 검증 테스트
- 감사 로그 연동 확인
- 알림 채널 (이메일) 연동
- README / 운영 매뉴얼 업데이트

각 Phase 완료 시점마다 **Git 커밋 + 푸시** 필수.

---

## 8. 비기능 요구사항

### 8.1 성능
- 팀 히트맵 조회 (30일 × 20명): **1초 이내** 응답
- 부하율은 미리 계산해서 캐시 테이블에 저장 (실시간 계산 X)
- SOP 검색: 2초 이내

### 8.2 보안
- 모든 API는 인증 미들웨어 통과
- 권한별 접근 제어 (5.6의 매트릭스)
- 감사 로그: 조회/수정/삭제 모두 기록
- ⚠️ **로그인 페이지의 테스트 계정 정보 노출 제거** (운영 배포 전 필수)

### 8.3 코드 품질
- 비즈니스 로직(부하율 계산 등)은 별도 모듈로 분리 → 단위 테스트 가능
- 매직넘버는 모두 환경변수 또는 config로
- 한글 주석 OK (계리 도메인 용어는 한글이 명확함)

---

## 9. Claude Code 첫 실행 명령

이 문서를 첨부한 뒤 다음과 같이 지시:

```
첨부한 REQUIREMENTS_workload_monitoring.md 문서를 정독해줘.

먼저 Phase 0 (사전 분석)만 수행하고 결과를 보고해줘.
- 현재 백엔드/프론트엔드 스택
- DB 종류 및 ORM
- 기존 users / tasks / 권한 관련 테이블 스키마
- 모듈 A/B와 충돌하거나 재사용 가능한 기존 기능

코드 수정은 절대 하지 말고, 분석 보고서만 만들어줘.
보고 후 내가 'Phase 1 진행'이라고 말하면 그때부터 코드 작성 시작.
```

이렇게 단계별로 끊어서 진행하면 안전하게 만들 수 있음.

---

## 10. 검토자 노트 (사용자가 Claude Code 작업 중 체크할 것)

- [ ] Phase 0 보고서를 받으면 **DB 스키마가 본인이 알고 있는 것과 일치하는지** 확인
- [ ] 부하율 임계치(120% / 70%)가 우리 팀 현실에 맞는지 검토
- [ ] 업무 유형 시드 값이 실제 결산팀 업무와 맞는지 (직접 수정 권장)
- [ ] **한국 공휴일 시드 방법 결정** (npm 패키지 vs 공공데이터 API vs 하드코딩)
- [ ] **회사 지정 휴무일 입력** (창립기념일, 임시휴무 등) — Phase 1 종료 시점
- [ ] 알림 채널: 사내 메일 SMTP 설정 정보 필요
- [ ] 운영 배포 전 로그인 페이지 테스트 계정 노출 반드시 제거

---

**문서 끝.**
