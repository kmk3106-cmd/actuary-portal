"""
daily_work_entries.time_entries[].minutes 백필.
점심(12:00-13:00) 1h 차감 정책에 맞춰 재계산.
부수효과: 서버 PATCH 훅이 workload_daily_cache 도 자동 재계산.

사용:
    python tmp/_check_08_backfill_lunch.py --api http://localhost:8888 [--dry-run]
"""
import argparse
import json
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

LUNCH_S = 12 * 60
LUNCH_E = 13 * 60


def hhmm_to_min(s):
    h, m = str(s).split(':')
    return int(h) * 60 + int(m)


def lunch_overlap(s, e):
    if e <= s:
        return 0
    return max(0, min(e, LUNCH_E) - max(s, LUNCH_S))


def net_minutes(s, e):
    if e <= s:
        return 0
    return (e - s) - lunch_overlap(s, e)


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
    d = http_json('GET', f'{base}/tables/daily_work_entries?limit=1000')
    rows = d.get('rows') or d.get('data') or d

    targets = []
    for e in rows:
        tes = e.get('time_entries') or []
        if not isinstance(tes, list) or not tes:
            continue
        new_tes = []
        changed = False
        for te in tes:
            s = te.get('start'); ee = te.get('end')
            if not s or not ee:
                new_tes.append(te); continue
            try:
                sm = hhmm_to_min(s); em = hhmm_to_min(ee)
            except Exception:
                new_tes.append(te); continue
            new_min = net_minutes(sm, em)
            old_min = te.get('minutes')
            if old_min != new_min:
                changed = True
            new_tes.append({**te, 'minutes': new_min})
        if changed:
            new_total = sum(int(t.get('minutes') or 0) for t in new_tes)
            targets.append({
                'id': e['id'],
                'member': e.get('member_name'),
                'old_total': e.get('total_minutes') or e.get('duration_minutes'),
                'new_total': new_total,
                'time_entries': new_tes,
            })

    print(f'백필 대상: {len(targets)} 건')
    for t in targets[:30]:
        print(f"  {t['member']:8} id={t['id']}: total {t['old_total']} → {t['new_total']}분")

    if args.dry_run or not targets:
        print('-- dry-run / 변경사항 없음 종료')
        return

    print('\n--- 적용 시작 ---')
    for t in targets:
        body = {'time_entries': t['time_entries'], 'total_minutes': t['new_total'], 'duration_minutes': t['new_total']}
        http_json('PATCH', f'{base}/tables/daily_work_entries/{t["id"]}', body)
        print(f"  ✓ {t['member']} {t['id']}")
    print('완료. (workload_daily_cache는 서버 훅이 자동 재계산)')


if __name__ == '__main__':
    main()
