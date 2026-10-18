#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
신구조문 대비 리포트(HTML) 를 포탈 계리업무절차서 › 규정·기준 에 등록하고,
선택적으로 규정 개정이력(reg_items) 건까지 만들어 연결한다.

  - 임베드 규칙은 js/report-embed.js 의 wrapForPortal() 과 동일 (한 줄 iframe srcdoc, 규칙 11 SSOT)
  - 서버의 기존 generic /tables API 만 사용 (새 엔드포인트 없음)

사용 예
  python scripts/publish_regulation.py --html samples/계리가정_세칙개정_대비_포탈용.html \
      --base-url https://portal.kkuks.com --author-id u_teamleader1 --author-name 김민국
  python scripts/publish_regulation.py --html report.html --meta meta.json --base-url http://127.0.0.1:8888
  python scripts/publish_regulation.py --meta meta.json --report-doc-id kb__xxxx --base-url ...   # 리포트는 이미 등록된 경우

meta.json 은 docs/02_규정개정이력_구축지시서.md §4-1 의 reg_items 필드(JSON) 그대로.
"""
import argparse
import json
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
from html import unescape

KB_TABLE = 'kb_documents'
REG_TABLE = 'reg_items'
DEFAULT_CATEGORY = 'kbc_regulation'
DEFAULT_HEIGHT_PX = 1400


def wrap_for_portal(html: str, height_px: int = DEFAULT_HEIGHT_PX) -> str:
    """js/report-embed.js wrapForPortal 과 동일 규칙."""
    esc = (html.replace('\r', '')
               .replace('&', '&amp;')
               .replace('"', '&quot;')
               .replace('\n', '&#10;'))
    return ('<div class="report-embed" style="margin:0;"><iframe srcdoc="%s" '
            'style="width:100%%;height:%dpx;border:0;display:block;" '
            'sandbox="allow-same-origin" loading="lazy" title="report"></iframe></div>' % (esc, height_px))


def extract_title(html: str) -> str:
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I)
    if m and m.group(1).strip():
        return re.sub(r'\s+', ' ', unescape(m.group(1))).strip()
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S | re.I)
    if m:
        return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', '', m.group(1)))).strip()
    return ''


def api(base: str, method: str, path: str, body=None, actor=None):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    req = urllib.request.Request(base.rstrip('/') + path, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    if actor:
        req.add_header('X-Actor-User', actor.get('id', ''))
        req.add_header('X-Actor-Username', urllib.parse.quote(actor.get('name', '')))   # 헤더는 latin-1 → 한글은 URL 인코딩 (portal.js 와 동일)
        req.add_header('X-Actor-Role', actor.get('role', 'team_leader'))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode('utf-8') or 'null')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8') or 'null')


def main():
    p = argparse.ArgumentParser(description='리포트 HTML → 포탈 규정·기준 등록 (+ reg_items 연결)')
    p.add_argument('--base-url', required=True, help='포탈 주소 예: https://portal.kkuks.com')
    p.add_argument('--html', help='리포트 HTML 파일 경로 (생략 시 --report-doc-id 필요)')
    p.add_argument('--title', help='문서 제목 (기본: HTML <title>)')
    p.add_argument('--category', default=DEFAULT_CATEGORY, help='kb_categories.id (기본 kbc_regulation)')
    p.add_argument('--height', type=int, default=DEFAULT_HEIGHT_PX, help='iframe 최소 높이 px')
    p.add_argument('--author-id', default='', help='kb_documents.author_id')
    p.add_argument('--author-name', default='', help='kb_documents.author_name / reg_items.created_by')
    p.add_argument('--draft', action='store_true', help='is_published=false 로 등록')
    p.add_argument('--meta', help='reg_items 필드 JSON 파일 (등록하면 report_doc_id 를 자동 연결)')
    p.add_argument('--report-doc-id', default='', help='이미 등록된 kb_documents.id (HTML 생략 시)')
    p.add_argument('--dry-run', action='store_true', help='서버에 보내지 않고 payload 만 출력')
    a = p.parse_args()

    if not a.html and not a.meta:
        p.error('--html 또는 --meta 중 하나는 필요합니다')

    actor = {'id': a.author_id, 'name': a.author_name, 'role': 'team_leader'}
    doc_id = a.report_doc_id

    if a.html:
        with open(a.html, encoding='utf-8') as f:
            html = f.read()
        if re.search(r'<script[\s>]', html, re.I):
            print('[경고] HTML 에 <script> 가 있습니다. 리포트는 스크립트 없이 만들어야 합니다 (스타일가이드 §5-2)', file=sys.stderr)
        title = a.title or extract_title(html) or a.html
        doc = {
            'category_id': a.category, 'title': title,
            'content': wrap_for_portal(html, a.height),
            'is_published': not a.draft,
            'author_id': a.author_id, 'author_name': a.author_name,
        }
        print(f'[kb_documents] title="{title}" content={len(doc["content"]):,}B category={a.category}')
        if a.dry_run:
            print(json.dumps({k: (v if k != 'content' else v[:200] + '…') for k, v in doc.items()}, ensure_ascii=False, indent=2))
        else:
            st, body = api(a.base_url, 'POST', f'/tables/{KB_TABLE}', doc, actor)
            if st not in (200, 201):
                print(f'[실패] kb_documents POST {st}: {body}', file=sys.stderr); sys.exit(2)
            doc_id = body['id']
            print(f'[완료] kb_documents id={doc_id}  → {a.base_url.rstrip("/")}/kb-sop.html?doc={doc_id}')

    if a.meta:
        with open(a.meta, encoding='utf-8') as f:
            meta = json.load(f)
        if doc_id:
            meta['report_doc_id'] = doc_id
        meta.setdefault('created_by', a.author_name)
        meta.setdefault('updated_by', a.author_name)
        for k in ('title', 'reg_type', 'reg_name', 'status'):
            if not meta.get(k):
                print(f'[실패] meta 필수 필드 누락: {k}', file=sys.stderr); sys.exit(3)
        print(f'[reg_items] title="{meta["title"]}" status={meta["status"]} report_doc_id={meta.get("report_doc_id")}')
        if a.dry_run:
            print(json.dumps(meta, ensure_ascii=False, indent=2))
        else:
            st, body = api(a.base_url, 'POST', f'/tables/{REG_TABLE}', meta, actor)
            if st not in (200, 201):
                print(f'[실패] reg_items POST {st}: {body}', file=sys.stderr)
                if st == 404:
                    print('       서버가 reg_items 테이블을 모릅니다 → 서버 재시작(update-now.bat) 후 다시 실행', file=sys.stderr)
                sys.exit(4)
            print(f'[완료] reg_items id={body["id"]}  → {a.base_url.rstrip("/")}/reg-history.html?item={body["id"]}')


if __name__ == '__main__':
    main()
