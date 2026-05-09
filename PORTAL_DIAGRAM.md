# 계리결산팀 운영관리포탈 — 프로그램 구조 도식

## 1. 전체 페이지 맵

```
index.html (대시보드)
│
├── [팀 관리]
│   ├── identity.html       팀 정체성 · 핵심가치
│   ├── goals-team.html     팀 목표
│   ├── goals-individual.html  개인 목표 (SMART)
│   ├── personnel.html      인사카드 (부임일·연차)
│   └── directives.html     팀장 지시사항
│
├── [결산 관리]
│   ├── settlement.html     결산 캘린더 + 체크리스트 ★핵심
│   └── settlement-review.html  결산 리뷰 (팀장 전용)
│
├── [성과 관리]
│   ├── performance.html    성과관리 종합표 · 개인카드
│   └── work-personal.html  개인별 업무입력 (정량평가)
│
├── [자동화 · 보고]
│   ├── automation.html     업무 자동화 로그
│   └── reports.html        보고서 자동생성 (계리/경영/재무)
│
└── [모니터링]
    └── bot-status.html     텔레그램 봇 상태
```

---

## 2. 데이터 흐름 (핵심 선후관계)

### 2-1. 결산기한준수 점수 흐름

```
[settlement.html] 결산 체크리스트
  ① 팀원이 완료일 입력 (date input)
  ② autoCalcDeadline() — 완료일 → 단축/지연일(D+N 기준) 자동산출
       getRelativeBizDay() — 이전달 날짜도 처리 (마지막 영업일=0, 그전=-1...)
  ③ 저장(saveChecklist()) 클릭
       └→ work_tasks 테이블 저장 (settlement_deadline_days: {s01:2, s12:0, ...})
       └→ pushDeadlineToPerf() 자동 호출
            calcDeadlineAvgScore() — 담당 업무별 점수 동일가중치 평균
            └→ performance_records 테이블 score_deadline 갱신
                                           ↓
[performance.html] 성과관리 화면에서 score_deadline 자동 반영
```

### 2-2. 정량평가 전체 흐름

```
[work-personal.html] 개인별 업무입력
  ① 팀원이 정량 지표 입력:
       s1: 지시수행 (건수)
       s2: 재무수치안 (건수)
       s3: 결산기한준수 ← settlement.html에서 자동유입 (읽기전용)
       s4: 임원회의소스 (건수)
  ② "성과관리에 반영" 버튼 → pushQuantToPerf()
       └→ performance_records.score_directive / score_csm / score_deadline / score_meeting 갱신
                                           ↓
[performance.html] 성과관리 화면에서 전체 점수 자동 계산
  기본점수 = score_directive×0.05 + score_csm×0.10
           + score_deadline×0.20 + score_meeting×0.15
           + score_kpi1×0.20 + score_kpi2×0.20 + score_kpi3×0.10
  최종점수 = 기본점수 × (1 + bonus_rate)
           bonus_rate = 프로젝트(+10%) + 승진(+10%)
```

### 2-3. 텔레그램 봇 데이터 흐름

```
[bot/app.py] 텔레그램 봇
  ↓ 쿼리 수신 (자연어 명령)
  ↓ parser.py → 의도 파악
  ↓ query_engine.py → portal-db.json 직접 읽기
  ↓ formatters.py → 마크다운 포맷
  ↓ 텔레그램 메시지 전송
     예시 명령: /결산현황, /성과, /팀원정보
```

### 2-4. 보고서 생성 흐름

```
[reports.html] 보고서 자동생성
  ① 유형 선택 (계리/경영/재무) + 기준월 + 작성자
  ② POST /api/reports/generate
       └→ server.js → reports/ 폴더 Python 스크립트 실행
  ③ 생성 이력: report_history 테이블 저장
  ④ 이력 조회 + 다운로드 / 삭제 버튼
```

---

## 3. 점수 산출 규칙

### 3-1. 결산기한준수 (score_deadline)

| 단축/지연일 | 점수 |
|------------|------|
| +2 이상    | 100  |
| +1         | 90   |
| 0 (기한준수)| 80  |
| -1         | 70   |
| -2         | 60   |
| -3 이하    | 0    |

- 복수 업무 담당 시 **동일가중치 평균** (예: 90점 + 80점 = **85점**)

### 3-2. 기타 정량평가

| 항목 | 산출 기준 |
|------|----------|
| 지시수행 (s1) | 건수 → 점수 환산 |
| 재무수치안 (s2) | 건수 → 점수 환산 |
| 임원회의소스 (s4) | 건수 → 점수 환산 |

### 3-3. 최종점수 가중치

| 항목 | 비중 |
|------|------|
| 지시수행 | 5% |
| 재무수치안 | 10% |
| 기한준수 | 20% |
| 임원소스 | 15% |
| KPI1 (계리모델AI활용) | 20% |
| KPI2 (재무수치분석) | 20% |
| KPI3 (계리지원강화) | 10% |
| **합계** | **100%** |

가산: 프로젝트 +10%, 승진대상 +10% (기본점수에 곱)

---

## 4. DB 테이블 구조 (주요)

```
work_tasks              개인별 업무 입력값
  id, year, month, member_name
  settlement_done[]     완료한 결산업무 id 목록
  settlement_dates{}    taskId → 완료일 (YYYY-MM-DD)
  settlement_times{}    taskId → 소요시간(분)
  settlement_deadline_days{}  taskId → 단축(+)/지연(-) 일수

performance_records     성과 평가 레코드
  id, year, month, target_name
  score_directive, score_csm, score_deadline, score_meeting  ← 정량
  score_kpi1, score_kpi2, score_kpi3                         ← 정성(팀장입력)
  basic_score, final_score, grade
  bonus_project, bonus_promotion
  self_comment, leader_comment

work_tasks (정량별도)
  quantitative_data{}   s1~s4 정량 raw값

settlement_calendar     캘린더 이벤트 (D+N 마감일 자동생성)
report_history          보고서 생성이력
```

---

## 5. SETTLE_SCHEDULE 담당자 매핑 (26개 항목)

| 그룹 | 항목 | 담당자 |
|------|------|--------|
| IFRS4 | 계리계약마감 | 오정택 |
| IFRS4 | 지급준비금 마감(실효만기) | 이용우 |
| IFRS4 | 지급준비금 마감(생존사고) | 이용우 |
| IFRS4 | 준비금마감 | 강세진 |
| IFRS4 | 보험료분해마감 | 김채린 |
| IFRS4 | 재보험마감 | 김예은 |
| IFRS4 | 보증준비금마감 | 강세진 |
| IFRS4 | 잉여금처리&계약자배당 | 이상현 |
| IFRS4 | 예금보험료 | 강세진 |
| IFRS17 BEL&RA | 결산모델배포 | 한인석 |
| IFRS17 BEL&RA | 계리모델입력데이터준비 | 김예은/이성원 |
| IFRS17 BEL&RA | 경제적가정산출 | 이상백 |
| IFRS17 BEL&RA | 최초/후속모델포인트생성 | 이성원 |
| IFRS17 BEL&RA | 최초인식보험부채산출 | 김예은 |
| IFRS17 BEL&RA | 후속측정보험부채산출 | 한인석/이성원 |
| IFRS17 BEL&RA | 사업비배부 | 마혜원 |
| IFRS17 부채결산 | 최초인식대상계약확정 | 이용우 |
| IFRS17 부채결산 | 결산대상계약확정 | 이용우 |
| IFRS17 부채결산 | 가중평균할인율산출 | 예대호 |
| IFRS17 부채결산 | BEL/RA data입수및계약그룹작업 | 이동민 |
| IFRS17 부채결산 | 결산대상계약및실제CF이관(재보험) | 김예은 |
| IFRS17 부채결산 | 실제CF Data이관(ETL) | 이동민 |
| IFRS17 부채결산 | 가중평균할인율산출(재보험) | 예대호 |
| IFRS17 부채결산 | BEL/RA data입수(재보험) | 김예은 |
| IFRS17 부채결산 | 부채결산무브먼트 | 이동민 |
| IFRS17 부채결산 | 부채결산무브먼트(재보험) | 김예은 |
| IFRS17 부채결산 | 회계팀결산Data전송 | 예대호 |

---

## 6. 서버 구동 순서

```bash
# 1. 포탈 서버 (port 8888)
node server/server.js

# 2. 텔레그램 봇 (별도 프로세스)
cd bot && python app.py
# 또는 Windows: bot/run.bat

# 3. 접속
http://localhost:8888
```

---

## 7. 파일 구조

```
actuary potal/
├── index.html              대시보드
├── settlement.html         결산캘린더+체크리스트 (핵심)
├── performance.html        성과관리
├── work-personal.html      개인별업무입력
├── reports.html            보고서생성
├── bot-status.html         봇상태
├── *.html                  기타 페이지
│
├── js/
│   ├── portal.js           공통 유틸 (showToast, confirm, formatDate 등)
│   ├── rbac.js             역할기반접근제어
│   └── auth.js             인증 처리
│
├── css/
│   └── main.css            공통 스타일
│
├── server/
│   ├── server.js           Node.js HTTP 서버 (port 8888)
│   └── data/
│       └── portal-db.json  JSON 파일 DB
│
├── bot/                    텔레그램 봇
│   ├── app.py              메인 봇 진입점
│   ├── parser.py           자연어 파싱
│   ├── query_engine.py     데이터 조회
│   ├── formatters.py       응답 포맷
│   └── .env                봇 토큰 설정
│
├── scripts/                재사용 스크립트
├── reports/                보고서 Python 스크립트
├── tmp/                    임시 점검 스크립트
└── PORTAL_DIAGRAM.md       본 파일
```
