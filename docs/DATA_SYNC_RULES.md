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

---

## 4. 신규 기능 추가/수정 체크리스트

신규 기능 PR/커밋 전 반드시 점검:

- [ ] **새로 추가/수정한 데이터가 daily_work_entries에 영향 주는가?**
  - YES → 저장 함수에 "전체 교체" 패턴 적용 (관련 기존 행 삭제 → 새로 POST)
- [ ] **메모리 상태(배열/Set)에서만 삭제/취소하는 액션이 있는가?**
  - YES → 다음 "저장" 시점에 DB도 동기화되는지 확인 (sanitize 또는 replace)
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

마지막 갱신: 2026-05-11 — Phase 7 동기화 + 마이그레이션 규칙 §7 추가
