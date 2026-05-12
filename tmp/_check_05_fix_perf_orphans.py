"""
성과관리 잔존 점수 9건 정리 (1단계).
_check_04_perf_orphans.py 와 같은 검출 로직으로 찾은 record의
score_deadline / score_directive / score_csm / score_meeting 을 null로 PATCH.

CLAUDE.md 규칙 13 + DATA_SYNC_RULES §7 준수.

사용:
    python tmp/_check_05_fix_perf_orphans.py --api http://localhost:8888 --dry-run  # 미리보기
    python tmp/_check_05_fix_perf_orphans.py --api http://localhost:8888            # 실행
"""
import argparse
import json
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def fetch_json(api_base, path):
    url = api_base.rstrip('/') + path
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def patch_record(api_base, record_id, body):
    url = api_base.rstrip('/') + '/tables/performance_records/' + record_id
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, method='PATCH',
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode('utf-8')


def main():
    ap = argparse.ArgumentParser(description='Fix orphan performance scores')
    ap.add_argument('--api', default='http://localhost:8888', help='API 베이스 URL')
    ap.add_argument('--dry-run', action='store_true', help='실제 PATCH 안 보내고 미리보기만')
    args = ap.parse_args()

    print(f'== 잔존 성과 점수 정리 (API: {args.api}, dry-run={args.dry_run}) ==')

    users = fetch_json(args.api, '/tables/users?limit=500')
    users = users.get('rows') or users.get('data') or users
    records = fetch_json(args.api, '/tables/performance_records?limit=500')
    records = records.get('rows') or records.get('data') or records
    tasks = fetch_json(args.api, '/tables/work_tasks?limit=500')
    tasks = tasks.get('rows') or tasks.get('data') or tasks

    tasks_by_key = {}
    for t in tasks:
        key = (t.get('member_name') or t.get('target_name'), str(t.get('year')), str(t.get('month')))
        tasks_by_key[key] = t

    fixes = []  # (record, fields_to_null)

    for r in records:
        name = r.get('target_name')
        y = str(r.get('year'))
        m = str(r.get('month'))
        task = tasks_by_key.get((name, y, m))
        fields_to_null = {}

        # A-deadline: score_deadline 있는데 settlement_done 비어있음
        if r.get('score_deadline') not in (None, '', 0):
            done = (task or {}).get('settlement_done') or []
            if isinstance(done, str):
                try: done = json.loads(done)
                except Exception: done = []
            if not done:
                fields_to_null['score_deadline'] = None

        # A-quant: score_directive/csm/meeting 있는데 other_tasks 비어있음
        for f in ['score_directive', 'score_csm', 'score_meeting']:
            if r.get(f) not in (None, '', 0):
                other = (task or {}).get('other_tasks') or []
                if isinstance(other, str):
                    try: other = json.loads(other)
                    except Exception: other = []
                if not other:
                    fields_to_null[f] = None

        if fields_to_null:
            fixes.append((r, fields_to_null))

    print(f'정리 대상: {len(fixes)} 건')
    for r, fields in fixes:
        print(f'  [{r.get("id")}] {r.get("target_name")} {r.get("year")}-{r.get("month")}')
        for f, v in fields.items():
            print(f'      {f}: {r.get(f)} → null')

    if args.dry_run:
        print()
        print('== dry-run 종료 (PATCH 보내지 않음) ==')
        return

    print()
    print('== PATCH 시작 ==')
    success = 0
    failed = 0
    for r, fields in fixes:
        try:
            status, _ = patch_record(args.api, r['id'], fields)
            if 200 <= status < 300:
                success += 1
                print(f'  OK  {r.get("target_name")} {r.get("year")}-{r.get("month")} → {list(fields.keys())}')
            else:
                failed += 1
                print(f'  FAIL [{status}] {r.get("target_name")} {r.get("year")}-{r.get("month")}')
        except Exception as e:
            failed += 1
            print(f'  ERR  {r.get("target_name")} {r.get("year")}-{r.get("month")} : {e}')

    print()
    print(f'== 완료: 성공 {success} / 실패 {failed} ==')


if __name__ == '__main__':
    main()
