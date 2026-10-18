#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
규정 개정 이벤트 + 생성 리포트 → 포탈 적재 (멱등)
  - kb_documents (계리업무절차서 › 규정·기준) 에 리포트 HTML 을 iframe 임베드로 등록
  - reg_items (규정 개정이력) 에 건 등록 + report_doc_id 연결 + 첨부(원문 파일) 업로드
  - 같은 이벤트(source_key = 원문 URL) 가 이미 있으면 건너뛴다 (--update 면 갱신)

  python scripts/load_reg_history.py --data data/reg_history.json --reports-dir reports/output/reg \
      --base-url https://portal.kkuks.com --author-id u_xxx --author-name 김민국 \
      --doc-override fss_prv_4225=kb__2d3b36e5e48a183e
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish_regulation import api, wrap_for_portal  # noqa: E402  (같은 임베드 규칙 재사용)

KB_TABLE, REG_TABLE, KB_CATEGORY = 'kb_documents', 'reg_items', 'kbc_regulation'
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
UPLOAD_EXTS = ('.hwpx', '.hwp', '.pdf', '.xlsx', '.docx', '.zip')
STATUS_PREFIX = {'사전예고': '[사전예고]', '입법예고': '[규정변경예고]', '공포': '[고시]', '시행': '[개정]', '보도자료': '[보도자료]'}
RELEVANCE_TAG = {'관련': '', '참고': '[참고]', '무관': '[팀무관]'}   # 문서 제목에 붙는 관련성 표기 (관련은 표기 없음)


def short_reg_name(name):
    """'은행업감독업무시행세칙, 금융투자업규정시행세칙, 보험업감독업무시행세칙, …' 같은 복수 규정 건은 보험 규정 + 외 N개 로 줄인다"""
    parts = [p.strip() for p in (name or '').split(',') if p.strip()]
    if len(parts) <= 1:
        return name
    ins = next((p for p in parts if '보험' in p), parts[0])
    return f'{ins} 외 {len(parts) - 1}개'


def get_all(base, table):
    st, body = api(base, 'GET', f'/tables/{table}?limit=5000')
    if st != 200:
        raise SystemExit(f'{table} 조회 실패 {st}: {body}')
    return body.get('rows') or body.get('data') or []


def upload(base, path, actor):
    name = os.path.basename(path)
    if os.path.splitext(name)[1].lower() not in UPLOAD_EXTS or os.path.getsize(path) > MAX_UPLOAD_BYTES:
        return None
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    st, body = api(base, 'POST', '/api/kb/upload', {'filename': name, 'content': b64, 'context': 'reg'}, actor)
    return body if st == 200 else None


def main():
    ap = argparse.ArgumentParser(description='규정 개정 이벤트 → 포탈 적재')
    ap.add_argument('--data', required=True)
    ap.add_argument('--reports-dir', required=True, help='make_reg_report.py 출력 폴더 (_index.json 포함)')
    ap.add_argument('--base-url', required=True)
    ap.add_argument('--author-id', default='')
    ap.add_argument('--author-name', default='자동수집')
    ap.add_argument('--doc-override', action='append', default=[], help='이벤트id=kb문서id (손으로 만든 리포트를 대신 연결)')
    ap.add_argument('--ids', default='', help='특정 이벤트만 (쉼표)')
    ap.add_argument('--update', action='store_true', help='이미 있는 건도 리포트·필드를 갱신')
    ap.add_argument('--no-attachments', action='store_true', help='원문 파일 업로드 생략')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    events = json.load(open(a.data, encoding='utf-8'))
    index = json.load(open(os.path.join(a.reports_dir, '_index.json'), encoding='utf-8'))
    overrides = dict(x.split('=', 1) for x in a.doc_override)
    want = set(x.strip() for x in a.ids.split(',') if x.strip())
    actor = {'id': a.author_id, 'name': a.author_name, 'role': 'team_leader'}

    existing = {it.get('source_key'): it for it in get_all(a.base_url, REG_TABLE) if it.get('source_key')}
    docs_by_title = {d.get('title'): d for d in get_all(a.base_url, KB_TABLE) if d.get('category_id') == KB_CATEGORY}
    by_id = {e['id']: e for e in events}
    created = updated = skipped = merged = 0
    # 공동 보도자료에 통합된 건(merged_into)은 대표 건 뒤에 처리해야 대표 건의 id 를 알 수 있다
    for ev in sorted(events, key=lambda e: 1 if (index.get(e['id']) or {}).get('merged_into') else 0):
        if want and ev['id'] not in want:
            continue
        meta = index.get(ev['id'])
        if not meta:
            print(f'  - {ev["id"]} 리포트 없음 (건너뜀)', file=sys.stderr); continue
        key = ev['url']
        exists = existing.get(key)
        # 금융위·금감원 공동 보도자료의 부(副) 건: 새로 만들지 않고, 이미 있으면 "통합됨" 표시만 (삭제 아님)
        if meta.get('merged_into'):
            primary_ev = by_id.get(meta['merged_into'])
            primary_item = existing.get(primary_ev['url']) if primary_ev else None
            if exists and primary_item and not a.dry_run and exists.get('merged_into') != primary_item['id']:
                api(a.base_url, 'PATCH', f'/tables/{REG_TABLE}/{urllib.parse.quote(exists["id"])}',
                    {'merged_into': primary_item['id'], 'merged_into_event_id': primary_ev['id'], 'is_duplicate': True, 'updated_by': a.author_name}, actor)
                if exists.get('report_doc_id'):
                    api(a.base_url, 'PATCH', f'/tables/{KB_TABLE}/{urllib.parse.quote(exists["report_doc_id"])}',
                        {'title': '[중복·통합] ' + re.sub(r'^\[중복·통합\]\s*', '', (next((d['title'] for d in docs_by_title.values() if d.get('id') == exists['report_doc_id']), '') or exists.get('title', ''))),
                         'change_note': f'공동 보도자료 — {primary_item.get("title", "")} 에 통합'}, actor)
                merged += 1
                print(f'  ~ {ev["id"]} → {primary_ev["id"]} 에 통합 표시', file=sys.stderr)
            elif a.dry_run:
                print(f'  [dry] {ev["id"]} 공동 보도자료 → {meta["merged_into"]} 에 통합 (별도 등록 안 함)')
            continue
        if exists and not a.update:
            skipped += 1; continue

        # 제목은 날짜 → 단계 → 규정명 → 요지 순 (목록에서 날짜가 먼저 보이도록)
        rel_tag = RELEVANCE_TAG.get(meta.get('relevance', ''), '')
        st_tag = STATUS_PREFIX.get(ev['status'], '')
        if ev['status'] == '보도자료':   # 금융위·금감원이 같은 날 같은 제목으로 내는 공동 보도자료를 구분
            st_tag = '[보도자료·' + ('금융위' if '금융위' in (ev.get('authority') or '') else '금감원') + ']'
        # 제목: 담당자가 확정한 제목(title_manual) > 자동 생성 '대상 + 실질 변경' (docs/03 P0-5)
        manual = bool(exists and exists.get('title_manual') and exists.get('title'))
        list_title = exists['title'] if manual else (meta.get('list_title') or meta['title'].split(' — ')[-1])[:80]
        doc_title = f"{(ev.get('date') or '').replace('-', '.')} {st_tag}{rel_tag} {short_reg_name(ev['reg_name'])} · {list_title[:70]}".strip()
        doc_id = overrides.get(ev['id']) or (exists or {}).get('report_doc_id') or ''
        if not doc_id and doc_title in docs_by_title:
            doc_id = docs_by_title[doc_title]['id']
        if a.dry_run:
            print(f'  [dry] {ev["id"]} {ev.get("date")} {ev["status"]} doc={"override" if ev["id"] in overrides else (doc_id or "NEW")} title="{doc_title}"')
            continue

        # 1) 리포트 문서
        if ev['id'] not in overrides:
            html_str = open(meta['file'], encoding='utf-8').read()
            doc_body = {'category_id': KB_CATEGORY, 'title': doc_title, 'content': wrap_for_portal(html_str),
                        'is_published': True, 'author_id': a.author_id, 'author_name': a.author_name,
                        'doc_date': ev.get('date') or ''}   # 목록 정렬·표시용 (게시물 일자)
            if doc_id:
                if a.update:
                    api(a.base_url, 'PATCH', f'/tables/{KB_TABLE}/{urllib.parse.quote(doc_id)}', {**doc_body, 'change_note': '자동 재생성'}, actor)
            else:
                st, body = api(a.base_url, 'POST', f'/tables/{KB_TABLE}', doc_body, actor)
                if st not in (200, 201):
                    print(f'  ! {ev["id"]} kb_documents 실패 {st}: {body}', file=sys.stderr); continue
                doc_id = body['id']; docs_by_title[doc_title] = body

        # 2) 첨부 업로드 (원문 파일)
        atts = (exists or {}).get('attachments') or []
        if not a.no_attachments and not atts:
            for att in ev.get('attachments', []):
                if att.get('local') and os.path.exists(att['local']):
                    up = upload(a.base_url, att['local'], actor)
                    if up:
                        up['source_url'] = att['url']; atts.append(up)

        # 3) reg_items
        is_notice = ev['status'] in ('사전예고', '입법예고')
        eff = ev.get('date_effective') or meta.get('date_effective') or None
        # 선행 예고 연결: 자동 신뢰도(high/medium/low) + 근거. 담당자가 [연결 확인]/[연결 해제] 한 상태는 보존한다 (docs/03 P0-3)
        kept = {r.get('related_event_id'): r for r in ((exists or {}).get('relationships') or []) if r.get('state') in ('confirmed', 'rejected')}
        rels = []
        rid = meta.get('related_notice_id') or ev.get('related_notice_id')
        if rid:
            r = {'related_event_id': rid, 'type': 'notice_of', 'confidence': meta.get('related_confidence') or 'low',
                 'evidence': meta.get('related_evidence') or '', 'state': 'auto'}
            if rid in kept:
                r.update({k: kept[rid][k] for k in ('state', 'reviewed_by', 'reviewed_at') if k in kept[rid]})
            rels.append(r)
        rels += [r0 for k, r0 in kept.items() if k != rid]
        item = {
            'relationships': rels,
            # 예고안에서 긁은 시행일은 '예정' 이다 — 확정 시행일 칸에 넣지 않는다 (docs/03 P0-2)
            'date_effective_planned': eff if is_notice else None,
            'date_effective_source': '' if is_notice or not eff else (ev.get('date_effective_source') or '발령문 본문 추출'),
            'date_effective_rule': meta.get('date_effective_rule') or '',   # 날짜 대신 조건('공포한 날부터 시행')으로 정한 예고안
            'date_effective_notes': ev.get('date_effective_notes') or meta.get('date_effective_notes') or '', 'supplement_text': (ev.get('supplement') or meta.get('supplement') or '')[:800],
            'title': list_title,
            'summary_line': (exists.get('summary_line') if (exists and exists.get('summary_manual')) else meta.get('summary_line', '')) or '',
            'title_source': 'manual' if manual else meta.get('title_source', ''), 'title_quality': meta.get('title_quality', ''),
            'reg_type': ev['reg_type'], 'reg_name': ev['reg_name'], 'articles': meta['articles'][:8], 'status': ev['status'],
            'date_notice': ev.get('date_notice') or None, 'date_comment_due': ev.get('date_comment_due') or None,
            'date_promulgated': ev.get('date_promulgated') or None,
            # 시행일은 리포트 생성기가 본문("YYYY.MM.DD부터 시행")에서 찾은 값이 더 많다 (확정 건만)
            'date_effective': None if is_notice else eff,
            'date_press': ev.get('date_press') or None,
            'authority': ev.get('authority', ''), 'summary': meta['summary'],
            'change_new': meta['change_new'], 'change_mod': meta['change_mod'], 'change_del': meta['change_del'], 'change_move': meta.get('change_move', 0),
            'line_counts': meta.get('line_counts') or {},
            'impact_level': '미정' if ev['status'] == '보도자료' else '대' if meta['compare_rows'] >= 15 or any(k in ' '.join(meta['impact_areas']) for k in ('해약률', '위험률', '책임준비금', '지급여력')) else ('중' if meta['compare_rows'] else '미정'),
            'impact_areas': meta['impact_areas'], 'impact_systems': meta['impact_systems'],
            'actions': (exists or {}).get('actions') or meta['actions'],
            'report_doc_id': doc_id or None,
            'sources': [{'label': ev['source_label'], 'url': ev['url'], 'fetched_at': 0}]
                       + [{'label': j['label'] + ' (공동 배포)', 'url': j['url'], 'fetched_at': 0, 'joint': True} for j in (meta.get('joint_sources') or [])],
            'joint_event_ids': [j['event_id'] for j in (meta.get('joint_sources') or [])],
            'analysis_kind': meta.get('analysis_kind', ''), 'legal_status': meta.get('legal_status', ''),
            'attachments': atts, 'tags': meta['tags'][:8],
            # event_id = 수집 이벤트 id. related_notice_id 도 이벤트 id 라서 화면은 event_id 로 선행 예고를 찾는다
            'source_key': key, 'source': ev['source'], 'event_id': ev['id'], 'related_notice_id': meta.get('related_notice_id') or ev.get('related_notice_id'),
            'relevance': meta.get('relevance', ''), 'relevance_reason': meta.get('relevance_reason', ''),
            # 화면에서 담당자가 바꾼 관련성(relevance_manual) 은 자동 갱신으로 덮어쓰지 않는다
            **({'relevance': exists['relevance'], 'relevance_reason': exists.get('relevance_reason', '')} if exists and exists.get('relevance_manual') else {}),
            'gazette_no': ev.get('gazette_no', ''), 'notice_kind': ev.get('notice_kind', ''),
            'updated_by': a.author_name, 'auto_collected': True,
        }
        if exists:
            st, body = api(a.base_url, 'PATCH', f'/tables/{REG_TABLE}/{urllib.parse.quote(exists["id"])}', item, actor)
            updated += 1 if st == 200 else 0
        else:
            item['created_by'] = a.author_name
            st, body = api(a.base_url, 'POST', f'/tables/{REG_TABLE}', item, actor)
            if st not in (200, 201):
                print(f'  ! {ev["id"]} reg_items 실패 {st}: {body}', file=sys.stderr); continue
            existing[key] = body; created += 1
        print(f'  + {ev["id"]} {ev.get("date")} {ev["status"]} doc={doc_id} atts={len(atts)}', file=sys.stderr)
    print(f'완료: 생성 {created} · 갱신 {updated} · 건너뜀 {skipped} · 공동 보도자료 통합 표시 {merged}', file=sys.stderr)


if __name__ == '__main__':
    main()
