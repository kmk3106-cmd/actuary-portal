#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
규정 개정이력 야간 점검 결과 적용 — 주제 묶음(config/reg_topic_groups.json) · 관련성(config/reg_relevance.json overrides) 을
포탈 reg_items 에 반영한다 (docs/REG_NIGHTLY_REVIEW.md 절차의 "적용" 단계).

  python scripts/apply_reg_review.py --base-url https://portal.kkuks.com --groups --relevance [--dry-run]

  --groups     : 묶음 파일의 event_ids 를 topic_group_no / topic_group_label / topic_group_source='reviewed' 로.
                 파일에 없는데 'reviewed' 로 남아 있는 건은 지운다 (묶음에서 빠진 것).
  --relevance  : overrides 의 relevance·reason 을 반영. 담당자가 화면에서 확정한 건(relevance_manual) 은 건드리지 않는다.
설정 파일이 SSOT 이고 이 스크립트는 "그대로 옮기는" 역할만 한다 (규칙 11). 재적재(load_reg_history.py) 도 같은 파일을 읽는다.
"""
import argparse
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from publish_regulation import api  # noqa: E402

REG_TABLE = 'reg_items'
DEFAULT_GROUPS = os.path.join(ROOT, 'config', 'reg_topic_groups.json')
DEFAULT_RELEVANCE = os.path.join(ROOT, 'config', 'reg_relevance.json')
SOURCE_REVIEWED = 'reviewed'


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def get_all(base, table):
    st, body = api(base, 'GET', f'/tables/{table}?limit=5000')
    if st != 200:
        raise SystemExit(f'{table} 조회 실패 {st}: {body}')
    return body.get('rows') or body.get('data') or []


def group_fields(cfg):
    """event_id → {'topic_group_no','topic_group_label','topic_group_source'}. 번호 중복·이벤트 중복은 오류."""
    out, seen_no = {}, set()
    for g in cfg.get('groups', []):
        no = int(g['no'])
        if no in seen_no:
            raise SystemExit(f'묶음 번호 중복: {no}')
        seen_no.add(no)
        for ev in g.get('event_ids', []):
            if ev in out:
                raise SystemExit(f'이벤트가 두 묶음에 들어 있음: {ev} ({out[ev]["topic_group_no"]} · {no})')
            out[ev] = {'topic_group_no': no, 'topic_group_label': g.get('label', ''), 'topic_group_source': SOURCE_REVIEWED}
    return out


def apply_groups(base, rows, cfg, actor, dry):
    want = group_fields(cfg)
    known = {r.get('event_id') for r in rows if r.get('event_id')}
    missing = [ev for ev in want if ev not in known]
    if missing:
        print(f'  ! 포탈에 없는 이벤트 {len(missing)}건은 건너뜀: {", ".join(missing[:8])}{" …" if len(missing) > 8 else ""}', file=sys.stderr)
    n_set = n_clear = 0
    for r in rows:
        ev = r.get('event_id')
        cur = {k: r.get(k) for k in ('topic_group_no', 'topic_group_label', 'topic_group_source')}
        if ev in want:
            if cur == want[ev]:
                continue
            patch = want[ev]; n_set += 1
        elif cur.get('topic_group_source') == SOURCE_REVIEWED:
            patch = {'topic_group_no': None, 'topic_group_label': '', 'topic_group_source': ''}; n_clear += 1
        else:
            continue
        print(f'  {"[dry] " if dry else ""}{ev or r["id"]}: 묶음 {cur.get("topic_group_no")} → {patch["topic_group_no"]} {patch.get("topic_group_label") or ""}')
        if not dry:
            st, body = api(base, 'PATCH', f'/tables/{REG_TABLE}/{urllib.parse.quote(r["id"])}', patch, actor)
            if st != 200:
                raise SystemExit(f'PATCH 실패 {st}: {body}')
    return n_set, n_clear


def apply_relevance(base, rows, cfg, actor, dry):
    ov = cfg.get('overrides', {})
    n = skipped = 0
    for r in rows:
        ev = r.get('event_id')
        if ev not in ov:
            continue
        want = {'relevance': ov[ev].get('relevance', ''), 'relevance_reason': ov[ev].get('reason', '')}
        if r.get('relevance') == want['relevance'] and (r.get('relevance_reason') or '') == want['relevance_reason']:
            continue
        if r.get('relevance_manual'):
            skipped += 1
            print(f'  - {ev}: 담당자 확정(relevance_manual) 이라 유지 ({r.get("relevance")} ≠ 설정 {want["relevance"]})')
            continue
        n += 1
        print(f'  {"[dry] " if dry else ""}{ev}: 관련성 {r.get("relevance")} → {want["relevance"]} ({want["relevance_reason"][:40]})')
        if not dry:
            st, body = api(base, 'PATCH', f'/tables/{REG_TABLE}/{urllib.parse.quote(r["id"])}', want, actor)
            if st != 200:
                raise SystemExit(f'PATCH 실패 {st}: {body}')
    return n, skipped


def main():
    ap = argparse.ArgumentParser(description='야간 점검 결과(묶음·관련성)를 포탈 reg_items 에 반영')
    ap.add_argument('--base-url', required=True)
    ap.add_argument('--groups', action='store_true', help='config/reg_topic_groups.json 반영')
    ap.add_argument('--relevance', action='store_true', help='config/reg_relevance.json overrides 반영')
    ap.add_argument('--groups-file', default=DEFAULT_GROUPS)
    ap.add_argument('--relevance-file', default=DEFAULT_RELEVANCE)
    ap.add_argument('--author-id', default='')
    ap.add_argument('--author-name', default='야간점검')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if not (a.groups or a.relevance):
        ap.error('--groups 또는 --relevance 중 하나 이상')
    actor = {'id': a.author_id, 'name': a.author_name, 'role': 'team_leader'}
    rows = get_all(a.base_url, REG_TABLE)
    print(f'reg_items {len(rows)}건 ({a.base_url})')
    if a.groups:
        s, c = apply_groups(a.base_url, rows, load_json(a.groups_file), actor, a.dry_run)
        print(f'묶음: 반영 {s} · 해제 {c}')
    if a.relevance:
        n, sk = apply_relevance(a.base_url, rows, load_json(a.relevance_file), actor, a.dry_run)
        print(f'관련성: 반영 {n} · 담당자 확정 유지 {sk}')
    # 반영 뒤 재조회로 영속 확인 (규칙 18)
    if not a.dry_run and a.groups:
        after = {r.get('event_id'): r for r in get_all(a.base_url, REG_TABLE)}
        want = group_fields(load_json(a.groups_file))
        bad = [ev for ev, f in want.items() if ev in after and after[ev].get('topic_group_no') != f['topic_group_no']]
        if bad:
            raise SystemExit(f'재조회 불일치 {len(bad)}건: {bad[:5]}')
        print('재조회 확인: 묶음 번호 일치')


if __name__ == '__main__':
    main()
