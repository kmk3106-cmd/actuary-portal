"""
daily_work_entries.task_category 백필.
- manual 행: work_tasks.other_tasks 의 cat(대구분 라벨) 을 (member, ym, desc) 매칭으로 채움.
- settlement 행은 서버 computeByType 가 source 로 처리하므로 백필 불필요.

사용:
    python tmp/_check_09_backfill_category.py --api http://localhost:8888 [--dry-run]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--api', default='http://localhost:8888')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    base = args.api.rstrip('/')
    wt_data = http_json('GET', f'{base}/tables/work_tasks?limit=500')
    dwe_data = http_json('GET', f'{base}/tables/daily_work_entries?limit=1000')

    # (member, ym, desc) → cat
    cat_map = {}
    for w in wt_data.get('rows', []):
        name = w.get('member_name')
        y = w.get('year'); m = w.get('month')
        if not (name and y and m): continue
        ym = f'{y}-{str(m).zfill(2)}'
        for t in (w.get('other_tasks') or []):
            desc = (t.get('desc') or '').strip()
            cat = (t.get('cat') or '').strip()
            if desc and cat:
                cat_map[(name, ym, desc)] = cat

    targets = []
    for e in dwe_data.get('rows', []):
        if e.get('source') != 'manual': continue
        if e.get('task_category'): continue
        name = e.get('member_name')
        ed = (e.get('end_date') or e.get('start_date') or '')
        ym = ed[:7]
        desc = (e.get('task_label') or '').strip()
        cat = cat_map.get((name, ym, desc))
        if cat:
            targets.append({'id': e['id'], 'name': name, 'desc': desc, 'cat': cat})
        else:
            targets.append({'id': e['id'], 'name': name, 'desc': desc, 'cat': '기타'})

    print(f'백필 대상: {len(targets)} 건')
    for t in targets[:30]:
        print(f"  {t['name']:8} \"{t['desc'][:40]}\" → cat={t['cat']}")

    if args.dry_run or not targets:
        print('-- dry-run / 변경사항 없음 종료')
        return

    print('\n--- 적용 시작 ---')
    for t in targets:
        http_json('PATCH', f'{base}/tables/daily_work_entries/{t["id"]}', {'task_category': t['cat']})
        print(f"  ✓ {t['name']} {t['id'][:25]}")
    print('완료.')


if __name__ == '__main__':
    main()
