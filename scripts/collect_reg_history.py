#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
규정 개정이력 자동 수집기 — 금감원·금융위 공개 게시판에서 보험 규정 개정 이벤트를 모아 JSON 으로 만든다.

수집원 (목록 → 상세 → 첨부 다운로드 → hwpx 본문/표 추출)
  fss_prv   금감원 세칙 제·개정 예고 (사전예고)          보험업감독업무시행세칙
  fss_info  금감원 최근 제개정 정보 (확정 개정·시행)      보험업감독업무시행세칙
  fsc_ntc   금융위 입법예고/규정변경예고                 보험업감독규정
  fsc_gosi  금융위 소관규정/고시 (확정 고시)             보험업감독규정

사용
  python scripts/collect_reg_history.py --since 2023-01-01 --out data/reg_history.json --files-dir data/reg_files
  python scripts/collect_reg_history.py --since 2026-06-01 --out tmp/t.json --files-dir tmp/f --sources fss_prv --limit 2

주의: 공개 게시판을 읽기만 한다. 요청 간격(--delay) 을 두고, 하루 1회 수준으로만 돌린다.
"""
import argparse
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
import struct
import xml.etree.ElementTree as ET
try:
    import olefile          # .hwp(5.0 바이너리) 본문 추출용 — 없으면 hwpx 만 추출
except ImportError:         # pragma: no cover
    olefile = None

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 ActuaryPortal-RegCollector'
DEFAULT_DELAY = 1.0
TIMEOUT = 60
RETRIES = 3
MAX_FILES_PER_EVENT = 12
# 본문·표 추출이 되는 한글 파일과 별지 서식(xlsx)만 받는다. pdf 는 같은 내용의 사본이라 원문 링크로 대신한다 (수집 시간 ½).
DOWNLOAD_EXTS = ('.hwpx', '.hwp', '.xlsx')

FSS = 'https://www.fss.or.kr'
FSC = 'https://www.fsc.go.kr'
SOURCES = {
    'fss_prv': {
        'label': '금융감독원 세칙 제·개정 예고', 'kind': 'fss_list',
        'list': FSS + '/fss/job/lrgRegItnPrvntc/list.do', 'menu': '200489',
        'query': '보험업감독업무시행세칙', 'reg_name': '보험업감독업무시행세칙', 'reg_type': '시행세칙', 'status': '사전예고',
        'authority': '금융감독원',
    },
    'fss_info': {
        'label': '금융감독원 최근 제개정 정보', 'kind': 'fss_list',
        'list': FSS + '/fss/job/lrgRegItnInfo/list.do', 'menu': '200488',
        'query': '보험업감독업무시행세칙', 'reg_name': '보험업감독업무시행세칙', 'reg_type': '시행세칙', 'status': '시행',
        'authority': '금융감독원',
    },
    'fsc_ntc': {
        'label': '금융위원회 입법예고/규정변경예고', 'kind': 'fsc_list',
        'list': FSC + '/po040301', 'query': '보험업감독규정', 'reg_name': '보험업감독규정', 'reg_type': '감독규정', 'status': '입법예고',
        'authority': '금융위원회',
    },
    'fsc_ntc_law': {   # 보험업법·시행령·시행규칙 입법예고 (금융위 소관) — 규정명·구분은 제목에서 판별
        'label': '금융위원회 입법예고 (보험업법·시행령·시행규칙)', 'kind': 'fsc_list',
        'list': FSC + '/po040301', 'query': '보험업법', 'reg_name': '보험업법', 'reg_type': '법률', 'status': '입법예고',
        'authority': '금융위원회',
    },
    'fsc_gosi': {
        'label': '금융위원회 소관규정/고시', 'kind': 'fsc_list',
        'list': FSC + '/po040200', 'query': '보험업감독규정', 'reg_name': '보험업감독규정', 'reg_type': '감독규정', 'status': '공포',
        'authority': '금융위원회',
    },
}
HP_NS = 'http://www.hancom.co.kr/hwpml/2011/paragraph'


# ── HTTP ─────────────────────────────────────────────────────────────
def _ctx():
    cafile = os.environ.get('SSL_CERT_FILE')
    return ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()


def fetch(url, delay=DEFAULT_DELAY):
    last = None
    for i in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx()) as r:
                data = r.read()
                time.sleep(delay)
                return data, dict(r.headers)
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f'fetch 실패 {url}: {last}')


def text_of(fragment):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', fragment))).strip()


def encode_href(href, base):
    """FSS 다운로드 링크는 쿼리값에 공백·한글이 날것으로 들어 있어 값만 인코딩한다."""
    href = html.unescape(href)
    if '?' not in href:
        return urllib.parse.urljoin(base, href)
    path, qs = href.split('?', 1)
    parts = []
    for kv in qs.split('&'):
        k, _, v = kv.partition('=')
        parts.append(k + '=' + urllib.parse.quote(v, safe='/'))
    return urllib.parse.urljoin(base, path + '?' + '&'.join(parts))


def norm_date(s):
    m = re.search(r'(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})', s or '')
    return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else ''


# ── 금감원 목록/상세 ────────────────────────────────────────────────────
def fss_list(src, since, delay, limit):
    out, seen = [], set()
    for page in range(1, 30):
        q = urllib.parse.urlencode({'menuNo': src['menu'], 'searchCnd': '1', 'searchWrd': src['query'],
                                    'sdate': since, 'edate': '2099-12-31', 'pageIndex': page})
        body, _ = fetch(src['list'] + '?' + q, delay)
        s = body.decode('utf-8', 'replace')
        rows = 0
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s, re.S):
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
            if len(tds) < 3:
                continue
            no, title, date = text_of(tds[0]), text_of(tds[1]), norm_date(text_of(tds[2]))
            link = re.search(r'href="([^"]+)"', tr)
            if not link or no in seen:
                continue
            seen.add(no); rows += 1
            if date and date < since:
                continue
            if '보험업감독' not in title and '보험업' not in title:
                continue
            out.append({'no': no, 'title': title, 'date': date, 'url': urllib.parse.urljoin(FSS, html.unescape(link.group(1)))})
            if limit and len(out) >= limit:
                return out
        if rows == 0:
            break
    return out


def fss_detail(url, delay):
    body, _ = fetch(url, delay)
    s = body.decode('utf-8', 'replace')
    fields = {}
    for dt, dd in re.findall(r'<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>', s, re.S):
        k = text_of(dt)
        if len(k) > 40 or '민원' in k or '분쟁' in k or '신고' in k or '지킴이' in k or '인허가' in k:
            continue
        fields[k] = text_of(dd)
    atts, seen = [], set()
    for href, label in re.findall(r'<a[^>]*href="(/fss\.hpdownload\?[^"]+)"[^>]*>(.*?)</a>', s, re.S):
        u = encode_href(href, FSS)
        if u in seen:
            continue
        seen.add(u)
        name = text_of(label)
        if not name or name == '다운로드':
            m = re.search(r'file=([^&]+)', html.unescape(href))
            name = os.path.basename(m.group(1)) if m else 'attachment'
        atts.append({'name': name, 'url': u})
    return fields, atts


# ── 금융위 목록/상세 ────────────────────────────────────────────────────
def fsc_list(src, since, delay, limit):
    out, seen = [], set()
    for page in range(1, 30):
        q = urllib.parse.urlencode({'srchKey': 'sj', 'srchText': src['query'], 'curPage': page})
        body, _ = fetch(src['list'] + '?' + q, delay)
        s = body.decode('utf-8', 'replace')
        lis = [li for li in re.findall(r'<li[^>]*>\s*(<div class="inner">.*?)</li>', s, re.S)]
        rows = 0
        stop = False
        for li in lis:
            sub = re.search(r'<div class="subject">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', li, re.S)
            if not sub:
                continue
            href, title = html.unescape(sub.group(1)), text_of(sub.group(2))
            # 예고 게시판은 './po040301/view?noticeId=NNN&…' 라 경로만으로는 전부 같은 키가 된다 → 첫 파라미터(noticeId)까지 포함
            key = href.split('&')[0]
            if key in seen:
                continue
            seen.add(key); rows += 1
            if src['query'] not in title.replace(' ', ''):
                continue
            info = text_of(re.search(r'<div class="info">(.*?)</div>', li, re.S).group(1)) if '<div class="info">' in li else ''
            period = re.search(r'예고기간\s*:\s*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})', info)
            files = fsc_files(li)
            item = {'title': title, 'url': urllib.parse.urljoin(FSC, href), 'info': info, 'files': files,
                    'date': period.group(1) if period else '', 'date_comment_due': period.group(2) if period else ''}
            if item['date'] and item['date'] < since:
                stop = True
                continue
            out.append(item)
            if limit and len(out) >= limit:
                return out
        if rows == 0 or stop:
            break
    return out


def fsc_files(fragment):
    """금융위 게시판 첨부: <div class="file-list"><span class="name">이름 (크기)</span> … <a href="/comm/getFile?…" title="파일 다운로드">
    (이름 링크에 title 이 있는 게시판도 있어 둘 다 지원)"""
    files = []
    for block in re.findall(r'<div class="file-list">(.*?)</div>', fragment, re.S):
        href = re.search(r'href="(/comm/getFile\?[^"]+)"', block)
        if not href:
            continue
        u = urllib.parse.urljoin(FSC, html.unescape(href.group(1)))
        name = ''
        m = re.search(r'<span class="name">(.*?)</span>', block, re.S)
        if m:
            name = re.sub(r'\s*\([\d.,]+\s*[KMG]?B\)\s*$', '', text_of(m.group(1)))
        if not name or name in GENERIC_LABELS:
            t = re.search(r'<a[^>]*href="/comm/getFile[^"]*"[^>]*title="([^"]+)"', block)
            name = html.unescape(t.group(1)).strip() if t else ''
        if all(f['url'] != u for f in files):
            files.append({'name': name, 'url': u})
    if not files:   # 구형 마크업: <a href=getFile title=이름>
        for fh, ft in re.findall(r'<a[^>]*href="(/comm/getFile\?[^"]+)"[^>]*title="([^"]+)"', fragment):
            u = urllib.parse.urljoin(FSC, html.unescape(fh))
            if all(f['url'] != u for f in files):
                files.append({'name': html.unescape(ft).strip(), 'url': u})
    return merge_atts([], [(f['url'], f['name']) for f in files])


def fsc_detail(url, delay):
    body, _ = fetch(url, delay)
    s = body.decode('utf-8', 'replace')
    date = ''
    for m in re.findall(r'class="[^"]*\bdate\b[^"]*"[^>]*>(.*?)<', s, re.S):
        date = norm_date(m)
        if date:
            break
    if not date:
        date = norm_date(' '.join(re.findall(r'<span[^>]*>(\d{4}-\d{2}-\d{2})</span>', s)[:1]))
    bodies = re.findall(r'<div[^>]*class="body"[^>]*>(.*?)</div>\s*(?:</div>|<div class="file)', s, re.S)
    bodytext = max((text_of(b) for b in bodies), key=len, default='')
    if not bodytext:
        cands = re.findall(r'<div[^>]*class="[^"]*\b(?:body|cont|view)[^"]*"[^>]*>(.*?)</div>', s, re.S)
        bodytext = max((text_of(c) for c in cands), key=len, default='')
    dept = re.search(r'담당부서\s*[:：]?\s*</?[^>]*>?\s*([가-힣\w]+과)', s)
    atts = fsc_files(s)
    return {'date': date, 'body': bodytext, 'dept': dept.group(1) if dept else ''}, atts


GENERIC_LABELS = ('파일 다운로드', '파일다운로드', '다운로드', '파일뷰어', '')


def merge_atts(atts, pairs):
    """같은 URL 이 아이콘 링크('파일 다운로드')와 이름 링크로 두 번 나오므로, 의미 있는 이름을 우선한다."""
    by_url = {a['url']: a for a in atts}
    order = [a['url'] for a in atts]
    for u, name in pairs:
        name = (name or '').strip()
        if u not in by_url:
            by_url[u] = {'name': name, 'url': u}; order.append(u)
        elif by_url[u]['name'] in GENERIC_LABELS and name not in GENERIC_LABELS:
            by_url[u]['name'] = name
    out = []
    for u in order:
        a = by_url[u]
        if a['name'] in GENERIC_LABELS:
            m = re.search(r'(?:file|fileNo)=([^&]+)', html.unescape(u))
            a['name'] = os.path.basename(urllib.parse.unquote(m.group(1))) if m else 'attachment'
        out.append(a)
    return out


# ── 첨부 다운로드 + hwpx 추출 ────────────────────────────────────────────
def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|]', '_', name).strip()
    return name[:150] or 'file'


def download(att, dest_dir, delay):
    os.makedirs(dest_dir, exist_ok=True)
    name = safe_name(att['name'])
    ext = os.path.splitext(name)[1].lower()
    local = os.path.join(dest_dir, name)
    if not os.path.exists(local):
        data, headers = fetch(att['url'], delay)
        if not ext:
            cd = headers.get('Content-Disposition', '')
            m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
            if m:
                name = safe_name(urllib.parse.unquote(m.group(1)))
                ext = os.path.splitext(name)[1].lower()
                local = os.path.join(dest_dir, name)
        with open(local, 'wb') as f:
            f.write(data)
    att['local'] = local
    att['ext'] = ext
    att['size'] = os.path.getsize(local)
    return att


def hwpx_extract(path):
    """hwpx(zip) → {'paras': [문단...], 'tables': [[[cell,...],...], ...]} (문서 순서. 표 안 문단은 paras 에서 제외)"""
    z = zipfile.ZipFile(path)
    secs = sorted(n for n in z.namelist() if n.startswith('Contents/section'))
    paras, tables = [], []
    tag = lambda n: '{%s}%s' % (HP_NS, n)

    def ptext(p):
        return re.sub(r'\s+', ' ', ''.join(t.text or '' for t in p.iter(tag('t')) if t.text)).strip()

    def cell_text(tc):
        return '\n'.join(x for x in (ptext(p) for p in tc.iter(tag('p'))) if x)

    for n in secs:
        root = ET.fromstring(z.read(n))
        for p in list(root):
            if p.tag != tag('p'):
                continue
            tbls = list(p.iter(tag('tbl')))
            if tbls:
                for t in tbls:
                    rows = []
                    for tr in t.iter(tag('tr')):
                        rows.append([cell_text(tc) for tc in tr.iter(tag('tc'))])
                    if rows:
                        tables.append(rows)
                # 표 밖 텍스트(그림 캡션 등)는 버린다
            else:
                tx = ptext(p)
                if tx:
                    paras.append(tx)
    return {'paras': paras, 'tables': tables}


HWP_TAG_PARA_TEXT, HWP_TAG_CTRL_HEADER, HWP_TAG_LIST_HEADER, HWP_TAG_TABLE = 67, 71, 72, 77


def hwp5_extract(path):
    """.hwp(5.0, 비암호) → {'paras','tables'}. 레코드 level 로 표 셀을 복원한다 (병합 셀은 row/col 위치만 반영)."""
    if olefile is None:
        raise RuntimeError('olefile 미설치')
    o = olefile.OleFileIO(path)
    flags = struct.unpack('<I', o.openstream('FileHeader').read()[36:40])[0]
    if (flags >> 1) & 1:
        raise RuntimeError('암호화된 hwp')
    paras, tables = [], []

    def records(data):
        i = 0
        while i + 4 <= len(data):
            h = struct.unpack('<I', data[i:i + 4])[0]
            tag, level, size = h & 0x3ff, (h >> 10) & 0x3ff, (h >> 20) & 0xfff
            i += 4
            if size == 0xfff:
                size = struct.unpack('<I', data[i:i + 4])[0]; i += 4
            yield tag, level, data[i:i + size]
            i += size

    def para_text(body):
        # 문자 단위로 제어문자(코드 < 32) 제거. 확장 제어(1~23 일부) 는 8자(16바이트) 뒤따름
        s = body.decode('utf-16le', 'ignore')
        out, j = [], 0
        while j < len(s):
            c = ord(s[j])
            if c < 32:
                if c in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23):
                    j += 8
                else:
                    j += 1
                continue
            out.append(s[j]); j += 1
        return re.sub(r'\s+', ' ', ''.join(out)).strip()

    for st in o.listdir():
        if st[0] != 'BodyText':
            continue
        raw = o.openstream(st).read()
        data = zlib.decompress(raw, -15) if flags & 1 else raw
        stack = []   # [{level, rows, cols, cells:{(r,c):[text]}, cur:(r,c)}]
        for tag, level, body in records(data):
            # 표(77) 와 셀 머리(72) 는 같은 level, 셀 문단 텍스트는 +1. 더 낮은 level 이 오면 표가 끝난 것
            while stack and level < stack[-1]['level']:
                t = stack.pop()
                grid = [['' for _ in range(t['cols'])] for _ in range(t['rows'])]
                for (r, c), lines in t['cells'].items():
                    if r < t['rows'] and c < t['cols']:
                        grid[r][c] = '\n'.join(x for x in lines if x)
                if any(any(cell for cell in row) for row in grid):
                    (stack[-1]['cells'].setdefault(stack[-1]['cur'], []) if stack else tables).append(grid if not stack else ' / '.join(' | '.join(r) for r in grid))
            if tag == HWP_TAG_TABLE and len(body) >= 8:
                rows, cols = struct.unpack('<HH', body[4:8])
                stack.append({'level': level, 'rows': rows, 'cols': cols, 'cells': {}, 'cur': (0, 0)})
            elif tag == HWP_TAG_LIST_HEADER and stack and len(body) >= 14:
                col, row = struct.unpack('<HH', body[6:10])
                stack[-1]['cur'] = (row, col)
                stack[-1]['cells'].setdefault((row, col), [])
            elif tag == HWP_TAG_PARA_TEXT:
                tx = para_text(body)
                if not tx:
                    continue
                if stack:
                    stack[-1]['cells'].setdefault(stack[-1]['cur'], []).append(tx)
                else:
                    paras.append(tx)
        while stack:
            t = stack.pop()
            grid = [['' for _ in range(t['cols'])] for _ in range(t['rows'])]
            for (r, c), lines in t['cells'].items():
                if r < t['rows'] and c < t['cols']:
                    grid[r][c] = '\n'.join(x for x in lines if x)
            tables.append(grid)
    return {'paras': paras, 'tables': tables}


def link_related(events):
    """확정 개정(fss_info/fsc_gosi) 에 가장 가까운 선행 예고(같은 규정, 0~200일 전) 를 related_notice_id 로 연결"""
    notices = [e for e in events if e['status'] in ('사전예고', '입법예고')]
    for e in events:
        if e['status'] not in ('시행', '공포') or not e.get('date'):
            continue
        best = None
        for n in notices:
            if n['reg_name'] != e['reg_name'] or not n.get('date') or n['date'] > e['date']:
                continue
            gap = (int(e['date'].replace('-', '')) - int(n['date'].replace('-', '')))
            if 0 <= gap <= 200 and (best is None or gap < best[0]):
                best = (gap, n['id'])
        if best:
            e['related_notice_id'] = best[1]


# ── 이벤트 조립 ──────────────────────────────────────────────────────────
def build_fss_event(key, src, row, fields, atts):
    ev = {
        'id': f"{key}_{re.sub(r'[^0-9A-Za-z]', '', urllib.parse.parse_qs(urllib.parse.urlparse(row['url']).query).get('lrgSlno', urllib.parse.parse_qs(urllib.parse.urlparse(row['url']).query).get('lrgClsfcNo', ['x']))[0])[-12:]}",
        'source': key, 'source_label': src['label'], 'url': row['url'], 'list_title': row['title'],
        'reg_name': fields.get('1. 규정의 명칭', '') or src['reg_name'], 'reg_type': src['reg_type'], 'status': src['status'],
        'authority': src['authority'], 'date': row['date'],
    }
    if key == 'fss_prv':
        ev.update({
            'date_notice': row['date'],
            'date_comment_due': norm_date(next((v for k, v in fields.items() if '의견제출' in k), '')),
            'purpose': next((v for k, v in fields.items() if '취지' in k), ''),
            'content': next((v for k, v in fields.items() if '내용' in k and '제' in k), ''),
            'etc': next((v for k, v in fields.items() if '기타' in k), ''),
            'contact': next((v for k, v in fields.items() if '접수부서' in k or '담당' in k), ''),
        })
        dept = re.match(r'([가-힣]+국)\s*([가-힣]+팀)?', ev['contact'] or '')
        if dept:
            ev['authority'] = '금융감독원 ' + dept.group(1) + (' ' + dept.group(2) if dept.group(2) else '')
    else:
        ev.update({'date_promulgated': fields.get('게시일', row['date']) and norm_date(fields.get('게시일', row['date'])) or row['date']})
    ev['attachments'] = atts
    return ev


def build_fsc_event(key, src, row, det, atts):
    nid = re.search(r'(?:noticeId=|po040200/)(\d+)', row['url'])
    reg_name, reg_type = src['reg_name'], src['reg_type']
    if key == 'fsc_ntc_law':
        t = row['title'].replace(' ', '')
        if '시행규칙' in t:
            reg_name, reg_type = '보험업법 시행규칙', '시행규칙'
        elif '시행령' in t:
            reg_name, reg_type = '보험업법 시행령', '시행령'
        if '감독규정' in t:
            reg_name += ' · 보험업감독규정'
    ev = {
        # 같은 게시물이 두 검색(감독규정·보험업법)에 걸리면 id 가 같아 병합 시 1건으로 합쳐진다
        'id': f"{'fsc_ntc' if key == 'fsc_ntc_law' else key}_{nid.group(1) if nid else 'x'}",
        'source': key, 'source_label': src['label'], 'url': row['url'], 'list_title': row['title'],
        'reg_name': reg_name, 'reg_type': reg_type, 'status': src['status'],
        'authority': '금융위원회' + (' ' + det['dept'] if det.get('dept') else ''),
        'date': row.get('date') or det.get('date', ''),
        'body': det.get('body', ''),
        'attachments': merge_atts(row.get('files', []), [(a['url'], a['name']) for a in atts]),
    }
    if key == 'fsc_ntc':
        ev['date_notice'] = ev['date']
        ev['date_comment_due'] = row.get('date_comment_due', '')
        kind = re.search(r'구분\s*:\s*(입법예고|규정변경예고|행정예고)', row.get('info', ''))
        ev['notice_kind'] = kind.group(1) if kind else '규정변경예고'
    else:
        ev['date_promulgated'] = ev['date']
        g = re.search(r'고시\s*제?\s*(\d{4}-\d+)호', ev['body'] + ' ' + ' '.join(a['name'] for a in ev['attachments']))
        ev['gazette_no'] = g.group(1) if g else ''
    # 공고문/고시문 공통: "1. 개정 이유(사유·취지) … 2. 주요 내용 … 3. …"
    body = ev['body']
    m = re.search(r'1\.\s*(?:개정\s*)?(?:이유|취지|사유)\s*(.*?)\s*2\.\s*(?:주요\s*)?(?:내용|개정\s*내용)', body, re.S)
    ev['purpose'] = (m.group(1).strip() if m else '')[:600]
    m2 = re.search(r'2\.\s*(?:주요\s*)?(?:내용|개정\s*내용)\s*(.*?)(?:\s*3\.\s*(?:의견|시행|부칙|기타)|\s*$)', body, re.S)
    ev['content'] = (m2.group(1).strip() if m2 else '')[:1500]
    m3 = re.search(r'(\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})\s*일?\s*부터\s*시행', body)
    if m3:
        ev['date_effective'] = f'{m3.group(1)}-{int(m3.group(2)):02d}-{int(m3.group(3)):02d}'
    elif key == 'fsc_gosi' and re.search(r'고시한\s*날부터\s*시행', body):
        ev['date_effective'] = ev['date']
    return ev


def main():
    ap = argparse.ArgumentParser(description='보험 규정 개정 이벤트 수집 (금감원·금융위)')
    ap.add_argument('--since', required=True, help='이 날짜 이후만 (YYYY-MM-DD)')
    ap.add_argument('--out', required=True, help='출력 JSON 경로')
    ap.add_argument('--files-dir', required=True, help='첨부 저장 폴더')
    ap.add_argument('--sources', default=','.join(SOURCES), help='수집원 키 (쉼표)')
    ap.add_argument('--delay', type=float, default=DEFAULT_DELAY, help='요청 간격(초)')
    ap.add_argument('--limit', type=int, default=0, help='수집원당 최대 건수 (테스트용)')
    ap.add_argument('--no-download', action='store_true', help='첨부 다운로드 생략')
    ap.add_argument('--merge', help='기존 JSON 이 있으면 id 기준으로 병합(이미 있는 건은 재수집 안 함)')
    a = ap.parse_args()

    existing = {}
    if a.merge and os.path.exists(a.merge):
        for ev in json.load(open(a.merge, encoding='utf-8')):
            existing[ev['id']] = ev

    events = []
    for key in [k.strip() for k in a.sources.split(',') if k.strip()]:
        src = SOURCES[key]
        print(f'[{key}] 목록 수집… ({src["label"]})', file=sys.stderr)
        rows = fss_list(src, a.since, a.delay, a.limit) if src['kind'] == 'fss_list' else fsc_list(src, a.since, a.delay, a.limit)
        print(f'[{key}] {len(rows)}건', file=sys.stderr)
        for row in rows:
            try:
                if src['kind'] == 'fss_list':
                    fields, atts = fss_detail(row['url'], a.delay)
                    ev = build_fss_event(key, src, row, fields, atts)
                else:
                    det, atts = fsc_detail(row['url'], a.delay)
                    ev = build_fsc_event(key, src, row, det, atts)
                    if ev.get('date') and ev['date'] < a.since:   # 고시 목록은 날짜가 상세에만 있어 여기서 거른다
                        print(f'  - {ev["id"]} {ev["date"]} (since 이전, 중단)', file=sys.stderr)
                        break
                if ev['id'] in existing:
                    events.append(existing[ev['id']]); print(f'  = {ev["id"]} (기존)', file=sys.stderr); continue
                if not a.no_download:
                    dest = os.path.join(a.files_dir, ev['id'])
                    for att in ev['attachments'][:MAX_FILES_PER_EVENT]:
                        ext0 = os.path.splitext(att['name'])[1].lower()
                        # 확장자가 있는데 대상이 아니면 건너뜀. 이름에 확장자가 없으면(금융위 아이콘 링크) 받아서 Content-Disposition 으로 판별
                        if ext0 and ext0 not in DOWNLOAD_EXTS:
                            continue
                        try:
                            download(att, dest, a.delay)
                            if att.get('ext') == '.hwpx':
                                try:
                                    att['extracted'] = hwpx_extract(att['local'])
                                except zipfile.BadZipFile:          # 확장자만 hwpx 인 바이너리 hwp
                                    att['extracted'] = hwp5_extract(att['local'])
                            elif att.get('ext') == '.hwp':
                                att['extracted'] = hwp5_extract(att['local'])
                        except Exception as e:  # noqa
                            att['error'] = str(e)[:200]
                events.append(ev)
                print(f'  + {ev["id"]} {ev["date"]} {ev["status"]} 첨부 {len(ev["attachments"])}', file=sys.stderr)
            except Exception as e:  # noqa
                print(f'  ! {row.get("url")}: {e}', file=sys.stderr)
    events.sort(key=lambda e: e.get('date', ''), reverse=True)
    link_related(events)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(events, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'완료: {len(events)}건 → {a.out}', file=sys.stderr)


if __name__ == '__main__':
    main()
