"""
5월 검출된 E/F/G 불일치 일괄 정리.

대상:
- E: work_tasks.settlement_pct > 0 인데 settlement_done == [] → pct=0 으로
- F: performance_records.basic_score 가 점수 가중합과 불일치 → 재계산
- G: final_score ≠ basic × (1+bonus_rate) → 재계산

분기 집계 record(month=None) 는 제외.

사용:
    python tmp/_check_07_fix_all_may.py --api http://localhost:8888 --ym 202605 [--dry-run]
"""
import argparse
import json
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def http_json(method, url, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def fetch_rows(api, path):
    d = http_json('GET', api.rstrip('/') + path)
    return d.get('rows') or d.get('data') or d


def grade_of(s):
    if s is None: return 'D'
    if s >= 100: return 'S'
    if s >= 90:  return 'A'
    if s >= 80:  return 'B'
    if s >= 70:  return 'C'
    return 'D'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--api', default='http://localhost:8888')
    ap.add_argument('--ym', required=True, help='YYYYMM')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    y = int(args.ym[:4]); m = int(args.ym[4:])
    base = args.api.rstrip('/')

    defs = fetch_rows(base, '/tables/kpi_definitions?limit=100')
    weight = {'directive': 5, 'csm': 10, 'deadline': 20, 'meeting': 15,
              'kpi1': 20, 'kpi2': 20, 'kpi3': 10}
    for d in defs:
        if d.get('is_active') is False: continue
        if str(d.get('year')) != str(y): continue
        weight[d.get('code')] = d.get('weight_pct') or weight.get(d.get('code'), 0)

    tasks = [t for t in fetch_rows(base, '/tables/work_tasks?limit=500')
             if str(t.get('year')) == str(y) and str(t.get('month')) == str(m)]
    records = [r for r in fetch_rows(base, '/tables/performance_records?limit=500')
               if str(r.get('year')) == str(y) and str(r.get('month')) == str(m)]

    score_codes = ['directive', 'csm', 'deadline', 'meeting', 'kpi1', 'kpi2', 'kpi3']

    actions = []

    # E: work_tasks settlement_pct 잔존
    for t in tasks:
        done = t.get('settlement_done') or []
        if isinstance(done, str):
            try: done = json.loads(done)
            except Exception: done = []
        pct = t.get('settlement_pct')
        if pct not in (None, 0, 0.0, '') and not done:
            actions.append({
                'kind': 'pct_reset',
                'table': 'work_tasks',
                'id': t.get('id'),
                'name': t.get('member_name'),
                'before': {'settlement_pct': pct},
                'patch': {'settlement_pct': 0},
            })

    # F/G: performance_records basic/final 정합성
    for r in records:
        score_map = {c: r.get('score_' + c) for c in score_codes}
        if all(v in (None, '') for v in score_map.values()):
            continue
        weighted = sum(float(v) * (weight.get(c, 0) / 100.0)
                       for c, v in score_map.items() if v not in (None, ''))
        new_basic = round(weighted * 10) / 10

        rate = r.get('bonus_rate')
        if rate in (None, ''):
            rate = (0.1 if r.get('bonus_project') else 0) + (0.1 if r.get('bonus_promotion') else 0)
        new_final = round(new_basic * (1 + float(rate)) * 10) / 10
        new_grade = grade_of(new_final)

        cur_basic = r.get('basic_score')
        cur_final = r.get('final_score')
        cur_grade = r.get('grade')

        patch = {}
        changed_basic = (cur_basic in (None, '')) or abs(float(cur_basic) - new_basic) > 0.15
        changed_final = (cur_final in (None, '')) or abs(float(cur_final) - new_final) > 0.15
        if changed_basic: patch['basic_score'] = new_basic
        if changed_final: patch['final_score'] = new_final
        if changed_basic or changed_final:
            if cur_grade != new_grade:
                patch['grade'] = new_grade
            actions.append({
                'kind': 'perf_recalc',
                'table': 'performance_records',
                'id': r.get('id'),
                'name': r.get('target_name'),
                'before': {'basic_score': cur_basic, 'final_score': cur_final, 'grade': cur_grade},
                'patch': patch,
                'scores': {k: v for k, v in score_map.items() if v not in (None, '')},
            })

    print(f'== 대상 연월: {y}-{m:02d} ==')
    print(f'액션 {len(actions)} 건:')
    for a in actions:
        print(f"  [{a['kind']}] {a['name']} ({a['table']}/{a['id']})")
        print(f"    before: {a['before']}")
        print(f"    patch:  {a['patch']}")
        if 'scores' in a:
            print(f"    scores: {a['scores']}")

    if args.dry_run or not actions:
        print('-- dry-run 또는 변경사항 없음. 종료.')
        return

    print()
    print('--- 적용 시작 ---')
    for a in actions:
        url = f"{base}/tables/{a['table']}/{a['id']}"
        http_json('PATCH', url, a['patch'])
        print(f"  ✓ {a['name']} {a['table']}/{a['id']}")
    print('완료.')


if __name__ == '__main__':
    main()
