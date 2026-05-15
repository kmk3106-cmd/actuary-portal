# 데이터 동기화 규칙 (DATA_SYNC_RULES)

> 계리결산팀 운영관리포탈의 **데이터 입력 → 저장 → 삭제 → 모니터링** 흐름이 깨지지 않게 하는 규칙. 신규 기능 추가/버그 수정 시 반드시 이 문서의 규칙을 지킬 것.

---

## 1. 핵심 테이블 관계도

```
[입력층]                            [정규화층]                    [집계/모니터링층]
┌─────────────────────┐              ┌─────────────────────┐     ┌──────────────────────┐
│ work_tasks          │              │ daily_work_entries  │     │ workload_daily_cache │
│ (월별 1건/멤버)      │  ──sync──▶  │ (시간대 단위 N건)    │ ─▶  │ (member,date 집계)    │
│                     │              │                      │     │                       │
│ - settlement_done   │              │ - time_entries: [   │     │ - total_minutes       │
│ - settlement_dates  │              │     {date,start,    │     │ - load_pct            │
│ - settlement_times  │              │      end,minutes}   │     │ - status              │
│ - settlement_       │              │   ]                  │     └──────────────────────┘
│   deadline_days     │              │ - source:            │              │
│ - other_tasks: [   │              │   'settlement' |     │              │
│     {cat,desc,...} │              │   'manual'           │              ▼
│   ]                  │              │ - settle_item_id    │     ┌──────────────────────┐
│ - score_*           │              │   (settlement only) │     │ /api/workload/*      │
└─────────────────────┘              └─────────────────────┘     │ - team / user        │
        │                                                          │ - summary / alerts   │
        │ pushDeadlineToPerf                                       │ - by-type            │
        ▼                                                          └──────────────────────┘
┌─────────────────────┐                                                    │
│ performance_records │                                                    ▼
│ - score_deadline    │                                              [화면 모니터링]
│ - score_*           │                                              workload-team / -me
└─────────────────────┘                                              performance.html
```

### 입력 화면 → 저장 대상 매핑

| 화면 | 입력 → 저장 위치 | 동기화 대상 |
|------|----------------|------------|
| `settlement.html` (결산 체크리스트) | `work_tasks` (월별) | → `daily_work_entries` (settle item별 N건) → `workload_daily_cache` |
| `work-personal.html` (결산외 업무) | `work_tasks.other_tasks` | → `daily_work_entries` (manual, N건) → `workload_daily_cache` |
| `workload-me.html` (일별 직접 입력) | `daily_work_entries` (직접) | → `workload_daily_cache` |
| `performance.html` (성과 기록) | `performance_records` | — |

---

## 2. 동기화 핵심 원칙

### 원칙 1: 입력층(work_tasks)이 진실의 원천 (Source of Truth)

- 사용자가 결산 체크리스트나 결산외 업무 입력 화면에서 보는 데이터는 **`work_tasks`** 가 정답.
- `daily_work_entries`는 `work_tasks`로부터 파생된 사본. **삭제/수정 시 자동 동기화 필수.**

### 원칙 2: 저장은 "전체 교체" (Replace, Not Append)

- 사용자가 화면에서 행을 추가/수정/삭제한 뒤 **저장** 버튼을 누르면:
  - `work_tasks` 의 해당 필드는 화면 상태로 **덮어쓰기**
  - `daily_work_entries` 의 (멤버 + 해당 월 + source 일치) 행은 **전부 삭제 후 새로 생성**
- ❌ "기존 행 그대로 두고 새 행 추가" 같은 append 방식 사용 금지 → **중복 누적 버그**의 원인
- ✅ Replace 방식으로 idempotent 보장

### 원칙 3: 체크 해제/행 삭제 = 데이터 삭제

- UI에서 항목을 체크 해제하거나 행을 삭제하는 행위는 "감춤"이 아니라 **삭제**다.
- 메모리 상태(체크박스, 배열)만 바꾸지 말고, **저장 시점에 DB도 정리**.
- 체크 해제된 항목에 잔존하는 `dates/times/deadline_days` 등의 키를 **sanitize 단계**에서 모두 제거 후 PUT.

### 원칙 4: 자동 캐시 재계산은 서버가 책임

- `daily_work_entries` POST/PUT/PATCH/DELETE 시 서버 훅(`refreshDailyCacheFor`)이 자동으로 `workload_daily_cache` 재계산.
- 클라이언트가 cache를 직접 건드리지 않음 (옛 행이 있던 일자만 재계산되므로 정확).

---

## 3. 발견된 버그 패턴 & 해결

### 버그 패턴 A: 체크 해제 후 deadline_days 잔존
**증상**: 김채린 0건인데 보험료분해 마감(-1) 점수 70점 표시  
**원인**: `chkDeadlineDaysMap`에 키가 남아 saveChecklist가 그대로 PUT  
**해결**:
- `toggleChkTask(id, false)` 시 관련 맵의 키 즉시 delete
- `saveChecklist` 시작부에 **sanitize 함수** 적용:
  ```js
  const sanitize = (obj) => {
    const out = {};
    for (const k in obj) if (chkDone.has(k)) out[k] = obj[k];
    return out;
  };
  chkDates = sanitize(chkDates);
  // ... 나머지 5개 맵
  ```
- `resetChecklist` 시 모든 맵 비우기 + 해당 멤버의 `daily_work_entries` (source='settlement') 일괄 삭제

### 버그 패턴 B: manual daily_work_entries 중복 누적
**증상**: 한인석 5월 14310분(238h) — 같은 작업 6건 중복  
**원인**: `saveWorkTask` 가 매번 POST만 하고 기존 manual 행 안 지움  
**해결**:
- 저장 step 4-pre: **기존 manual 행 일괄 삭제** → 새로 POST
  ```js
  const existing = (rows).filter(e =>
    e.member_name === currentMember &&
    e.source === 'manual' &&
    (e.end_date || '').startsWith(ymPrefix)
  );
  await Promise.all(existing.map(e =>
    fetch(`/tables/daily_work_entries/${encodeURIComponent(e.id)}`, { method: 'DELETE' })
  ));
  // ... 그 다음 새로 POST
  ```

### 버그 패턴 C: 결산 체크 해제 후 daily_work_entries 잔존
**증상**: settlement에서 체크 해제했는데 팀모니터링에 계속 조회됨  
**원인**: `syncSettleToDwe` 가 체크된 항목만 upsert, 해제된 항목의 기존 행 삭제 안 함  
**해결**:
- syncSettleToDwe 시작부에서 **(멤버, 해당 월, source='settlement')의 기존 행 로드 → 현재 체크된 settle_id 집합에 없는 것 삭제** → 그 다음 upsert
- `resetChecklist`도 `deleteAllSettleDweForMember()` 호출하여 일괄 삭제

### 버그 패턴 D: 마이그레이션 잔존
**증상**: 4월 work_tasks 없는데 daily_work_entries만 잔존  
**원인**: Phase 7-1 마이그레이션 시점의 자동 변환 결과가 후속 삭제와 동기화 안 됨  
**해결**: 주기적 일관성 검사 + 보고. 사용자 의도가 명확하지 않은 잔존은 **확인 후 삭제**.

### 버그 패턴 E: 마이그레이션이 만든 source가 동기화 필터에서 누락 ★★★
**증상**: 사용자가 결산 체크 해제 + 저장했는데도 팀모니터링에 계속 표시됨 (5명 분량 잔존)  
**원인**:
- Phase 7-1 마이그레이션이 자동 변환한 행 → `source = 'settlement_auto'`
- 사용자가 직접 저장한 행 → `source = 'settlement'`
- 정리 함수(`syncSettleToDwe`, `deleteAllSettleDweForMember`)는 `source === 'settlement'` 만 필터링
- → 마이그레이션 잔존은 어떤 UI 액션으로도 안 지워짐 (영구 좀비)

**해결**:
- 필터를 `(source === 'settlement' || source === 'settlement_auto')` 로 확장
- 한 번의 일괄 정리로 기존 잔존 즉시 제거

**일반 원칙 (★ 마이그레이션 시 반드시 ★)**:
- **새 source/category/type 값을 만들면, 그것을 참조하는 모든 동기화/정리/필터 함수에서 함께 처리**
- 마이그레이션이 생성한 데이터는 **사용자가 만든 데이터와 동등하게 취급**되어야 함
- "마이그레이션 라벨(is_estimated 같은)"은 표시용일 뿐, 동기화 책임은 똑같이 짊어진다

### 버그 패턴 F: push*ToPerf 의 null 가드로 옛 점수 잔존 ★★
**증상** (2026-05-11): 성과관리표·개인평가카드에 옛 점수 잔존
- 이상현 5월 score_deadline=12, 한인석 45, 오정택 4, 강세진 4, 이동민 90, 김채린 70 등 6명
- 마혜원 5월 score_directive/csm/meeting=100 일률 잔존
- 분기 record(`pr_2026q2_XX`) 13건도 score_deadline=80, score_csm=50 잔존
- 사용자가 결산 체크 해제·work_task 정리 후에도 옛 점수 그대로

**원인** (`settlement.html` `pushDeadlineToPerf`):
```js
if (Object.keys(chkDeadlineDaysMap).length > 0) pushDeadlineToPerf();  // ← 비면 호출 안 함
async function pushDeadlineToPerf() {
  const score = calcDeadlineAvgScore();
  if (score == null) return;  // ← 또 막힘. 옛 점수 영구 잔존
  ...
}
```
- raw 데이터가 비어 score가 null이 되어도 **명시적으로 null PATCH 안 함**
- 호출 조건도 "맵에 키가 있을 때만" — 모든 키 정리하면 호출 자체가 스킵

**해결**:
- 호출 조건 제거: `pushDeadlineToPerf()` 항상 호출
- 함수 내 가드 제거: `score == null` 인 경우에도 명시적으로 `score_deadline: null` 로 PATCH
- 기존 PUT(전체 record 덮어쓰기) → PATCH(해당 필드만)로 변경. 다른 필드(정성 KPI 등) 보존.
- 기존 record가 없고 score도 null이면 빈 record 생성은 안 함 (의미 없음)

**일반 원칙 (push*ToPerf 패턴 전체)**:
- raw 데이터 → score 변환 결과가 null이어도 **명시적 null PATCH** 필수
- "raw가 비었으면 호출 스킵" 패턴 금지 → 옛 점수 영구 잔존의 원인
- 동일 패턴이 `pushQuantToPerf` (work-personal.html line 531), `pushKpiToPerf` (work-personal.html line 640) 에도 잠재할 수 있으니 신규 점수 동기화 함수 작성 시 같은 원칙 적용

### 버그 F 보완 — work-personal 정량 raw 자동 동기화 (2026-05-11 추가)
**증상**: 마혜원 5월 work_task의 raw_directive=None인데 performance_records.raw_directive=1
("반영" 누른 후 사용자가 work-personal에서 raw 값을 다시 비웠지만 performance_records 미갱신)
- raw_directive=1 / raw_csm_amount=1900 / raw_meeting_count=1 잔존
- score_directive/csm/meeting = 100/100/100 (옛 값) 잔존
- basic_score=30, final_score=36, grade=D 도 옛 값 잔존

**원인**: `work-personal.saveQuantitative()` 가 **work_tasks 만 PUT/POST 하고 performance_records 동기화 안 함**.
`pushQuantToPerf()` 는 "반영" 버튼 클릭 시에만 호출되므로 raw를 다시 비우고 저장만 하면 performance_records는 옛 값 그대로.

**해결** (work-personal.html):
```js
async function saveQuantitative() {
  // ... work_tasks 저장 ...
  await syncQuantRawToPerf();   // ← 자동 동기화 추가
  // ...
}

async function syncQuantRawToPerf() {
  // raw_* + score_directive/csm/meeting 자동 PATCH (raw가 null이면 score도 null)
  // 가드 없음: 사용자 클릭 없이 자동 실행
  // record 없으면 생성 안 함 ("반영" 시점에 pushQuantToPerf가 처리)
}
```
- `pushQuantToPerf` ("반영" 버튼) 는 그대로. basic_score/final_score/grade 등 종합 점수까지 산출하는 책임.
- `syncQuantRawToPerf` (자동) 는 raw + 정량 score 3개만 동기화. 가벼운 일관성 유지 책임.
- score_deadline은 settlement의 책임이므로 syncQuantRawToPerf에서 건드리지 않음.

**일반 원칙 (저장 함수의 동기화 책임)**:
- 어떤 입력 화면의 "저장" 액션이 SoT(work_tasks)를 갱신하면, **그 변경이 영향 주는 모든 파생 테이블도 같은 트랜잭션에 동기화** 해야 함.
- "반영" 같은 별도 액션을 추가로 누르게 하는 UX는 사용자 실수로 잔존 발생 → 자동화 필수.

### 버그 패턴 G: push*ToPerf 류가 score만 PATCH 하고 basic_score/final_score 재계산 누락 (2026-05-12)
**증상**: 한인석 5월 score_kpi1=80 (KPI1 weight 20% → basic 기댓값 16) 인데
performance_records.basic_score=34, final_score=37.4 잔존. 다른 점수(directive/csm/deadline/meeting)는
모두 null. KPI score만 갱신된 시점의 옛 basic/final 가 그대로 남음.
- 동일 시점 이성원 5월: score_deadline=0 입력했지만 basic_score=null 인 상태(0으로 재계산 안 됨).

**원인**: `pushKpiToPerf` (work-personal.html L675), `syncQuantRawToPerf` (work-personal.html),
`pushDeadlineToPerf` (settlement.html) 모두 score_* 필드만 PATCH/PUT 하고
**basic_score / final_score / grade** 는 재계산하지 않음.
- 사용자가 performance.html 모달을 열고 수동 저장해야만 autoCalcScores 가 돌면서 일치.
- 그 사이엔 모니터링 화면(개인평가카드, 분기 집계 등)에서 옛 점수가 표시됨.

**해결**:
- 공유 가중합 헬퍼(예: `recalcBasicFinal(record)`) 한 곳에 두고 모든 push*ToPerf 끝부분에서 호출.
  - basic_score = Σ(score_code × weight_pct/100)  (현재 record 의 score_* 만 합산)
  - final_score = basic_score × (1 + bonus_rate)
  - grade = gradeFromScore(final_score)
- 점수가 모두 null 이면 basic/final/grade 도 null 로 명시적 세팅 (잔존 방지)
- 가중치는 `kpi_definitions` API 에서 동적 로드 (하드코딩 금지 — 규칙 11 SSOT)

**검증 스크립트**: `tmp/_check_04_perf_orphans.py` 의 F/G 케이스 (basic 가중합 불일치 / final≠basic×(1+rate))

**일반 원칙**:
- 파생 점수(basic/final/grade)는 원천 점수(score_*)에서 항상 도출 가능해야 함.
- 원천 점수를 PATCH 하면서 파생 점수를 PATCH 하지 않으면, 다른 화면에서 옛 파생 점수가 무한히 살아남는다.
- 새 점수 입력 경로 추가 시 반드시 "원천 → 파생" 전체 재계산을 트랜잭션에 포함시킬 것.

### 버그 패턴 H: 멀티데이 time_entries 가 사용자 입력 시간을 무시하고 강제 변환 (2026-05-12)
**증상**: 이성원 `5/11 08:00 ~ 5/12 17:00` 입력했는데 팀모니터링/daily_work_entries에서
- 5/11: **08:00~18:00** (10시간) ← 첫날 끝이 강제로 18:00
- 5/12: **09:00~17:00** (8시간)  ← 마지막날 시작이 강제로 09:00
로 비대칭 변환되어 표시. 사용자 입력 시간과 일치하지 않음.

**원인** (`server/lib/timeentry.js` 옛 `buildEntriesFromRange`):
```js
// 첫날: startTime ~ '18:00' (강제 18:00)
// 중간일: '09:00' ~ '18:00'
// 마지막날: '09:00' ~ endTime (강제 09:00)
```
"연속된 한 블록(start 시각부터 end 시각까지 쭉)" 모델로 해석한 옛 정책.
하지만 실제 사용자 의도는 **"매일 같은 시간(start~end)에 일하는 일정"** 인 경우가 훨씬 일반적.

**해결**:
- 멀티데이도 **각 일자에 사용자 입력 startTime~endTime 동일 적용**.
- 점심(12:00~13:00) 자동 차감은 유지 (8h 표준 정책, 패턴 H 별개).
- 첫날/마지막날 시간 강제 변환 금지 — **사용자가 입력한 값을 그대로 신뢰**.

```js
// 새 정책 (개정 후)
while (cur <= end) {
  out.push({ date: toIso(cur), start: startTime, end: endTime,
             minutes: netMinutesInRange(sM, eM) });
  cur.setDate(cur.getDate() + 1);
}
```

**일반 원칙 (시간/날짜 입력 처리)**:
- **사용자 입력 시간/날짜는 변형하지 않는다.** 시작·종료시간을 임의로 09:00/18:00 같은 기본값으로 대체 금지.
- 자동 보정이 필요한 항목은 **분(minutes)** 같은 파생값만. 그것도 명확한 정책(점심 차감 등) 하에서만.
- 멀티데이 분산 시 "한 블록 연속" vs "매일 동일 시간" 두 모델 중 **사용자 직관에 가까운 후자**를 택한다.

### 시간 정합성 정책 요약 (2026-05-12 합의)

| 항목 | 정책 |
|------|------|
| 표준 근무시간 | 09:00~18:00 (점심 12:00~13:00 1h 제외 = 8h/day) |
| 점심 차감 | **`netMinutesInRange()`** 가 자동 처리. 클라이언트가 보낸 minutes 신뢰 X — 항상 서버 재계산 |
| 멀티데이 분산 | 각 일자에 동일 `start_time~end_time` 적용. 첫/마지막날 강제 변환 금지 |
| start_time / end_time | 직원이 입력한 값 그대로 저장. 시스템이 09:00/18:00 등으로 덮어쓰지 않음 |
| total_minutes / duration_minutes | `summarize(time_entries)` 결과 (점심 차감 반영된 합) |

### 버그 패턴 J: 업무유형별 분포(by-type) 가 task_label 까지 분산 (2026-05-12)
**증상**: 팀 업무량 모니터링 도넛 차트 "업무유형별 분포" 가 19개 이상의 개별 업무명으로
잘게 쪼개져 표시. 사용자 의도는 대구분(프로젝트/데이터 분석/외부감사 등) 단위.

**원인** (`server/lib/workload.js` 옛 `computeByType`):
- `task_category_id` 가 `null` 인 manual 행에서 fallback이 `e.task_label` (업무명) 로 떨어짐
- work-personal 입력은 카테고리(`t.cat`) 를 화면에서만 보유, daily_work_entries 에는 안 저장
- → 카테고리 정보 손실 → 도넛이 업무명 단위로 분산

**해결**:
- `work-personal.html` daily_work_entries POST 에 **`task_category: t.cat`** (대구분 라벨) 추가
- `computeByType` 우선순위: `task_category_id`(FK) > `task_category`(라벨) > `source=settlement* → '결산 업무'` > `'기타'`
- 개별 `task_label` 은 도넛에서 절대 사용하지 않음 (legend·tooltip은 가능, 그룹키 X)
- 기존 데이터: `tmp/_check_09_backfill_category.py` 로 work_tasks.other_tasks 와 매칭해 백필

**일반 원칙 (집계 단위 보존)**:
- 입력화면이 가진 분류 정보(카테고리/태그/대구분)는 **저장 시점에 daily_work_entries 까지 함께 전달** 필수
- 집계/도넛/막대 같은 차트는 **항상 대구분 단위만** 사용. 개별 업무명 단위 그룹화 금지
- 새 입력 화면 추가 시 daily_work_entries POST 본문에 분류 라벨 빠지지 않았는지 점검

### 버그 패턴 I: 로컬 메모리 상태와 서버 캐시 분리 후 한쪽만 갱신 → 화면 불일치 (2026-05-12)
**증상**: 결산캘린더에서 본인 체크박스를 켜거나 끄거나 "초기화"를 눌러도
달력 셀의 마감 칩 색상(✓ / 셀 초록 배경)이 즉시 변하지 않음. 화면 새로고침 후에야 반영.

**원인** (`settlement.html` `buildChklChipMap` + `isSettleTaskCompleted`):
- 캘린더에 **모든 멤버의 완료 항목**을 표시하기 위해 `allMembersWorkTasks` (서버 work_tasks 캐시) 를 사용
- 그런데 토글/초기화 등 본인 액션은 로컬 변수(`chkDone`, `chkDates`)만 갱신
- 캘린더 빌드 함수는 `allMembersWorkTasks` (서버 상태) 만 읽음 → 본인의 로컬 변경이 화면에 안 보임

**해결**:
- `buildChklChipMap` / `isSettleTaskCompleted` 가 본인(`chkMember`)에 대해서는 **로컬 `chkDone`/`chkDates`를 사용**, 그 외 멤버는 서버 캐시 사용
- 본인 record 가 서버에 없는 경우(신규)도 로컬 상태만으로 렌더
- `toggleChkTask(true)` 도 항상 `buildChklChipMap + renderCalendar + showDayPanel` 호출 (체크 즉시 마감 칩 ✓ 표시)
- `resetChecklist` / `cancelChecklist` 는 이미 호출하므로 그대로

**일반 원칙 (로컬-캐시 혼합 시)**:
- **본인 상태(편집 중)는 로컬이 SoT, 타인 상태는 서버 캐시가 SoT** — 한 함수에서 두 소스를 처리할 때 반드시 출처를 구분
- 로컬 변경을 발생시키는 모든 액션(토글/취소/초기화/저장)이 **화면 재빌드 함수를 호출**하도록 점검
- 단지 "저장 시 서버 fetch + 재렌더" 만 해두면 안 됨 — 저장 전 상태 변화도 화면에 즉시 반영되어야 사용자 신뢰

---

## 4. 신규 기능 추가/수정 체크리스트

신규 기능 PR/커밋 전 반드시 점검:

- [ ] **새로 추가/수정한 데이터가 daily_work_entries에 영향 주는가?**
  - YES → 저장 함수에 "전체 교체" 패턴 적용 (관련 기존 행 삭제 → 새로 POST)
- [ ] **메모리 상태(배열/Set)에서만 삭제/취소하는 액션이 있는가?**
  - YES → 다음 "저장" 시점에 DB도 동기화되는지 확인 (sanitize 또는 replace)
  - 또한 해당 액션 직후 **화면 재빌드(buildXxx + renderXxx)** 가 호출되는지 점검 (버그 패턴 I 참조)
- [ ] **로컬 상태 / 서버 캐시 혼합 화면**(예: 본인 편집 + 타인 조회) 의 렌더 함수가 본인은 로컬 / 타인은 캐시를 사용하는가? (버그 패턴 I 참조)
- [ ] **`source` 필드 일관성**: settlement / manual / settlement_auto / 외 새 source 만들 때 동기화·삭제·필터 함수 **모두** 그 source 포함하도록 확장 (버그 패턴 E 참조)
- [ ] **`workload_daily_cache`** 는 절대 클라이언트에서 직접 쓰지 말 것. 서버 훅이 처리.
- [ ] **잔존 키/행 일관성 검사 스크립트** 한 번 돌려보기 (§5 참조)

---

## 5. 잔존 데이터 점검 스크립트 (수동 운영)

운영 중 의심되면 다음을 실행해 잔존 데이터를 식별:

```bash
# work_tasks 잔존 키 (settlement_done에 없는데 dates/times/deadline_days 잔존)
curl -s "http://localhost:8888/tables/work_tasks?limit=100" \
  | python -c "
import json,sys
d = json.load(sys.stdin)
for r in d['rows']:
  done = set(r.get('settlement_done') or [])
  for fld in ['settlement_dates','settlement_times','settlement_deadline_days',
              'settlement_start_dates','settlement_start_times','settlement_end_times']:
    m = r.get(fld) or {}
    orphan = [k for k in m if k not in done]
    if orphan:
      print(f\"{r['member_name']} {r['year']}-{r['month']} {fld}: {orphan}\")"

# manual daily_work_entries 잔존 (work_tasks.other_tasks에 매치 안 됨)
# → 사용자가 화면에서 지웠는데 DB 잔존
# 위 정도 패턴으로 비교 가능 (자세한 스크립트 별도 작성 권장)
```

---

## 6. 향후 검토 항목

- [ ] DB 변경 시 자동 검증을 위한 통합 헬스체크 API (`/api/admin/health-check`) 도입
- [ ] 마이그레이션 도구 페이지에 "잔존 데이터 검출 / 일괄 정리" 버튼 추가
- [ ] 단위 테스트: saveChecklist / saveWorkTask 의 idempotency 보장 테스트

---

## 7. ★ 마이그레이션 작업 필수 체크리스트 ★

데이터 모델 변경(AS-IS → TO-BE)으로 인한 마이그레이션을 수행할 때 **반드시** 다음을 점검한다.

### 7.1 마이그레이션 생성 데이터의 생애주기

마이그레이션은 단순히 "옛 데이터를 새 형식으로 변환"이 아니라 **새 데이터의 영구 관리책임**까지 포함한다.

```
[마이그레이션 시점]
  옛 데이터 → 변환 → 새 데이터 (source='xxx_auto', is_estimated=true)
                                    │
                                    ▼
[이후 사용자 액션]
  - 사용자가 옛 위치(work_tasks)에서 데이터 삭제/수정
  - → 마이그레이션이 만든 daily_work_entries 행도 함께 정리되어야 함
  - 사용자가 새 UI에서 직접 보정/삭제
  - → 동일 source의 다른 행과 똑같이 취급
```

### 7.2 마이그레이션 시 반드시 확인할 항목

마이그레이션 코드를 작성/수정할 때:

- [ ] **새 source/type 명명**: `xxx_auto` / `xxx_imported` 등 마이그레이션 출처를 식별할 source 부여 (사용자 입력과 구분)
- [ ] **`is_estimated` 또는 동등한 플래그**: 사용자에게 "추정/마이그레이션 라벨" 표시 가능하게
- [ ] **멱등성 마커**: `db._meta.migrated_xxx_v1` 같은 마커로 중복 실행 방지
- [ ] **동기화 함수 전수 검토**: 다음 위치들의 `source` 필터에 새 값 포함되었는지
  - `settlement.html` — syncSettleToDwe / deleteAllSettleDweForMember
  - `work-personal.html` — saveWorkTask 의 step 4-pre (manual 정리)
  - `workload-me.html` — 일별 입력 폼의 동기화 (있으면)
  - `server/lib/workload.js` — computeDayLoad 등 집계 (source 무관하게 합산해도 OK)
  - 향후 추가될 모든 정리 함수
- [ ] **삭제 흐름 검증**:
  - 사용자가 source='xxx_auto' 행을 삭제할 수 있는가?
  - 또는 옛 위치(work_tasks 등) 삭제 시 마이그레이션 행이 자동 정리되는가?
  - 어느 경로로도 정리되지 않는 "좀비" 데이터가 생기지 않는가?
- [ ] **잔존 검출 스크립트 실행**: §5 스크립트로 마이그레이션 직후/직전 상태 비교
- [ ] **DATA_SYNC_RULES.md 갱신**: 새 source/type을 §1 관계도 + §3 버그 패턴(예방) 에 명시

### 7.3 마이그레이션 검증 시나리오

```
1. 마이그레이션 실행 → 새 데이터 N건 생성
2. 사용자 시점: UI 새로고침 → 화면에 N건 정상 표시
3. 옛 위치에서 1건 삭제 + 저장 → 새 위치에서도 1건 사라짐 ✓
4. 새 위치에서 1건 수동 보정 → 옛 위치엔 영향 없음 (단방향) 또는 양방향 동기화 명시
5. 모든 데이터 삭제 → 새 위치도 0건 ✓
6. 잔존 검사 스크립트 → 0건 확인 ✓
```

위 단계 중 하나라도 실패하면 마이그레이션 미완성으로 간주한다.

### 7.4 회고 (Phase 7-1 마이그레이션의 누락)

Phase 7-1에서 source='settlement_auto'로 7건 생성. 하지만 syncSettleToDwe 필터에 source 누락:
- 결과: 사용자가 결산 캘린더에서 체크 해제 + 저장해도 잔존 (영구 좀비)
- 1주 후 사용자 다수 잔존 신고 → 5명 7건 일괄 정리 + 필터 수정
- **재발 방지**: 위 §7.2 체크리스트가 그때 있었다면 즉시 캐치 가능했을 사안

---

**문서 갱신 정책**: 새 버그 패턴 발견 시 §3에 추가. 데이터 모델 변경 시 §1 다이어그램 갱신. **새 source/type 도입 시 §7.2 체크리스트 통과 후 머지**.

---

## 8. Phase 8 — 게이미피케이션 + 휴가 시스템

### 8.1 신규 테이블

| 테이블 | 역할 | 동기화 트리거 |
|--------|------|---------------|
| `vacations` | 휴가 사용 이력 (개별 row) | 등록·수정·삭제 시 `vacation_quotas.used/remaining` 자동 재계산 |
| `vacation_quotas` | 연도/사용자별 한도 (annual_total/used/remaining) | 서버에서만 갱신, 클라이언트 직접 수정 금지 |
| `engagement_points` | 포인트 적립 ledger | 멱등키 `idempotency_key = actionType + ':' + actionRef`로 중복 방지 |
| `point_rules` | 적립 룰 SSOT (action_type / points / is_active) | settings 페이지에서 편집 → 다음 적립부터 즉시 반영 |
| `prize_rules` | 분기 시상 룰 (rank / prize_amount / label) | settings에서 편집 |
| `prize_history` | 분기별 TOP3 확정 기록 | `/api/prizes/finalize` 멱등 INSERT |

### 8.2 적립 훅 위치 (server.js handleTablesRequest)

| 트리거 | action_type | 멱등 키 | 비고 |
|--------|-------------|---------|------|
| POST `/tables/daily_work_entries` | `work_entry` | entry.id | 5pt/건 |
| POST `/tables/kb_issues` | `issue_register` | issue.id | 20pt/건 |
| POST `/tables/kb_documents` | `sop_create` | doc.id | 30pt/건 |
| PATCH `/tables/work_tasks` (KPI 필드 신규 채움) | `kpi_entry` | quarter + member | **분기당 1회** (`awardPointsOncePerQuarter`) |
| 결산 체크리스트 완료 | `settlement_check` | settle_item.id + month | 클라이언트가 별도 호출 (UI 시 추가 예정) |

### 8.3 휴가 → 업무 모니터링 연동 (분모 보정)

`server/lib/workload.js` `computeMonthlyForUser`:
- 입력: 그 월에 겹치는 `vacations.status='approved'` 행 일수 합산
- 영업일 차감: `effective_business_days = business_days - vacation_days`
- `standard_hours = effective_business_days × 8h` → `load_pct` 분모 축소
- 결과: 휴가일은 부하율 분모에서 빠지므로 같은 업무량이면 휴가자의 부하율이 상승 (정확)
- **휴가는 별도 테이블 유지** — `daily_work_entries`에 자동 row 생성 X (잔존 좀비 방지, §7.4 교훈 적용)

### 8.4 SSOT 원칙

- **point_rules** 단일 SSOT: 적립 점수 하드코딩 금지. `server/lib/points.js`의 `DEFAULT_RULES`는 시드 전용. 룰 변경은 `/tables/point_rules` PATCH로만.
- **prize_rules**: 1/2/3등 상금 액수는 settings 페이지에서 편집 가능해야 함 (CLAUDE.md §11).
- 팀장(`role='team_leader'`)은 적립·랭킹 대상에서 자동 제외 (룰 변경 X).

### 8.5 위험 패턴 (예방)

- **취소된 휴가**: status를 'rejected' / 'cancelled'로 PATCH할 시 `syncVacationQuotaOnUpdate`가 used 자동 재계산. 단순 DELETE 시 `syncVacationQuotaOnDelete` 호출.
- **멤버명 변경**: `vacation_quotas`는 user_id 우선, fallback이 member_name. 이름 바뀌면 quotas는 옛 이름으로 남음 → 새 이름으로 quota 새로 생성됨 (이중 quota 발생 가능). 사용자 마스터 이름 변경 시 quotas 마이그레이션 필요.
- **분기 경계 적립**: `awardPoints`는 항상 `currentQuarter()` 기준. 분기 종료 직후 첫 적립부터 새 분기. `prize_history`는 직전 분기 수동 finalize 후 잠금.

### 8.6 포인트 적립 룰 정비 (2026-05-15)

#### settlement_check 정책 (안건 1 — B5)

| 항목 | 내용 |
|------|------|
| 트리거 | `work_tasks PATCH` 시 `settlement_done` 배열에 **새 키가 추가**될 때 |
| 적립 | 추가된 키 1개당 3pt (`point_rules.settlement_check` 기준) |
| 멱등 키 | `settlement_check:<work_task.id>:<done_key>` — 해제 후 재체크해도 1회 |
| 분기 캡 | 분기당 30건(90pt) 초과 시 추가 적립 스킵 |
| 회수 | 체크 해제(`settlement_done`에서 키 제거)시 해당 `idempotency_key` 행 즉시 DELETE |
| cascade | `work_tasks DELETE` 시 `settlement_check:<wtId>:*` 패턴 전체 회수 (`startsWith` 필터) |
| 팀장 | 팀장 본인 또는 팀장이 대리 체크 시 적립 X (기존 가드 동일 적용) |

**구현 위치**: `server/lib/points.js` `syncSettlementCheckPoints()` + `server/server.js` PATCH work_tasks 훅

#### work_entry 그룹 멱등 정책 (안건 2 — B8)

| 항목 | 내용 |
|------|------|
| 문제 | work-personal.html에서 동일 작업을 시간대로 쪼개 입력 → POST 건수만큼 중복 적립 |
| 판별 단위 | `(member_name × YYYY-MM × task_label × task_category)` 그룹 |
| 적립 룰 | 그룹당 1회만 5pt — 그룹 내 두 번째 이후 entry는 skip |
| 멱등 키 | `work_entry:<entry.id>` 유지 (entry 레벨 중복은 기존 방식) |
| 그룹 키 저장 | `engagement_points.group_key` 컬럼에 `member:YM:label:category` 기록 |
| 전체 교체 패턴 | DELETE cascade → 해당 그룹 ep 삭제 → 새 POST → 그룹 첫 entry가 다시 적립 획득 → 안정적 |
| 다른 작업 여러 개 | task_label/category 가 다르면 각각 정상 적립 (차단 X) |

**구현 위치**: `server/lib/points.js` `awardWorkEntryGrouped()` + `server/server.js` POST daily_work_entries 훅

#### recompute (`/api/points/recompute`) 반영

- `settlement_check`: work_tasks 스캔 → settlement_done 배열 키당 분기 캡 적용하여 재적립
- `work_entry`: tables 루프 후 group_key 기반 중복 제거 후처리 (groupSeen set)
- 두 변경 모두 strict 모드(`?strict=1`) 하에서 actor 미상 record skip 정책 동일 적용

마지막 갱신: 2026-05-15 — settlement_check 실현 + work_entry 그룹 멱등 §8.6

---

## 9. Phase 9 — 게이미피케이션 강화 (2026-05-15)

### 9.1 신규 게임 요소

| 요소 | action_type | 룰 | 멱등 키 | 비고 |
|------|------------|-----|---------|------|
| 연속 입력 보너스 | `streak_bonus` | 영업일 연속 work_entry 입력 시 streak일×0.5pt, 하루 최대 10pt | `streak_bonus:<member>:<date>` | 2일 연속부터 적립, is_active 토글 |
| 분기 미션 | `quarterly_mission` | 분기 내 KPI×1 + SOP×1 + 이슈×3 달성 시 30pt | `quarterly_mission:<quarter>:<member>` | 분기당 1회, is_active 토글 |
| 첫 SOP 보너스 | `first_sop` | 분기 첫 SOP 등록 시 +20pt | `first_sop:<quarter>:<member>` | sop_create 직후 tryAwardFirstBonus 호출 |
| 첫 이슈 보너스 | `first_issue` | 분기 첫 이슈 등록 시 +10pt | `first_issue:<quarter>:<member>` | issue_register 직후 tryAwardFirstBonus 호출 |

**설계 원칙**:
- 모든 신규 룰은 `point_rules` 테이블에 `is_active` 컬럼으로 존재 → settings 페이지에서 토글, 서버 재시작 없이 즉시 반영
- `DEFAULT_RULES` 에 추가 → `seedPointsConfig()` 가 기존 DB에 없으면 자동 INSERT

### 9.2 신규 보상 체계

| 보상 | type | 기준 | 선정 | prize_rules id |
|------|------|------|------|---------------|
| 참여상 | `participation` | 분기 ≥50pt 전원 | 자동 | `pz_participation` |
| 성장상 1~3위 | `growth` | 직전 분기 대비 점수 증가율 TOP3 | 자동 | `pz_growth_1~3` |
| SOP MVP | `category_mvp` | 분기 sop_create 점수 1위 | 자동 | `pz_mvp_sop` |
| 이슈 MVP | `category_mvp` | 분기 issue_register 점수 1위 | 자동 | `pz_mvp_issue` |
| 결산 MVP | `category_mvp` | 분기 settlement_check 점수 1위 | 자동 | `pz_mvp_settlement` |

**신규 API**: `GET /api/points/awards?quarter=YYYY-Qn` — top3 + 참여상 + 성장상 + MVP 전체 반환

**`finalizeQuarter` 확장**: prize_history 에 award_type 컬럼 추가 (rank / participation / growth / category_mvp)

### 9.3 신규 Audit 카테고리 (6개)

| 카테고리 | 심각도 | 검출 | 자동수정 |
|----------|--------|------|---------|
| `points_rule_stale` | high | 룰 비활성화 이후 생성된 포인트 | O (삭제) |
| `points_quarter_boundary` | medium | 분기 경계 ±3일 5건 이상 집중 | X |
| `points_duplicate_user` | high | 동일 action_ref 를 복수 사용자에게 적립 | X |
| `points_inactive_user_ledger` | medium | 비활성 사용자 포인트 잔존 | X |
| `points_member_rename` | medium | 동일 user_id 에 복수 member_name 혼재 | X |
| `points_self_sop_ref` | medium | first_sop/first_issue 보너스 오발급 | O (삭제) |
