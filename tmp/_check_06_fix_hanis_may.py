"""
한인석 2026-5 데이터 정합성 정리 (1회용).
- work_tasks.settlement_pct: 8 → 0  (settlement_done=[] 인데 pct 잔존)
- performance_records.basic_score / final_score 재계산
  (score_kpi1=80 만 있고 다른 점수 모두 null → basic=16, final=basic×(1+rate)=19.2)

사용:
    python tmp/_check_06_fix_hanis_may.py --api http://localhost:8888 [--dry-run]
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
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--api', default='http://localhost:8888')
    ap.add_argument('--dry-run', action='store_true', help='수정 없이 계획만 출력')
    args = ap.parse_args()

    base = args.api.rstrip('/')

    # work_tasks
    wt_id = 'wor_40fd52bf4d0406f8'
    wt = http_json('GET', f'{base}/tables/work_tasks/{wt_id}')
    print(f'[work_tasks {wt_id}] before: settlement_pct={wt.get("settlement_pct")}')

    # performance_records
    pr_id = 'per_e9bf48e37e749926'
    pr = http_json('GET', f'{base}/tables/performance_records/{pr_id}')
    print(f'[performance_records {pr_id}] before: basic={pr.get("basic_score")} final={pr.get("final_score")} kpi1={pr.get("score_kpi1")} rate={pr.get("bonus_rate")}')

    # 재계산: 현재 점수 가중합 (kpi_definitions 에서 weight 읽기)
    defs = http_json('GET', f'{base}/tables/kpi_definitions?limit=100').get('rows', [])
    weight = {'directive': 5, 'csm': 10, 'deadline': 20, 'meeting': 15,
              'kpi1': 20, 'kpi2': 20, 'kpi3': 10}
    for d in defs:
        if d.get('is_active') is not False and d.get('year') == pr.get('year'):
            weight[d.get('code')] = d.get('weight_pct') or weight.get(d.get('code'), 0)

    score_map = {
        'directive': pr.get('score_directive'),
        'csm':       pr.get('score_csm'),
        'deadline':  pr.get('score_deadline'),
        'meeting':   pr.get('score_meeting'),
        'kpi1':      pr.get('score_kpi1'),
        'kpi2':      pr.get('score_kpi2'),
        'kpi3':      pr.get('score_kpi3'),
    }
    weighted = 0.0
    for code, v in score_map.items():
        if v in (None, ''):
            continue
        weighted += float(v) * (weight.get(code, 0) / 100.0)
    new_basic = round(weighted * 10) / 10

    rate = pr.get('bonus_rate')
    if rate in (None, ''):
        rate = (0.1 if pr.get('bonus_project') else 0) + (0.1 if pr.get('bonus_promotion') else 0)
    new_final = round(new_basic * (1 + float(rate)) * 10) / 10

    def grade_of(s):
        if s >= 100: return 'S'
        if s >= 90:  return 'A'
        if s >= 80:  return 'B'
        if s >= 70:  return 'C'
        return 'D'
    new_grade = grade_of(new_final)

    print(f'  계산: basic={new_basic}, final={new_final} (rate={rate}), grade={new_grade}')

    if args.dry_run:
        print('-- dry-run 모드: 변경하지 않고 종료')
        return

    # 1) work_tasks settlement_pct 정리
    if wt.get('settlement_pct') not in (None, 0, 0.0):
        http_json('PATCH', f'{base}/tables/work_tasks/{wt_id}', {'settlement_pct': 0})
        print('  ✓ work_tasks.settlement_pct → 0')

    # 2) performance_records basic/final/grade 정리
    patch = {'basic_score': new_basic, 'final_score': new_final, 'grade': new_grade}
    http_json('PATCH', f'{base}/tables/performance_records/{pr_id}', patch)
    print(f'  ✓ performance_records: basic={new_basic}, final={new_final}, grade={new_grade}')

    # 검증
    wt2 = http_json('GET', f'{base}/tables/work_tasks/{wt_id}')
    pr2 = http_json('GET', f'{base}/tables/performance_records/{pr_id}')
    print(f'[after] work_tasks.settlement_pct={wt2.get("settlement_pct")}')
    print(f'[after] perf basic={pr2.get("basic_score")} final={pr2.get("final_score")} grade={pr2.get("grade")}')


if __name__ == '__main__':
    main()
