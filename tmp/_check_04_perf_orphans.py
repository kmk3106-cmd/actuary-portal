"""
성과관리(performance_records) 잔존 데이터 검출.
CLAUDE.md 규칙 13 + DATA_SYNC_RULES §7 체크리스트 준수.

검출 케이스:
- A: score_*가 있는데 work_tasks의 raw 데이터(settlement_done, other_tasks)가 비어있음
     → work_tasks 변경 후 동기화 누락된 옛 점수
- B: target_name이 현재 users(is_active=true)에 없는 record (퇴직자 또는 삭제된 멤버)
- D: work_tasks.settlement_done 에 없는데 settlement_deadline_days 에 키 잔존
     (DATA_SYNC_RULES §3 버그 A)
- E: work_tasks.settlement_pct > 0 인데 settlement_done == []
     → 결산 체크 해제 후 pct 잔존 (UI 표시 오류 가능)
- F: performance_records.basic_score 가 현재 점수 가중합과 불일치
     → push*ToPerf 후 basic_score 재계산 누락
- G: performance_records.final_score ≠ basic_score × (1 + bonus_rate)
     → basic 갱신 시 final 재계산 누락

사용:
    python tmp/_check_04_perf_orphans.py --api http://localhost:8888 --ym 202605
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
from collections import defaultdict

# Windows PowerShell cp949 회피 — stdout을 UTF-8로 강제
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def fetch_json(api_base, path):
    url = api_base.rstrip('/') + path
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode('utf-8'))
    return data.get('rows') or data.get('data') or data


def main():
    ap = argparse.ArgumentParser(description='Performance records orphan detector')
    ap.add_argument('--api', default='http://localhost:8888', help='API 베이스 URL')
    ap.add_argument('--ym', default=None, help='기준 연월 YYYYMM (생략 시 전체)')
    args = ap.parse_args()

    target_year = target_month = None
    if args.ym:
        target_year = int(args.ym[:4])
        target_month = int(args.ym[4:])

    print(f'== 성과관리 잔존 데이터 검출 (API: {args.api}) ==')
    if args.ym:
        print(f'== 대상 연월: {target_year}-{target_month:02d} ==')
    print()

    users = fetch_json(args.api, '/tables/users?limit=500')
    active_names = {u.get('full_name') for u in users if u.get('is_active') is not False}
    all_names = {u.get('full_name') for u in users}
    print(f'활성 사용자: {len(active_names)} 명 / 전체: {len(all_names)} 명')

    records = fetch_json(args.api, '/tables/performance_records?limit=500')
    if target_year and target_month:
        records = [
            r for r in records
            if str(r.get('year')) == str(target_year)
            and str(r.get('month')) == str(target_month)
        ]
    print(f'성과 기록: {len(records)} 건')
    print()

    tasks = fetch_json(args.api, '/tables/work_tasks?limit=500')
    if target_year and target_month:
        tasks = [
            t for t in tasks
            if str(t.get('year')) == str(target_year)
            and str(t.get('month')) == str(target_month)
        ]

    # key: (target_name, year, month) → work_task
    tasks_by_key = {}
    for t in tasks:
        key = (t.get('member_name') or t.get('target_name'), str(t.get('year')), str(t.get('month')))
        tasks_by_key[key] = t

    score_fields = [
        'score_directive', 'score_csm', 'score_deadline', 'score_meeting',
        'score_kpi1', 'score_kpi2', 'score_kpi3',
        'basic_score', 'leader_score', 'final_score',
    ]

    # KPI 가중치는 kpi_definitions API에서 동적으로 로드 (하드코딩 금지)
    try:
        kpi_defs = fetch_json(args.api, '/tables/kpi_definitions?limit=100')
    except Exception:
        kpi_defs = []
    # 정량 가중치 fallback (autoCalcScores 의 quantW 와 동일)
    weight_by_code = {'directive': 5, 'csm': 10, 'deadline': 20, 'meeting': 15,
                      'kpi1': 20, 'kpi2': 20, 'kpi3': 10}
    cur_year = target_year if target_year else None
    for k in kpi_defs:
        if k.get('is_active') is False:
            continue
        if cur_year and str(k.get('year')) != str(cur_year):
            continue
        weight_by_code[k.get('code')] = k.get('weight_pct') or weight_by_code.get(k.get('code'), 0)

    case_b = []  # 비활성/삭제된 사용자의 record
    case_a_deadline = []  # score_deadline 있는데 work_task settlement_done 비어있음
    case_a_quant = []     # score_directive/csm/meeting 있는데 work_task other_tasks 비어있음
    case_d = []           # work_task settlement_deadline_days 잔존
    case_e = []           # work_task settlement_pct > 0 인데 settlement_done == []
    case_f = []           # basic_score 와 가중합 불일치
    case_g = []           # final_score ≠ basic × (1+bonus_rate)

    for r in records:
        name = r.get('target_name')
        y = str(r.get('year'))
        m = str(r.get('month'))
        has_score = any(r.get(f) is not None and r.get(f) != '' for f in score_fields)

        # B 케이스
        if name and name not in active_names and has_score:
            case_b.append({
                'id': r.get('id'),
                'name': name,
                'ym': f'{y}-{m}',
                'in_users_table': name in all_names,
                'scores': {f: r.get(f) for f in score_fields if r.get(f)},
            })

        # A 케이스 (deadline)
        if r.get('score_deadline') not in (None, '', 0):
            task = tasks_by_key.get((name, y, m))
            if task:
                done = task.get('settlement_done') or []
                if isinstance(done, str):
                    try:
                        done = json.loads(done)
                    except Exception:
                        done = []
                if not done:
                    case_a_deadline.append({
                        'id': r.get('id'),
                        'name': name,
                        'ym': f'{y}-{m}',
                        'score_deadline': r.get('score_deadline'),
                        'reason': 'work_task.settlement_done이 비어있음',
                    })

        # A 케이스 (quant - directive/csm/meeting)
        for f in ['score_directive', 'score_csm', 'score_meeting']:
            if r.get(f) not in (None, '', 0):
                task = tasks_by_key.get((name, y, m))
                if task:
                    other = task.get('other_tasks') or []
                    if isinstance(other, str):
                        try:
                            other = json.loads(other)
                        except Exception:
                            other = []
                    if not other:
                        case_a_quant.append({
                            'id': r.get('id'),
                            'name': name,
                            'ym': f'{y}-{m}',
                            'field': f,
                            'value': r.get(f),
                            'reason': 'work_task.other_tasks가 비어있음',
                        })

    # D 케이스: work_tasks 자체 점검
    for t in tasks:
        name = t.get('member_name') or t.get('target_name')
        y = str(t.get('year'))
        m = str(t.get('month'))
        done = t.get('settlement_done') or []
        if isinstance(done, str):
            try:
                done = json.loads(done)
            except Exception:
                done = []
        done_set = set(done)
        dd = t.get('settlement_deadline_days') or {}
        if isinstance(dd, str):
            try:
                dd = json.loads(dd)
            except Exception:
                dd = {}
        orphans = [k for k in dd.keys() if k not in done_set]
        if orphans:
            case_d.append({
                'id': t.get('id'),
                'name': name,
                'ym': f'{y}-{m}',
                'orphan_keys': orphans,
            })

        # E 케이스: settlement_pct > 0 인데 settlement_done == []
        pct = t.get('settlement_pct')
        if pct not in (None, 0, 0.0, '') and not done:
            case_e.append({
                'id': t.get('id'),
                'name': name,
                'ym': f'{y}-{m}',
                'settlement_pct': pct,
            })

    # F/G 케이스: performance_records 의 basic_score / final_score 정합성
    score_code_to_field = {
        'directive': 'score_directive', 'csm': 'score_csm',
        'deadline': 'score_deadline', 'meeting': 'score_meeting',
        'kpi1': 'score_kpi1', 'kpi2': 'score_kpi2', 'kpi3': 'score_kpi3',
    }
    TOL = 0.15  # 반올림(소수 1자리) 오차 + 가중치 변동 가능성 허용
    for r in records:
        # 분기 집계 record(month=None, id 'pr_*q*') 는 월별 평균이라 가중합 검증 의미 없음 → 스킵
        if r.get('month') in (None, '', 0) or str(r.get('id', '')).startswith('pr_') and 'q' in str(r.get('id', '')):
            continue
        # 합산할 점수가 하나도 없으면 스킵 (B 케이스에서 별도 처리)
        score_vals = {code: r.get(field) for code, field in score_code_to_field.items()}
        if all(v in (None, '') for v in score_vals.values()):
            continue

        weighted_sum = 0.0
        for code, v in score_vals.items():
            if v in (None, ''):
                continue
            w = weight_by_code.get(code, 0)
            weighted_sum += float(v) * (w / 100.0)
        expected_basic = round(weighted_sum * 10) / 10

        actual_basic = r.get('basic_score')
        if actual_basic in (None, ''):
            # 점수는 있는데 basic_score가 비어있음 → 불일치
            case_f.append({
                'id': r.get('id'),
                'name': r.get('target_name'),
                'ym': f"{r.get('year')}-{r.get('month')}",
                'expected_basic': expected_basic,
                'actual_basic': actual_basic,
                'scores': {k: v for k, v in score_vals.items() if v not in (None, '')},
            })
        elif abs(float(actual_basic) - expected_basic) > TOL:
            case_f.append({
                'id': r.get('id'),
                'name': r.get('target_name'),
                'ym': f"{r.get('year')}-{r.get('month')}",
                'expected_basic': expected_basic,
                'actual_basic': actual_basic,
                'scores': {k: v for k, v in score_vals.items() if v not in (None, '')},
            })

        # G: final_score = basic × (1+bonus_rate)
        actual_final = r.get('final_score')
        if actual_basic not in (None, '') and actual_final not in (None, ''):
            rate = r.get('bonus_rate')
            if rate in (None, ''):
                rate = (0.1 if r.get('bonus_project') else 0) + (0.1 if r.get('bonus_promotion') else 0)
            expected_final = round(float(actual_basic) * (1 + float(rate)) * 10) / 10
            if abs(float(actual_final) - expected_final) > TOL:
                case_g.append({
                    'id': r.get('id'),
                    'name': r.get('target_name'),
                    'ym': f"{r.get('year')}-{r.get('month')}",
                    'basic': actual_basic,
                    'bonus_rate': rate,
                    'expected_final': expected_final,
                    'actual_final': actual_final,
                })

    print('=== A 케이스: 점수는 있는데 raw 데이터 비어있음 ===')
    print(f'  score_deadline 잔존: {len(case_a_deadline)} 건')
    for x in case_a_deadline[:15]:
        print(f'    {x["name"]} {x["ym"]}: score_deadline={x["score_deadline"]} ({x["reason"]})')
    print(f'  정량 KPI(directive/csm/meeting) 잔존: {len(case_a_quant)} 건')
    for x in case_a_quant[:15]:
        print(f'    {x["name"]} {x["ym"]} {x["field"]}={x["value"]} ({x["reason"]})')

    print()
    print('=== B 케이스: 비활성/삭제된 사용자의 성과 기록 ===')
    print(f'  총 {len(case_b)} 건')
    for x in case_b[:15]:
        marker = '(users 테이블에 있지만 is_active=false)' if x['in_users_table'] else '(users 테이블에 없음)'
        print(f'    {x["name"]} {x["ym"]} {marker}')
        print(f'      scores: {x["scores"]}')

    print()
    print('=== D 케이스: work_tasks에 deadline_days 잔존 (DATA_SYNC_RULES §3 버그 A) ===')
    print(f'  총 {len(case_d)} 건')
    for x in case_d[:15]:
        print(f'    {x["name"]} {x["ym"]}: 잔존 키 = {x["orphan_keys"]}')

    print()
    print('=== E 케이스: settlement_pct > 0 인데 settlement_done == [] ===')
    print(f'  총 {len(case_e)} 건')
    for x in case_e[:15]:
        print(f'    {x["name"]} {x["ym"]}: settlement_pct={x["settlement_pct"]}')

    print()
    print('=== F 케이스: basic_score 가 점수 가중합과 불일치 ===')
    print(f'  총 {len(case_f)} 건')
    for x in case_f[:15]:
        print(f'    {x["name"]} {x["ym"]}: 실제={x["actual_basic"]} / 예상={x["expected_basic"]}  scores={x["scores"]}')

    print()
    print('=== G 케이스: final_score ≠ basic × (1+bonus_rate) ===')
    print(f'  총 {len(case_g)} 건')
    for x in case_g[:15]:
        print(f'    {x["name"]} {x["ym"]}: 실제 final={x["actual_final"]} / 예상={x["expected_final"]} (basic={x["basic"]}, rate={x["bonus_rate"]})')

    print()
    print('=== 요약 ===')
    print(f'  A(deadline 잔존): {len(case_a_deadline)}')
    print(f'  A(quant 잔존):    {len(case_a_quant)}')
    print(f'  B(비활성 record): {len(case_b)}')
    print(f'  D(work_tasks 잔존): {len(case_d)}')
    print(f'  E(settlement_pct 잔존): {len(case_e)}')
    print(f'  F(basic_score 불일치):  {len(case_f)}')
    print(f'  G(final_score 불일치):  {len(case_g)}')


if __name__ == '__main__':
    main()
