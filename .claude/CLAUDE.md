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
