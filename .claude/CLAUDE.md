# 계리결산팀 포탈 — 작업 규칙

## 규칙 1: python -c 금지
멀티라인 로직은 절대 `python -c "..."` 로 실행하지 않는다.
반드시 `.py` 파일을 만들어서 `python file.py` 로 실행한다.

## 규칙 2: 하드코딩 금지
파일 경로, 날짜, 이름, DB 경로, 시트명, 매직 넘버를 코드 안에 박아 넣지 않는다.
- 경로 → argparse `--input` / `--out` 인자 또는 환경변수
- 날짜 → `--ym YYYYMM` 인자로 받아서 자동 계산
- 시트명 → `--sheet` 인자 또는 상수로 파일 상단에 정의
- 매직 넘버 → 이름 있는 상수로 파일 상단에 정의

## 규칙 3: 임시 점검 스크립트 위치
일회성 또는 디버깅용 스크립트는 `tmp/_check_NN_설명.py` 형식으로 저장한다.
(`NN` = 두 자리 숫자 시퀀스, 예: `tmp/_check_01_sheet_names.py`)

## 규칙 4: 재사용 스크립트 위치
반복 사용하거나 팀 공유가 필요한 스크립트는 `scripts/` 폴더에 저장하고
반드시 `argparse` 를 사용해 인자를 받는다.

## 규칙 5: 파일 명명 규칙
| 용도 | 위치 | 패턴 |
|------|------|-------|
| 보고서 생성 | `reports/` | `make_*.py` |
| 임시 점검 | `tmp/` | `_check_NN_설명.py` |
| 재사용 유틸 | `scripts/` | `동사_명사.py` (소문자 + 언더스코어) |
| 출력 파일 | `reports/output/` | `ReportName_YYYYMM.xlsx` |

## 규칙 6: 모든 스크립트는 argparse 또는 환경변수
스크립트를 실행할 때 경로나 파라미터를 코드 수정 없이 바꿀 수 있어야 한다.
```python
parser = argparse.ArgumentParser(description='...')
parser.add_argument('--input', required=True, help='입력 엑셀 경로')
parser.add_argument('--ym', required=True, help='기준 연월 YYYYMM')
args = parser.parse_args()
```

## 규칙 7: 월 정기 업무 → 스크립트화
매월 반복하는 작업은 반드시 `scripts/` 또는 `reports/` 아래 스크립트로 만든다.
"이번 한 번만" 이라는 생각으로 임시 코드를 작성하지 않는다.

## 규칙 8: 코드 작성 후 자체 체크리스트
코드를 작성하거나 수정한 뒤 아래 항목을 순서대로 확인한다.
- [ ] 하드코딩된 경로/날짜/이름이 없는가?
- [ ] argparse 인자가 모두 명시되어 있는가?
- [ ] 파일 위치가 규칙 5의 패턴을 따르는가?
- [ ] `python -c` 를 사용하지 않았는가?
- [ ] 임시 파일은 `tmp/` 에 있는가?

## 규칙 9: JS 루프 로직 반드시 추적 검증
HTML/JS 파일의 `for` / `while` 루프를 작성하거나 리뷰할 때 반드시 아래를 확인한다.
- 초기값 → 조건 → 증감 방향이 일치하는가? (예: `y >= min` 이면 반드시 `y--`)
- 탈출 조건(`break`)이 실제로 도달 가능한가?
- 루프 변수가 조건과 같은 방향으로 이동하는가?

## 규칙 10: HTML 페이지 수정 후 반드시 curl 로드 확인
HTML 파일을 수정한 뒤 커밋 전에 아래 명령으로 서버 응답을 확인한다.
```
curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/페이지명.html
```
200이 아닌 경우 서버 재시작 또는 코드 오류 여부를 점검한다.

## 규칙 11: 기능 반영 시 상호연관성 자동 연동 필수
무엇인가를 반영할 때는 항상 서로 상호연관성을 파악하여 자동으로 연관되도록 한다.
- 단일 데이터 소스(SSOT) 원칙: 같은 개념(KPI, 카테고리, 룰 등)을 여러 파일/하드코딩으로 분산하지 않는다.
  설정 페이지에서 정의된 값은 다른 모든 페이지에서 그 값을 직접 참조해야 한다.
- 신규 항목 추가 시: 설정에 항목을 추가하면 사용처(폼 입력란, 드롭다운, 점수계산 등)에 별도 코드 수정 없이
  자동으로 반영되어야 한다 (정적 HTML 폼 X, 동적 렌더링 O).
- 작업 완료 전 점검: "이 값을 settings에서 바꾸면 사용처에서 자동으로 보일까?" 를 모든 연관 페이지에 대해
  실제로 수정 → 새로고침 흐름으로 검증한다. API 200 응답만으로는 부족하다.
- 연관 매트릭스: 변경 위치 / 반영 위치 / 트리거(저장 / 새로고침 / 즉시) 를 작업 전 표로 정리한다.

## 규칙 13: 데이터 동기화 작업 시 docs/DATA_SYNC_RULES.md 필수 참조
`work_tasks` / `daily_work_entries` / `workload_daily_cache` / `performance_records` 등
**입력 → 정규화 → 집계 흐름**에 영향 주는 모든 작업은 시작 전에
`docs/DATA_SYNC_RULES.md` 를 정독한다.
- 핵심 원칙 4가지: SoT는 work_tasks / 저장은 전체 교체 / 체크해제=삭제 / 캐시는 서버 책임
- 신규 기능 추가 시 §4 체크리스트 통과 후 커밋
- 새 버그 패턴 발견 시 §3에 추가하여 미래 회귀 방지
- **데이터 모델 마이그레이션(AS-IS→TO-BE) 작업 시 §7 체크리스트 통과 필수**
  - 새 source/type 명명 + 동기화 함수 전수 검토 + 잔존 검출 스크립트 실행
  - 마이그레이션이 만든 데이터도 사용자 입력과 동등한 정리 책임을 짊어진다
  - 이 단계 누락 시 "영구 좀비 데이터" 발생 (Phase 7-1 settlement_auto 사례)

## 규칙 12: 프론트 작업은 html-ui-designer 서브에이전트에게 위임
HTML/CSS/UI 디자인·반응형·레이아웃 개선 작업은 직접 수정하지 말고
반드시 `html-ui-designer` 서브에이전트에게 위임한다.
- 직접 수정 대상: 기능 로직, JS 동작, 데이터 흐름, API 연동 등
- 위임 대상: 시각 디자인, 모바일/태블릿 반응형, 레이아웃, CSS 스타일링,
  표/카드/모달 등 UI 컴포넌트 개선
- 사용자가 "모바일에서 안 보여" / "디자인 좀 다듬어" / "반응형 적용" 같은
  요청을 할 때는 즉시 Agent 도구로 html-ui-designer 호출
- 매번 사용자 신고를 받고 수정하지 말고, UI 작업이 들어오면 가능한 한
  전 페이지 일괄 점검을 함께 위임할 것

## 규칙 14: 공통 UI 컴포넌트 CSS는 main.css 단독 SSOT
모든 페이지에서 공유하는 UI 컴포넌트(`.modal-overlay`, `.modal-box`, `.sidebar`, `.toast`,
`.btn-*` 등)의 CSS는 **`css/main.css` 한 곳에서만 정의**한다.
페이지 인라인 `<style>` 에서 같은 셀렉터를 재정의 금지.

### 14-1. 모달 시스템 약속
- 비표시 상태: `.modal-overlay` (main.css가 `opacity:0; visibility:hidden`)
- 표시 상태: `.modal-overlay.show` 또는 `.modal-overlay.open` 추가 → `opacity:1; visibility:visible`
- main.css는 **`.show`, `.open` 둘 다 인식**하도록 selector 그룹으로 작성. 페이지 JS는
  둘 중 어느 클래스를 써도 정상 작동.
- 페이지 인라인에서 `.modal-overlay { display:none; ... }` 같은 재정의 절대 금지
  (인라인 `display:none`이 main.css의 `display:flex`를 덮어쓰면 `.open` 추가해도
  opacity/visibility는 main.css 기본값 그대로라 모달이 떠도 화면에 안 보임).

### 14-2. 발견 사례 (2026-05-11)
인사카드/성과관리/지시사항/개인목표/팀목표 5개 페이지에서 수정·등록 모달이
"버튼 누르면 함수는 정상으로 실행되는데 모달이 화면에 안 보이는" 증상.
- 원인: main.css는 `.show` 시스템, 5개 페이지 인라인은 `.open` 시스템으로 명명 불일치
- `.modal-overlay.open { display:flex }` 만 적용되고 main.css의
  `opacity:0; visibility:hidden`이 살아남아 invisible 상태로 유지
- 진단 핵심: `getComputedStyle(modal).opacity / .visibility` 확인. `'0'` / `'hidden'`이면
  CSS 충돌. `classList.contains('open')` 이 `true`인데 안 보이면 100% 이 패턴

### 14-3. main.css 수정 후 캐시 버스트 필수
공유 CSS 파일(`main.css` 등)을 수정한 직후 반드시 모든 HTML의 `?v=N` 쿼리를 +1 한다.
- 브라우저는 동일 URL의 CSS를 캐시하므로 버전을 안 올리면 변경 사항 미반영
- 일괄 변경: `find <루트> -name "*.html" -exec sed -i 's/main\.css?v=N/main.css?v=N+1/g' {} \;`
- HTML 자체는 서버가 `Cache-Control: no-cache` 헤더 보내므로 매 요청마다 새로 받음.
  단 인라인 `<style>` 변경은 HTML 재로드만으로 적용되고 v 쿼리는 불필요.

### 14-4. 새 페이지 작성 / 모달 추가 시 체크리스트
- [ ] 인라인 `<style>` 에 `.modal-overlay { ... }` 정의를 넣지 않았는가?
- [ ] JS는 `classList.add('show')` 또는 `classList.add('open')` 사용 (둘 다 main.css가 인식)
- [ ] main.css를 건드렸다면 모든 HTML의 `?v=` 쿼리 +1 했는가?
- [ ] 같은 패턴(인라인이 main.css 덮어쓰는 케이스)이 카드/툴팁/드롭다운 등 다른 공통
      컴포넌트에 잠재해 있는지 점검했는가?
