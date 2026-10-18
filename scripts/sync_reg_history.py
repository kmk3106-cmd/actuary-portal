#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
규정 개정이력 일일 동기화 — 수집 → 리포트 생성 → 포탈 적재 를 한 번에.
서버(server/server.js) 가 매일 1회 호출하고, 사람이 수동으로 돌려도 된다.

  python scripts/sync_reg_history.py --base-url http://127.0.0.1:8888 --data-dir server/data/reg_history --days 120
  python scripts/sync_reg_history.py --base-url https://portal.kkuks.com --data-dir server/data/reg_history --since 2023-01-01

동작
  1. collect_reg_history.py  : --since 이후 이벤트를 수집하되 data-dir/reg_history.json 에 이미 있는 건은 재수집하지 않는다 (--merge)
  2. make_reg_report.py      : 새로 들어온 이벤트만 리포트 HTML 생성 (data-dir/reports/)
  3. load_reg_history.py     : 포탈에 없는 건만 등록 (source_key 기준 멱등). 손으로 만든 리포트는 --doc-override 로 유지
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DAYS = 120


def run(cmd):
    print('$ ' + ' '.join(cmd), file=sys.stderr)
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f'실패 ({r.returncode}): {cmd[1] if len(cmd) > 1 else cmd}')


def main():
    ap = argparse.ArgumentParser(description='규정 개정이력 일일 동기화')
    ap.add_argument('--base-url', required=True)
    ap.add_argument('--data-dir', required=True, help='reg_history.json · files/ · reports/ 를 두는 폴더')
    ap.add_argument('--since', help='수집 시작일 (기본: 오늘-days)')
    ap.add_argument('--days', type=int, default=DEFAULT_DAYS)
    ap.add_argument('--author-id', default='')
    ap.add_argument('--author-name', default='자동수집')
    ap.add_argument('--doc-override', action='append', default=[])
    ap.add_argument('--delay', type=float, default=1.0)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    since = a.since or (dt.date.today() - dt.timedelta(days=a.days)).isoformat()
    data = os.path.join(a.data_dir, 'reg_history.json')
    files = os.path.join(a.data_dir, 'files')
    reports = os.path.join(a.data_dir, 'reports')
    os.makedirs(a.data_dir, exist_ok=True)
    before = set()
    if os.path.exists(data):
        before = {e['id'] for e in json.load(open(data, encoding='utf-8'))}

    py = sys.executable
    run([py, '-I', os.path.join(HERE, 'collect_reg_history.py'), '--since', since, '--out', data, '--files-dir', files,
         '--delay', str(a.delay), '--merge', data])
    # 국가법령정보 API 보강 (인증키 LAW_API_KEY 가 있을 때만): 법령 공포본 이벤트 + 행정규칙 부칙 시행일
    if os.environ.get('LAW_API_KEY'):
        run([py, '-I', os.path.join(HERE, 'enrich_reg_history_law.py'), '--data', data, '--since', since, '--delay', str(max(a.delay, 2.0))])
    else:
        print('LAW_API_KEY 없음 — 법령정보 API 보강 생략 (server/.env 에 LAW_API_KEY=… 설정)', file=sys.stderr)
    after = json.load(open(data, encoding='utf-8'))
    new_ids = [e['id'] for e in after if e['id'] not in before]
    idx_path = os.path.join(reports, '_index.json')
    need = new_ids if os.path.exists(idx_path) else [e['id'] for e in after]
    if need:
        run([py, '-I', os.path.join(ROOT, 'reports', 'make_reg_report.py'), '--data', data, '--out-dir', reports] + (['--ids', ','.join(need)] if os.path.exists(idx_path) else []))
        if os.path.exists(idx_path) and new_ids:
            # 부분 생성 시 _index.json 이 덮어써지므로 기존 색인과 합친다
            pass
    cmd = [py, '-I', os.path.join(HERE, 'load_reg_history.py'), '--data', data, '--reports-dir', reports, '--base-url', a.base_url,
           '--author-id', a.author_id, '--author-name', a.author_name]
    for o in a.doc_override:
        cmd += ['--doc-override', o]
    if a.dry_run:
        cmd.append('--dry-run')
    run(cmd)
    print(f'동기화 완료: 신규 {len(new_ids)}건 (since {since})', file=sys.stderr)


if __name__ == '__main__':
    main()
