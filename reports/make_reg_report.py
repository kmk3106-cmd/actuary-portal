#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
규정 개정 이벤트(JSON, scripts/collect_reg_history.py 산출) → 리포트 HTML 생성
docs/01_리포트_스타일가이드.md 서식을 따른다. CSS 는 templates/report-template.html 의 <style> 을 그대로 가져와 쓴다 (SSOT).

  python reports/make_reg_report.py --data data/reg_history.json --out-dir reports/output/reg
  python reports/make_reg_report.py --data data/reg_history.json --out-dir tmp/rep --ids fss_prv_4225,fsc_gosi_86827

출력: <out-dir>/<event id>.html  + <out-dir>/_index.json (id → 파일, 제목, 분류 결과)
"""
import argparse
import difflib
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, '..', 'templates', 'report-template.html')
MAX_ROWS_IN_REPORT = 60          # 대비표 행이 이보다 많으면 나머지는 부록으로
DASH_RE = re.compile(r'(?:[-─—―–‒ー=]\s?){4,}')   # 점선(붙은 것·띄운 것 모두) = 원문 '현행과 같음'
STATUS_LABEL = {'사전예고': '사전예고', '입법예고': '규정변경예고', '공포': '확정 고시', '시행': '확정 개정', '보도자료': '보도자료'}
STATUS_TAG = {'사전예고': '사전예고', '입법예고': '규정변경예고', '공포': '고시', '시행': '개정·시행', '보도자료': '보도자료'}
IMPACT_MAP = [
    (r'해약률|해지율', '해약률 가정'), (r'위험률|사망률|발생률', '위험률 가정'), (r'할인율|금리', '할인율·금리'),
    (r'지급여력|K-ICS|요구자본|가용자본', '지급여력(K-ICS)'), (r'책임준비금|보험부채|최선추정|CSM|위험조정', '책임준비금'),
    (r'계리가정|계리적\s*가정', '계리가정'), (r'실손', '실손의료보험'), (r'공시', '경영공시'), (r'업무보고서|별지', '업무보고서'),
    (r'IFRS|국제회계|재무제표', 'IFRS 회계'), (r'LTV|주택담보|부동산|PF', '대출·부동산 익스포저'), (r'비상위험준비금', '비상위험준비금'),
    (r'내부모형', '내부모형'), (r'자체\s*위험|ORSA', 'ORSA'), (r'판매채널|GA|법인보험대리점|모집', '판매채널'), (r'자산건전성|대손', '자산건전성'),
]
SYSTEM_MAP = [(r'해약률|위험률|할인율|계리가정|준비금|부채|CSM', '현금흐름모델'), (r'지급여력|K-ICS|요구자본|가용자본|내부모형', 'K-ICS 산출'),
              (r'업무보고서|별지|공시|재무제표', '결산·보고'), (r'실손|상품|판매', '상품·영업')]


def esc(s):
    return html.escape(str(s or ''), quote=False)


def fmt_date(d):
    return d.replace('-', '.') if d else '—'


def load_css():
    s = open(TEMPLATE, encoding='utf-8').read()
    m = re.search(r'<style>(.*?)</style>', s, re.S)
    return m.group(1) if m else ''


def all_text(ev):
    parts = [ev.get('purpose', ''), ev.get('content', ''), ev.get('body', ''), ev.get('list_title', '')]
    for a in ev.get('attachments', []):
        ex = a.get('extracted')
        if ex:
            parts += ex.get('paras', [])[:200]
            # 바이너리 hwp 는 본문이 표로만 나온다 — 부칙('… 2026년 10월 xx일부터 시행') 도 표 안에 있다
            parts += [c for t in ex.get('tables', [])[:40] for r in t[:80] for c in r if c][:400]
    parts.append(ev.get('supplement') or '')
    return ' '.join(p for p in parts if p)


def find_articles(text):
    arts = []
    for m in re.findall(r'별표\s?\d+(?:-\d+)?|별지\s?(?:제\s?)?\d+(?:-\d+)?호?|제\s?\d+-\d+조(?:의\s?\d+)?', text):
        m = re.sub(r'\s+', '', m)
        if m not in arts:
            arts.append(m)
    return arts[:10]


def impacts(text):
    areas = [lbl for pat, lbl in IMPACT_MAP if re.search(pat, text, re.I)]
    systems = [lbl for pat, lbl in SYSTEM_MAP if re.search(pat, text, re.I)]
    return areas[:6], systems[:4]


# 새 항목(조문 단위)의 시작으로 보는 줄머리: 조문·별표·별지·장·절·로마숫자 대제목. "1." "가." 같은 호·목 번호는 같은 조문 안의 줄이다
ITEM_START_RE = re.compile(r'^\s*(?:제\s?\d+(?:-\d+)?조(?:의\s?\d+)?|[\[<＜]?\s?별표\s?\d+|[\[<＜]?\s?별지\s?(?:제\s?)?\d+|[Ⅰ-Ⅻ]\s?\.|제\s?\d+\s?장|제\s?\d+\s?절)')
COMPARE_FILE_RE = re.compile(r'대비|신구|신·구|개정안|고시|세칙|규정')
MARKER_RE = re.compile(r'[<＜(\[]\s*(?:단서|항|호|목)?\s*(?:신\s*설|삭\s*제|생\s*략|이\s*동|현행과\s*같음)\s*[>＞)\]]|[-─—―–‒ー=]{3,}|\(현행과\s*같음\)')
RELEVANCE_PATH = os.path.join(HERE, '..', 'config', 'reg_relevance.json')
RELEVANCE_LEVELS = ['관련', '참고', '무관']


def load_relevance_rules():
    try:
        return json.load(open(RELEVANCE_PATH, encoding='utf-8'))
    except Exception:  # noqa
        return {'keywords': {'관련': [], '참고': []}, 'overrides': {}}


def classify_relevance(ev, strong_text, related, rules):
    """(관련|참고|무관, 사유). 건별 override → 취지·주요내용 키워드 → 선행 예고의 판정 → 무관"""
    ov = (rules.get('overrides') or {}).get(ev['id'])
    if ov and ov.get('relevance') in RELEVANCE_LEVELS:
        return ov['relevance'], ov.get('reason', '담당자 확정')
    kw = rules.get('keywords') or {}
    low = strong_text.lower()
    for level in ('관련', '참고'):
        hits = [k for k in kw.get(level, []) if k.lower() in low]
        if hits:
            return level, '키워드 자동 판정: ' + ', '.join(hits[:5])
    if related and related.get('_relevance'):
        return related['_relevance'][0], '선행 예고 판정 준용: ' + related['_relevance'][1]
    return '무관', '관련 키워드 없음 (자동 판정 — 확인 필요)'


def strip_markers(s):
    return re.sub(r'\s', '', MARKER_RE.sub('', s or ''))


def item_heading(ca, cb):
    """항목 제목: 조문/별표 머리가 있는 첫 줄. 점선·마커 제거, '제n조(제목)' 까지만"""
    for src in (cb, ca):
        for line in str(src or '').split('\n'):
            t = MARKER_RE.sub(' ', line)
            t = re.sub(r'\s+', ' ', t).strip(' ·,')
            if not t or len(t) < 2:
                continue
            m = re.match(r'(제\s?\d+(?:-\d+)?조(?:의\s?\d+)?\s*(?:\([^)]{0,40}\))?)', t)
            if m:
                return m.group(1)
            m = re.match(r'([\[<＜]?\s?별[표지]\s?(?:제\s?)?\d+(?:-\d+)?(?:호)?\s?[\]>＞]?\s*[^①-⑳\d]{0,40}?)(?:\s+제?\s?[①-⑳\d]|$)', t)
            if m:
                return m.group(1).strip()
            return t[:60]
    return '항목'


def compare_rows(ev):
    """첨부에서 '현행 | 개정안' 2열 표를 찾아 (현행, 개정안, 출처파일) 항목 목록으로.
    - 머리글 행('현행','개정안') 이 있으면 그 열을 쓰고, 없으면(hwp 바이너리 대비표) 2열 표의 0·1열로 본다
    - 표의 한 행이 문단 한 줄인 경우가 많아, 조문·별표 머리로 시작하는 행에서 새 항목을 시작하고 나머지 행은 이어 붙인다"""
    items = []
    for a in ev.get('attachments', []):
        ex = a.get('extracted')
        if not ex:
            continue
        for t in ex.get('tables', []):
            if not t or len(t[0]) < 2 or len(t) < 2:
                continue
            head = [re.sub(r'\s', '', c or '') for c in t[0]]
            ia = next((i for i, h in enumerate(head) if '현행' in h), None)
            ib = next((i for i, h in enumerate(head) if '개정' in h or '변경' in h), None)
            body_rows = t[1:]
            joined = ' '.join(' '.join(c or '' for c in r) for r in t)
            # 조문 대비표처럼 보이는가: 조문·별표·신설·삭제·점선 중 하나는 있고, 의견제출서·담당자 연락처 표는 아니어야 한다
            looks_law = bool(re.search(r'제\s?\d+(?:-\d+)?조|별표|별지|신\s*설|삭\s*제|[-─—]{4,}|현행과\s*같음', joined)) \
                and not re.search(r'접수부서|담당자|전화번호|팩스|의견제출자|연락처|메일', joined)
            if ia is None or ib is None or ia == ib:
                # 세로 배치 대비표 (금감원 예고안 hwp): 한 열에만 글이 있고 (현행 행, 개정안 행) 이 번갈아 온다
                filled_cols = [j for j in range(len(t[0])) if any((r[j] if j < len(r) else '') for r in t)]
                if not looks_law:
                    continue
                if len(filled_cols) == 1 and len(t) >= 2:
                    j = filled_cols[0]
                    body_rows = [[(t[k][j] if j < len(t[k]) else ''), (t[k + 1][j] if k + 1 < len(t) and j < len(t[k + 1]) else '')] for k in range(0, len(t), 2)]
                    ia, ib = 0, 1
                elif len(t[0]) in (2, 3) and len(t) >= 3 and COMPARE_FILE_RE.search(a['name']):
                    ia, ib, body_rows = 0, 1, t
                else:
                    continue
            elif not looks_law and len(t) < 3:
                continue
            cur = None
            for r in body_rows:
                ca, cb = (r[ia] if ia < len(r) else '') or '', (r[ib] if ib < len(r) else '') or ''
                if not (ca or cb).strip():
                    continue
                if re.sub(r'\s', '', ca) in ('현행', '현행규정', '현행조문') and re.sub(r'\s', '', cb) in ('개정안', '개정', '개정조문'):
                    continue
                first_b = (cb.strip().split('\n') or [''])[0]
                first_a = (ca.strip().split('\n') or [''])[0]
                starts = bool(ITEM_START_RE.match(first_b) or ITEM_START_RE.match(first_a))
                if cur is None or starts:
                    cur = [ca, cb, a['name']]; items.append(cur)
                else:
                    cur[0] = (cur[0] + '\n' + ca).strip('\n'); cur[1] = (cur[1] + '\n' + cb).strip('\n')
    # 변경이 없는 항목(개정안이 점선·'현행과 같음'·'생략' 뿐이거나 현행과 동일) 은 맥락 행이므로 뺀다
    out, unchanged = [], []
    for ca, cb, name in items:
        a_core, b_core = strip_markers(ca), strip_markers(cb)
        if not a_core and not b_core:
            continue
        if b_core and a_core == b_core:
            unchanged.append(item_heading(ca, cb)); continue
        if not b_core and a_core and not re.search(r'삭\s*제', cb or '') and MARKER_RE.search(cb or ''):
            unchanged.append(item_heading(ca, cb)); continue
        out.append((ca, cb, name))
    out_unchanged = []
    for u in unchanged:
        if u not in out_unchanged:
            out_unchanged.append(u)
    return out, out_unchanged


KIND_LABEL = {'n': '신설', 'c': '변경', 'v': '이동', 'm': '삭제', 's': '동일'}
KIND_ORDER = ['n', 'c', 'v', 'm', 's']
MOVE_RE = re.compile(r'(?:에서|으로|로|부터)\s*이동|이동\s*(?:신설|[>＞)\]])|[<＜(\[]\s*이동|※\s*[^\n]{0,40}이동')
SAME_RE = re.compile(r'^\s*(?:[①-⑳]|\d+\.|[가-힣]\.|[ⅰ-ⅹ]|[㉮-㉻]|-|•|◦|○)?\s*(?:[-─—―–‒ー=·.\s]{3,}|\(\s*현행과\s*같음\s*\)|[<＜]\s*현행과\s*같음\s*[>＞]|[<＜(]\s*생\s*략\s*[>＞)])\s*(?:[-─—―–‒ー=·.\s]*)$')
LEAD_RE = re.compile(r'^\s*(제\s?\d+(?:-\d+)?조(?:의\s?\d+)?|[①-⑳]|\d+\.|[가-힣ㄱ-ㅎa-z]\.|\(\d+\)|[ⅰ-ⅹ]+\)?|[ivx]+\)|[㉮-㉻]|[ⓐ-ⓩ])')
MAX_ALIGN_CELLS = 90000     # 항목 안 줄 정렬 DP 상한 (현행 줄수 × 개정안 줄수 = 300×300). 넘으면 순서대로 짝짓기
PAIR_THRESHOLD = 0.35       # 줄 정렬: 유사도가 이보다 높아야 '같은 줄의 변경' 으로 짝짓고, 낮으면 삭제 + 신설 두 줄로 둔다
TOKEN_RE = re.compile(MARKER_RE.pattern + r'|\w+|\s+|[^\w\s]', re.U)   # 마커(〈신설〉·점선)는 한 토큰으로 묶어 밑줄이 쪼개지지 않게


def classify(ca, cb):
    """항목(조문) 단위 종류: n 신설 / m 삭제 / v 이동 / c 변경"""
    a, b = re.sub(r'\s', '', ca), re.sub(r'\s', '', cb)
    a_core, b_core = strip_markers(ca), strip_markers(cb)
    if MOVE_RE.search(cb or '') or MOVE_RE.search(ca or ''):
        return 'v', '이동'
    if not a_core and b_core:
        return 'n', '신설'
    if re.search(r'삭\s*제', cb or '') and not b_core:
        return 'm', '삭제'
    if not b and a:
        return 'm', '삭제'
    return 'c', '변경'


def split_lines(cell):
    return [x.strip() for x in str(cell or '').split('\n') if x.strip()]


def norm_line(s):
    """줄 비교용 정규화: 마커·점선·공백 제거"""
    return re.sub(r'\s', '', MARKER_RE.sub('', DASH_RE.sub('', s or '')))


def is_same_marker(s):
    """개정안 줄이 '① ———' / '(현행과 같음)' 처럼 현행 유지 표시뿐인가"""
    return bool(s) and (bool(SAME_RE.match(s)) or not norm_line(s) and bool(DASH_RE.search(s) or '현행과' in s or '생략' in s))


def lead_token(s):
    m = LEAD_RE.match(s or '')
    return re.sub(r'\s', '', m.group(1)) if m else ''


def line_sim(a, b):
    """현행 줄 a 와 개정안 줄 b 의 유사도 0~1. 개정안이 '현행과 같음' 표시면 머리번호(①, 1., 가.) 일치 여부로 본다"""
    if is_same_marker(b):
        la, lb = lead_token(a), lead_token(b)
        return 0.9 if (la and la == lb) else (0.5 if not lb else 0.2)
    na, nb = norm_line(a), norm_line(b)
    if not nb and re.search(r'삭\s*제', b):      # 개정안 '〈삭제〉' 표시는 순서상 맞은편 현행 줄에 붙인다
        return 0.45
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    la, lb = lead_token(a), lead_token(b)
    sm = difflib.SequenceMatcher(None, na, nb, autojunk=False)
    r = sm.quick_ratio()                           # 상한값. 문턱 아래면 정확히 계산할 필요 없다
    if r >= PAIR_THRESHOLD:
        r = sm.ratio()
    # 개정안 줄이 '㉮ ——— 의 경과기간별…' 처럼 점선(현행과 같음)을 품고 있으면, 점선 자리는 현행 문구이므로
    # 개정안에 남은 글자가 현행에 모두 들어있을 때 같은 줄로 본다
    if r < PAIR_THRESHOLD and (DASH_RE.search(b) or '현행과' in b) and nb and len(nb) <= len(na):
        segs = [re.sub(r'\s', '', seg) for seg in MARKER_RE.split(b)]
        segs = [seg for seg in segs if len(seg) >= 2]
        if segs and sum(1 for seg in segs if seg in na) / len(segs) >= 0.6:
            r = max(r, 0.55)
    if la and lb and la == lb:
        r = max(r, 0.6)
    return r


def align_lines(A, B):
    """현행 줄 목록 A 와 개정안 줄 목록 B 를 순서를 지키며 짝짓는다 (Needleman-Wunsch).
    반환: (a 또는 '', b 또는 '') 의 목록. 셀 수가 상한을 넘으면 순서대로 짝짓는다"""
    n, m = len(A), len(B)
    if n * m > MAX_ALIGN_CELLS:
        k = max(n, m)
        return [(A[i] if i < n else '', B[i] if i < m else '') for i in range(k)]
    # 짝 점수 = 유사도 - 문턱 (문턱보다 비슷해야 양수), 비우기 = 0. 순서를 지키며 점수 합이 최대가 되게 짝짓는다
    score = [[line_sim(A[i], B[j]) - PAIR_THRESHOLD for j in range(m)] for i in range(n)]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best[i][j] = max(best[i - 1][j - 1] + score[i - 1][j - 1], best[i - 1][j], best[i][j - 1])
    out, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and score[i - 1][j - 1] > 0 and abs(best[i][j] - (best[i - 1][j - 1] + score[i - 1][j - 1])) < 1e-9:
            out.append((A[i - 1], B[j - 1])); i -= 1; j -= 1
        elif i > 0 and (j == 0 or abs(best[i][j] - best[i - 1][j]) < 1e-9):
            out.append((A[i - 1], '')); i -= 1
        else:
            out.append(('', B[j - 1])); j -= 1
    out.reverse()
    return out


def line_pairs(ca, cb):
    """항목 하나를 (현행 줄, 개정안 줄, 종류) 목록으로. 종류: n 신설 / c 변경 / v 이동 / m 삭제 / s 동일(현행과 같음)"""
    # 현행 칸의 '〈신 설〉'·점선 같은 자리표시 줄은 내용이 없으므로 뺀다 (맞은편 개정안 줄이 신설로 잡힌다)
    A = [x for x in split_lines(ca) if norm_line(x)]
    B = split_lines(cb)
    pairs = align_lines(A, B)
    out = []
    last_b_idx = max((k for k, (_, b) in enumerate(pairs) if b), default=-1)
    trailing_same = last_b_idx >= 0 and is_same_marker(pairs[last_b_idx][1]) and not re.search(r'삭\s*제', pairs[last_b_idx][1])
    for k, (a, b) in enumerate(pairs):
        if a and b:
            if is_same_marker(b) or norm_line(a) == norm_line(b):
                kind = 's'
            elif MOVE_RE.search(b):
                kind = 'v'
            elif re.search(r'[<＜(]\s*삭\s*제\s*[>＞)]', b) and not norm_line(b):
                kind = 'm'
            else:
                kind = 'c'
        elif a:
            # 개정안 마지막 줄이 '———'(이하 현행과 같음) 이면 그 뒤 현행 줄은 유지되는 줄이다
            kind = 's' if (trailing_same and k > last_b_idx) else 'm'
        else:
            kind = 'v' if MOVE_RE.search(b) else ('m' if re.search(r'[<＜(]\s*삭\s*제\s*[>＞)]', b) and not norm_line(b) else ('s' if is_same_marker(b) else 'n'))
        out.append((a, b, kind))
    return out


def word_diff(a, b):
    """두 줄의 단어 단위 차이를 (a_html, b_html) 로. 바뀐 조각은 <em> 으로 감싼다"""
    ta, tb = TOKEN_RE.findall(a), TOKEN_RE.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    ha, hb = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        sa, sb = esc(''.join(ta[i1:i2])), esc(''.join(tb[j1:j2]))
        if tag == 'equal':
            ha.append(sa); hb.append(sb)
        else:
            if sa.strip():
                ha.append(f'<em>{sa}</em>')
            elif sa:
                ha.append(sa)
            if sb.strip():
                hb.append(f'<em>{sb}</em>')
            elif sb:
                hb.append(sb)
    return ''.join(ha), ''.join(hb)


def mark_html(s):
    """원문 마커(점선·〈신설〉·〈삭제〉·(현행과 같음)) 를 표시용 span 으로"""
    s = DASH_RE.sub('<span class="mk">(현행과 같음)</span>', s)
    # esc() 를 거친 문자열이라 '<' 는 &lt; 로 들어온다. 〈신설〉〈단서 신설〉〈삭제〉〈생략〉〈이동〉 변형을 모두 표시용 span 으로
    s = re.sub(r'(?:&lt;|[＜(\[])\s*((?:단서|항|호|목)?\s*(?:신\s*설|삭\s*제|생\s*략|이\s*동|현행과\s*같음))\s*(?:&gt;|[＞)\]])',
               lambda m: '<span class="mk">(현행과 같음)</span>' if '현행' in m.group(1) else '<span class="nil">〈' + re.sub(r'\s', '', m.group(1)).replace('단서', '단서 ') + '〉</span>', s)
    return s


def line_cls(line):
    return ' class="ind"' if re.match(r'\s*(?:[①-⑳]|\d+\.|[가-힣]\.|[ⅰ-ⅹ]|[ivx]+\)|[㉮-㉻]|[ⓐ-ⓩ]|-|•|◦|○)', line.strip()) and not re.match(r'제\d', line.strip()) else ''


def cmp_table(ca, cb):
    """항목 하나의 현행·개정안을 줄 단위로 맞춘 표 HTML + 줄 종류별 개수"""
    pairs = line_pairs(ca, cb)
    counts = {k: 0 for k in KIND_ORDER}
    rows = []
    for a, b, kind in pairs:
        counts[kind] += 1
        if kind == 'c':
            ha, hb = word_diff(a, b)
            ha, hb = mark_html(ha), mark_html(hb)
        elif kind == 'v' and a and b:
            ha, hb = word_diff(a, b)
            ha, hb = mark_html(ha), mark_html(hb)
        else:
            ha, hb = mark_html(esc(a)) if a else '', mark_html(esc(b)) if b else ''
        if kind == 's' and a and not b:
            hb = '<span class="mk">(현행과 같음)</span>'
        rows.append(f'<tr class="k-{kind}"><td class="k"><span class="lk {kind}">{KIND_LABEL[kind]}</span></td>'
                    f'<td class="col-a"><p{line_cls(a)}>{ha or "<span class=nil>—</span>"}</p></td>'
                    f'<td class="col-b"><p{line_cls(b)}>{hb or "<span class=nil>—</span>"}</p></td></tr>')
    html = ('<div class="tw"><table class="cmpt"><thead><tr><th class="k">구분</th><th>현행</th><th class="b">개정안</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>')
    return html, counts


def counts_text(counts, with_same=False):
    bits = [f'{KIND_LABEL[k]} {counts[k]}' for k in KIND_ORDER if counts.get(k) and (with_same or k != 's')]
    return ' · '.join(bits) if bits else '변경 줄 없음'


def law_html(cell, side):
    out = []
    for line in [x for x in str(cell).split('\n') if x.strip()]:
        s = mark_html(esc(line.strip()))
        out.append(f'<p{line_cls(line)}>{s}</p>')
    return '\n'.join(out) or '<p class="nil">—</p>'


def bullets(text):
    """'□ ◦ 가. 1.' 등으로 구분된 본문을 문장 목록으로"""
    if not text:
        return []
    t = re.sub(r'\s+', ' ', text)
    parts = re.split(r'\s(?=(?:□|◦|○|ㅇ|▪|■|-|•|\d+\.\s|[가-힣]\.\s|[①-⑳]))', ' ' + t)
    out = []
    for p in parts:
        p = p.strip(' □◦○ㅇ▪■•-')
        p = re.sub(r'^\d+\.\s*|^[가-힣]\.\s*', '', p).strip()
        if len(p) > 3:
            out.append(p)
    return out[:20]


def sections_from_paras(paras):
    """예고안 hwp 문단에서 '규정 변경 주요 내용'/'개정 이유' 류 소제목 아래 문단을 모은다"""
    sec, cur = {}, None
    for p in paras:
        m = re.match(r'^\s*\d+\.\s*(.{2,30})$', p)
        if m and len(p) < 40:
            cur = m.group(1).strip(); sec[cur] = []
            continue
        if cur:
            sec[cur].append(p)
    return sec


# 예고안 부칙의 시행일 표기 — '2026년 10월 xx일' (일자 미정) · '2024년 X월 X일' (연도만) · '202x년 x월 x일' (전부 미정) · '’25. 10. 0.' 까지 읽는다
_YR = r'(\d{4}|\d{3}[xX]|[’\']\s*\d{2})'
_MD = r'(\d{1,2}|[xX○□●◯]{1,2})?'
EFFECTIVE_RE = re.compile(_YR + r'\s*[.년]\s*' + _MD + r'\s*[.월]?\s*' + _MD + r'\s*[.일]?\s*(?:이후\s*[^.]{0,20}?)?부터\s*시행')
GOSI_EFFECTIVE = {}     # 확정 감독규정 고시일 → 시행일 (main() 이 채움) — 세칙 부칙 '감독규정 시행일부터 시행' 연동용
EFFECTIVE_LBL_RE = re.compile(r'시행일\s*[:：]\s*[’\']?\s*(\d{2,4})\s*\.\s*(\d{1,2})\s*\.?\s*(\d{1,2})?')
# 부칙 본문 '이 세칙은 … 시행한다' (제1조(시행일) 이 있든 없든) — 본칙·다만(예외) 을 나눠 읽는다
_SUBJ = r'이\s*(세칙|규정|영|법|규칙|고시)[은는]'
CLAUSE_RE = re.compile(_SUBJ + r'((?:(?!시행한다|이\s*(?:세칙|규정|영|법|규칙|고시)[은는]).){0,250}?)시행한다', re.S)
EXCEPT_RE = re.compile(r'(?:다만|단)[,，]?\s*((?:(?!시행한다|제\d조\s*\(|이\s*(?:세칙|규정|영|법|규칙|고시)[은는]).){0,200}?)시행한다', re.S)
OLD_SUPP_RE = re.compile(r'<\s*(?:대통령령|법률|총리령|금융위원회\s*고시|금융감독원\s*세칙)?\s*제\s*(?!9999)\d{2,}호')   # 신구조문대비표에 끼어 있는 '예전' 부칙
# 날짜 대신 조건으로 정한 시행일 — 날짜가 없어도 '언제 시행인지' 는 적어야 한다
EFFECTIVE_RULES = [
    (re.compile(r'(?:고시|공포|발령)한\s*날(?:로)?부터\s*시행'), '공포(고시)한 날부터 시행'),
    (re.compile(r'공포\s*후\s*(\d+)\s*(개월|년)이?\s*경과한\s*날부터\s*시행'), '공포 후 {0}{1}이 경과한 날부터 시행'),
    (re.compile(r'(보험업감독규정)\s*\(([^)]{0,40})\)\s*의?\s*시행일부터\s*시행'), '{0} 개정({1})의 시행일부터 시행'),
    (re.compile(r'([가-힣]{2,20})의\s*시행일부터\s*시행'), '{0}의 시행일부터 시행'),
]


def effective_text(ev):
    """시행일 문장은 첨부 끝(부칙) 이나 표 셀에 있으므로 all_text 의 길이 상한을 두지 않고 '시행' 이 든 조각만 모은다."""
    parts = [ev.get('purpose') or '', ev.get('content') or '', ev.get('body') or '', ev.get('supplement') or '']
    for a in ev.get('attachments', []):
        ex = a.get('extracted') or {}
        parts += [p for p in ex.get('paras', []) if '시행' in p]
        parts += [c for t in ex.get('tables', []) for r in t for c in r if c and '시행' in c]
    return ' '.join(parts)


def _num(g, hi):
    if g and g.isdigit() and 1 <= int(g) <= hi:
        return int(g)
    return None


def _year(g):
    g = (g or '').replace('’', '').replace("'", '').strip()
    if g.isdigit():
        return int(g) + 2000 if len(g) == 2 else int(g)
    return None


def _date_of(frag):
    """조각 하나에서 (날짜 'YYYY-MM-DD'|'YYYY-MM'|'YYYY'|'', 날짜 표기가 있었는지)"""
    m = EFFECTIVE_RE.search(frag)
    if not m:
        return '', False
    y, mo, d = _year(m.group(1)), _num(m.group(2), 12), _num(m.group(3), 31)
    if y and mo and d:
        return f'{y}-{mo:02d}-{d:02d}', True
    if y and mo:
        return f'{y}-{mo:02d}', True
    return (str(y) if y else ''), True


def _rule_of(frag):
    for rx, tpl in EFFECTIVE_RULES:
        m = rx.search(frag)
        if m:
            return tpl.format(*m.groups())
    return ''


def supplement_clauses(text):
    """부칙 본칙 조각들 — [{'subj','main','excepts':[...],'raw'}]. 신구조문대비표에 끼어 있는 예전 부칙(<제NNN호>)은 뺀다."""
    out = []
    for m in CLAUSE_RE.finditer(text):
        before = text[max(0, m.start() - 70):m.start()]
        if OLD_SUPP_RE.search(before) or '현행과' in before[-20:]:
            continue
        tail = text[m.end():m.end() + 400]
        excepts = [x.group(1).strip() + ' 시행' for x in EXCEPT_RE.finditer(tail[:tail.find('제2조') if '제2조' in tail else 400])]
        lead = re.search(r'(?:부\s*칙\s*(?:<[^>]{0,40}>)?\s*)?(?:제1조\s*\(시행일\)\s*(?:①\s*)?)?$', before)
        raw_start = m.start() - (len(lead.group(0)) if lead else 0)
        ex_end = m.end()
        for x in EXCEPT_RE.finditer(tail):
            if x.start() > 300:
                break
            ex_end = m.end() + x.end()
        nxt = re.search(r'(?:②|제2조\s*\([^)]{0,20}\))[^.]{0,160}\.', text[ex_end:ex_end + 220])
        raw = text[raw_start:ex_end] + ((' ' + nxt.group(0)) if nxt else '')
        out.append({'subj': m.group(1), 'main': m.group(0), 'excepts': excepts, 'raw': re.sub(r'\s+', ' ', raw).strip()[:400]})
    return out


def find_effective(ev, text):
    """부칙에서 시행일 추출 → (날짜, 조건문, 비고, 부칙 원문).
    날짜는 'YYYY-MM-DD' | 'YYYY-MM'(일자 미정) | 'YYYY'(월·일 미정) | ''. 본칙이 '공포한 날부터' 처럼 조건이면 조건문을, '다만 …은 2027.1.1 시행' 은 비고로.
    여러 규정(시행령 · 감독규정) 이 한 공고에 있으면 본칙 날짜가 있는 첫 규정을 쓰고 나머지는 비고에 적는다. 공고문의 '고시한 날부터 시행' 은 확정 건이면 게시일로 본다."""
    clauses = supplement_clauses(text)
    date, rule, notes = '', '', []
    SUBJ_LBL = {'세칙': '시행세칙', '규정': '감독규정', '영': '시행령', '법': '법률', '규칙': '시행규칙', '고시': '고시'}
    picked = None
    for c in clauses:
        d, had = _date_of(c['main'])
        r = _rule_of(c['main'])
        if picked is None and (d or r or had):
            picked = c
            date, rule = d, r
            if had and not d:
                rule = rule or '연·월·일 미정 (예고안)'
            elif d and len(d) == 4:
                rule = rule or '월·일 미정 (예고안)'
        elif picked is not None and (d or r) and (c['subj'], d, r) != (picked['subj'], date, rule):   # 같은 문장이 본문·표에 두 번 나온 건 빼고, 다른 규정(시행령 vs 감독규정) 만 비고
            notes.append(f"{SUBJ_LBL.get(c['subj'], c['subj'])}은 {planned_label(d) if d else r}")
    if picked:
        for x in picked['excepts']:
            d, _ = _date_of(x)
            r = _rule_of(x)
            if d or r:
                xs = re.sub(r'\s+', ' ', x).strip()
                if len(xs) > 90:
                    xs = xs[:90].rsplit(' ', 1)[0] + '…'
                notes.append('다만 ' + xs + ((' → ' + planned_label(d)) if d else ''))
    notes = [n for n in dict.fromkeys(notes) if not (date and len(date) == 10 and '미정' in n)]   # 확정일을 아는데 '월·일 미정' 옛 표기는 잡음
    raw = picked['raw'] if picked else (clauses[0]['raw'] if clauses else '')
    if ev.get('date_effective'):
        return ev['date_effective'], ('' if not rule.endswith('(예고안)') else rule), ' · '.join(notes), raw
    if picked and not date and rule == '공포(고시)한 날부터 시행' and ev['status'] in ('공포', '시행'):
        date, rule = ev.get('date', ''), ''
    if not picked:
        m = EFFECTIVE_LBL_RE.search(text)          # '□시행일 : ’25. 10. 0.'
        if m:
            y, mo, d = _year(m.group(1)), _num(m.group(2), 12), _num(m.group(3), 31)
            if y and mo:
                date = f'{y}-{mo:02d}-{d:02d}' if d else f'{y}-{mo:02d}'
        if not date:
            date, _ = _date_of(text)               # 부칙 꼴이 아닌 본문 문장 ('… 2026년 6월 30일부터 시행')
        if not date and not rule:
            rule = _rule_of(text)
        if not date and not rule and ev['status'] in ('공포', '시행') and re.search(r'(?:고시|공포|발령)한\s*날(?:로)?부터\s*시행', text):
            date = ev.get('date', '')
    if date and rule and not rule.endswith('(예고안)'):
        rule = ''                                   # 본칙 날짜가 있으면 조건문은 쓰지 않는다
    if not date and rule.startswith('보험업감독규정 개정('):   # '감독규정(2023년 3월 2일 개정의결)의 시행일부터' → 그 고시의 시행일로 연동
        m = re.search(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2}|[xX])?', rule)
        if m:
            key = f'{m.group(1)}-{int(m.group(2)):02d}'
            hits = [(d, e) for d, e in GOSI_EFFECTIVE.items() if d.startswith(key) and (not (m.group(3) or '').isdigit() or d == f'{key}-{int(m.group(3)):02d}')]
            if len(hits) == 1:
                date = hits[0][1]
                notes.append(f'보험업감독규정 {fmt_date(hits[0][0])} 고시의 시행일({fmt_date(date)}) 연동')
                rule = ''
    return date, rule, ' · '.join(notes), raw


def planned_label(p):
    """예정 시행일 표기 — 'YYYY' → 'YYYY년 (월·일 미정)', 'YYYY-MM' → 'YYYY.MM (일자 미정)'."""
    if not p:
        return ''
    if len(p) == 4:
        return f'{p}년 (월·일 미정)'
    if len(p) == 7:
        return fmt_date(p) + ' (일자 미정)'
    return fmt_date(p)


def short_purpose(ev):
    p = ev.get('purpose') or ''
    p = re.sub(r'^[\sㅁ□◦○ㅇ▪■•\-]*(?:\d+\.\s*|[가-힣]\.\s)?', '', p)   # 글머리표·번호 제거
    p = re.split(r'(?<=[다요])\s|\s\(|\s에\s따라', p)[0] if p else ''
    if not p:
        p = ev.get('list_title', '')
    return (p[:70] + '…') if len(p) > 70 else p


LINK_MAX_GAP_DAYS = 240          # 예고 → 확정 게시 사이 최대 간격
LINK_HIGH_OVERLAP, LINK_HIGH_SIM = 2, 0.6     # high: 조문 겹침 ≥2 또는 취지 유사도 ≥0.6
LINK_MED_OVERLAP, LINK_MED_SIM = 1, 0.3       # medium: 겹침 1 또는 유사도 ≥0.3 (연결 후보 · 원문 대조 필요)
LINK_CONFIDENCE_LABEL = {'high': '선행 예고', 'medium': '선행 예고 (연결 후보 · 원문 대조 필요)', 'low': '선행 예고 (추정 · 근거 부족)'}


def _gist(e):
    """연결 비교용 취지 문장 (공백 제거)"""
    return re.sub(r'\s', '', (e.get('purpose') or e.get('content') or e.get('list_title') or '')[:400])


def relink(events):
    """확정 건(공포·시행) ↔ 선행 예고 연결 + 신뢰도·근거 (docs/03 P0-3).
    같은 규정, 확정일 이전 240일 안의 예고 가운데 조문·별표 겹침과 취지 유사도가 가장 높은 것을 고르고
    high / medium / low 로 매긴다. low 는 "같은 규정의 가장 가까운 예고" 일 뿐이라 화면에서는 쓰지 않는다."""
    def arts_of(e):
        # 바이너리 hwp 는 문단 없이 표만 나오므로 대비표 항목 머리(제n조·별표)도 조문 근거로 쓴다
        heads = ' '.join(item_heading(a, b) for a, b, _ in compare_rows(e)[0])
        return set(find_articles(all_text(e) + ' ' + heads)) | set(e.get('articles') or [])
    notices = [e for e in events if e['status'] in ('사전예고', '입법예고') and e.get('date')]
    na = {n['id']: arts_of(n) for n in notices}
    ng = {n['id']: _gist(n) for n in notices}
    for e in events:
        if e['status'] not in ('공포', '시행') or not e.get('date'):
            continue
        ea, eg = arts_of(e), _gist(e)
        best = None
        for n in notices:
            if n['reg_name'].split(' ·')[0] != e['reg_name'].split(' ·')[0] or n['date'] > e['date']:
                continue
            gap = int(e['date'].replace('-', '')) - int(n['date'].replace('-', ''))
            if gap > LINK_MAX_GAP_DAYS:
                continue
            # 의견제출 시한 전에 확정 게시되는 경우도 실제로 있어(’26.4 K-ICS 건) 시한으로는 거르지 않는다
            overlap = sorted(ea & na[n['id']])
            sim = difflib.SequenceMatcher(None, eg, ng[n['id']], autojunk=False).ratio() if eg and ng[n['id']] else 0.0
            key = (len(overlap) * 2 + sim * 3, -gap)
            if best is None or key > best[0]:
                best = (key, n, overlap, sim, gap)
        if not best:
            e['related_notice_id'] = None; e['_link_strong'] = False; e['_link_confidence'] = ''; e['_link_evidence'] = ''
            continue
        _, n, overlap, sim, gap = best
        if len(overlap) >= LINK_HIGH_OVERLAP or sim >= LINK_HIGH_SIM:
            conf = 'high'
        elif len(overlap) >= LINK_MED_OVERLAP or sim >= LINK_MED_SIM:
            conf = 'medium'
        else:
            conf = 'low'
        e['related_notice_id'] = n['id']
        e['_link_confidence'] = conf
        e['_link_strong'] = conf == 'high'
        e['_link_evidence'] = (f"규정명 동일 · 조문 겹침 {len(overlap)}개" + (f"({', '.join(overlap[:4])})" if overlap else '')
                               + f" · 취지 유사도 {sim:.2f} · 예고 후 {gap}일")


# ── 목록 제목 = 대상 + 실질 변경 (docs/03 P0-5, 지시서 §12) ──────────────────────────────
TITLE_MAX = 58                 # 목록 제목 길이 상한(자). 함축보다 구체성에 비중(70:30) — 수치·조문·대상을 남긴다
ITEM_MAX = 40                  # 변경 항목 하나를 줄인 길이 상한
SUMMARY_MAX = 110              # 한 줄 요약 상한
# 변경 행위 (문장 끝의 동작 명사). 이 앞의 명사구가 '대상' 이다
ACTION_RE = re.compile(r'(인하|인상|신설|마련|개선|정비|확대|축소|완화|강화|단축|연장|명시|삭제|변경|도입|한정|구체화|반영|추가|폐지|통합|현행화|상향|하향|적용|제외|제한|규정|조정|전환|개편|지정|구분|간소화|일원화|명확화|합리화|허용|면제|구축|금지|감면|의무화|세분화|활성화|부과|생략)(?=$|[^가-힣]|하|함|한|됨|되|돼|토록)')   # '확인하도록' 의 '인하' 처럼 낱말 속 글자는 제외
# 추상어만으로 끝나는 제목 금지: 대상 명사 없이 아래 말로만 끝나면 실패
ABSTRACT_ONLY_RE = re.compile(r'^(?:\S+\s){0,1}(?:일부\s?개정|제도\s?개선|합리화|명확화|정비|강화|개선|변경|개정|관련\s?사항\s?변경|기준\s?강화)$')
# 제목에서 뺄 군더더기
TITLE_NOISE_RE = re.compile(r'\((?:안|案)\s*[^)]*\)|\[[^\]]*\]|\*[^\s]*|｢|｣|「|」|『|』|\s+등\s*$')
PARTICLE_RE = re.compile(r'(을|를|이|가|은|는|의|에|로|으로|와|과|도|에서|에게|까지)$')
CLAUSE_END_RE = re.compile(r'(경우|따라|위해|위하여|위한|대해|대한|관련|토록|도록|하여|함에|하고|함으로써|함에\s따라),?$')
PRESS_LABEL_RE = re.compile(r'[ㅁ□◦○ㅇ▪■•①-⑳]\s*\(([^)]{2,24})\)')


def _strip_article_refs(s):
    """'(안 제6-11조의6제2항)' 같은 조문 참조를 떼고 참조 목록을 돌려준다"""
    refs = [re.sub(r'\s', '', m) for m in re.findall(r'(?:안\s*)?(제\s?\d+(?:-\d+)?조(?:의\s?\d+)?|별표\s?\d+(?:-\d+)?(?:의\s?\d+)?|별지\s?(?:제\s?)?\d+(?:-\d+)?호?)', s)]
    s = TITLE_NOISE_RE.sub(' ', s)
    s = re.sub(r'\((?:제\s?\d+(?:-\d+)?조[^)]*|별표\s?\d+[^)]*|별지\s?(?:제\s?)?\d+[^)]*)\)', '', s)   # '(별지64)' 같은 조문 참조 괄호
    s = re.sub(r'\(\s*\)', '', s)
    s = re.sub(r'\s+', ' ', s).strip(' .,·-')
    return s, list(dict.fromkeys(refs))


LEAD_NUM_RE = re.compile(r'^(?:\(\d+\)|[가-힣]\.|\d+\.|[①-⑳]|[ⅰ-ⅹ]+\.?|[a-z]\)|[ㅁ□◦○ㅇ▪■•\-–])\s*')
OBJ_PARTICLE_RE = re.compile(r'(을|를|은|는)$')     # 변경 행위 바로 앞 토큰에서만 뗀다 ('시가평가' 의 '가' 를 떼지 않기 위해)
DOMAIN_KW_RE = re.compile(r'(해약환급금준비금|해약률|위험률|할인율|계리가정|계리적\s?가정|책임준비금|보험부채|비상위험준비금|지급여력비율|요구자본|경험통계기간|사업비\s?가정|손해율\s?가정|평균해지율|계약자배당|유배당손익|선임계리사|내부모형|ORSA|경영실태평가|업무보고서|표준약관|표준사업방법서|상품위원회|판매수수료|간단보험대리점|손해사정|DSR|LTV|담보대출|실손의료보험|실손|반려동물보험|공정가치)')
PHRASE_CHARS = 34                    # 변경 행위 앞에서 거슬러 올라가며 모을 글자 수
JUNK_ITEM_RE = re.compile(r'^(?:\(현행\)|\(개선\)|세부 개정 내용|자세한 사항|보험 가입기간이|보험료가 비교적|위험보장 내용이|없음 명백|일시|장소|배경|개요|추진경과|향후 계획|향후계획)')


def _clean_item(item):
    s = item.strip()
    s = re.sub(r'^[^\w가-힣‘’“”「『(\[]+', '', s)                       # 앞머리 쓰레기(: ) 등)
    if ')' in s and ('(' not in s or s.index(')') < s.index('(')):     # 글머리 분리로 잘린 괄호 꼬리
        s = s[s.index(')') + 1:].strip()
    s = LEAD_NUM_RE.sub('', s)
    s = re.sub(r'^[\(（][^)）]*[\)）]\s*', '', s)                          # 앞머리 괄호 설명((종전)·(현행)) 통째로 제거
    s = re.sub(r'\s+', ' ', s).strip()
    return s


LEAD_JUNK = ('및', '등', '등을', '등의', '있는', '있던', '하는', '되는', '하며', '하고', '또한', '아울러', '그', '이', '해당')


def _strip_lead(toks):
    """'있던 선임계리사의 …' / '하며, 손해사정업자의 …' 처럼 앞 절의 꼬리로 시작하는 토막을 정리"""
    while toks and (toks[0].endswith((',', '며', '고', '던', '된', '하여')) or toks[0] in LEAD_JUNK):
        toks.pop(0)
    return toks


LAW_BOILERPLATE_RE = re.compile(r'현행\s*제도의\s*운영상\s*나타난\s*일부\s*미비점을?\s*개선[ㆍ·]?보완|법률에서\s*위임된\s*사항과\s*그\s*시행에\s*필요한\s*사항을\s*정하')


def law_reason_items(content):
    """국가법령정보센터 제개정이유 → 변경 항목. '◇ 주요내용' 의 '가. 제목(조문)' 머리를 쓰고, 없으면 개정이유 한 문장을 '하고, / 하는 한편,' 절로 나눈다."""
    c = re.sub(r'\s+', ' ', content or '')
    c = re.sub(r'^\[[^\]]*\]\s*', '', c).replace('<법제처 제공>', '').strip()
    m = re.search(r'◇\s*주요내용\s*(.*)$', c)
    items = []
    if m:
        for part in re.split(r'\s(?=[가-힣]\.\s)', ' ' + m.group(1)):
            part = part.strip()
            if not re.match(r'[가-힣]\.\s', part):
                continue
            h = re.match(r'[가-힣]\.\s(.*?\((?:제\s?\d|별표|별지)[^)]*\))', part)
            items.append(h.group(1) if h else re.sub(r'^[가-힣]\.\s', '', part)[:90])
    if not items:
        body = re.sub(r'^◇\s*개정이유(?:\s*및\s*주요내용)?\s*', '', c)
        for cl in re.split(r'(?:하고|하며|되고|되며|하는\s*한편|한편),\s*', body):
            cl = cl.strip(' .,')
            if len(cl) > 8 and not LAW_BOILERPLATE_RE.search(cl):
                items.append(cl)
    return items[:12]


def compress_item(item):
    """'직전 분기말 … 해약환급금준비금을 현행 산출방식에 따른 금액의 100분의 80만 적립하도록 적립비율을 인하(안 제6-11조의6제2항)'
    → '해약환급금준비금 적립비율 인하'. 마지막 변경 행위 앞의 짧은 명사구 + (빠졌으면) 가장 가까운 대상 명사를 앞에 붙인다.
    변경 행위가 없는 글(설명·조건문)은 버린다 ('', refs)"""
    s0 = _clean_item(item)
    s0 = re.sub(r'100분의\s*(\d+)', r'\1%', s0)
    s, refs = _strip_article_refs(s0)
    s = re.split(r'\s[-–]\s|\s\*', s)[0]                  # 부연 설명(- …, * 각주) 제거
    s = re.sub(r'\([^)]*(?:고시\s*제|부칙|제\s?\d+조)[^)]*\)', '', s)   # '(금융위원회 고시 제2022-53호 부칙 제3조 삭제)' 같은 근거 괄호
    if not s or JUNK_ITEM_RE.match(s) or '→' in s:
        return '', refs
    toks = _strip_lead(s.split())
    act_idx = None
    for i in range(len(toks) - 1, -1, -1):
        if ACTION_RE.search(toks[i]):
            act_idx = i
            break
    if act_idx is None:
        return '', refs
    act = ACTION_RE.search(toks[act_idx]).group(1)
    phrase = []
    i = act_idx - 1
    while i >= 0:
        t = toks[i]
        if CLAUSE_END_RE.search(t) or t.endswith(('하도록', '토록', '하여', '위해', '따라', '경우', '때에', '맞춰', '맞추어', '통해', '기준으로', '있도록')) or (phrase and t == '에서'):
            break
        if i < act_idx - 1 and ACTION_RE.search(t) and re.sub(r'[()\d.]', '', t).endswith(ACTION_RE.search(t).group(1)):   # 앞 절의 변경 행위('범위 확대') 에서 멈춘다
            break
        if i == act_idx - 1 and t not in ('또는', '및', '등'):
            t = OBJ_PARTICLE_RE.sub('', t)
        phrase.insert(0, t)
        if len(' '.join(phrase)) >= PHRASE_CHARS:
            break
        i -= 1
    out = re.sub(r'\s+', ' ', ' '.join(phrase + [act]).strip())
    while len(out) > ITEM_MAX and ' ' in out:          # 길면 앞(수식어)부터 줄인다 — 변경 행위는 남긴다
        out = out.split(' ', 1)[1]
    out = ' '.join(_strip_lead(out.split()))            # 앞을 잘라내고 남은 '있던 …' 같은 앞 절 꼬리 제거
    # 대상 명사(계리 핵심어)가 빠졌으면, 변경 행위 앞에서 가장 가까운 핵심어를 앞에 붙인다 (길이 상한보다 대상이 우선)
    before = ' '.join(toks[:act_idx])
    kws = [k for k in DOMAIN_KW_RE.findall(before) if re.search(re.escape(k) + r'(?![사업자인])', before)]   # '손해사정사' 속 '손해사정' 은 대상이 아니다 ('실손의료보험의' 는 된다)
    if kws and kws[-1].replace(' ', '') not in out.replace(' ', ''):
        out = kws[-1] + ' ' + out
    # 수치(80%, 5년, 30년 …)는 구체성의 핵심이라 빠졌으면 괄호로 남긴다
    nums = [n for n in re.findall(r'(?<![제-])\d+(?:\.\d+)?\s?(?:%|년|억원|만원|배|개월)', s) if n not in out]   # 법률 '제19211호' 같은 번호는 수치가 아니다
    if nums:
        out += '(' + ' · '.join(dict.fromkeys(nums[:2])) + ')'
    return out.rstrip(' ·,('), refs


HEADLINE_VERB_CORE = r'(도입|마련|조정|개편|강화|개선|신설|시행|구축|정비|확대|고도화|추진|실시|의결|통과|개최|운영|구성|확립|제고|제정|개정|지정|발표|전환|규제)'
HEADLINE_VERB_RE = re.compile(HEADLINE_VERB_CORE + r'(?![가-힣])')   # '시행령' 의 '시행' 처럼 낱말 속 글자는 제외


def press_title(ev):
    """보도자료: 본문 글머리의 '(계리가정 관리 강화)' 같은 꼬리표 → '계리가정 관리 강화 · 계리가정 보고서 도입 발표'.
    없으면 헤드라인의 핵심 명사구('…도입으로 … 제고하겠습니다' → '… 도입')만 남긴다"""
    body = (ev.get('purpose') or '') + ' ' + (ev.get('body') or '')[:600]
    labels = [l.strip() for l in PRESS_LABEL_RE.findall(body)]
    labels = [l for l in labels if len(l) >= 4 and not JUNK_ITEM_RE.match(l) and not re.fullmatch(r'[\d.\s년월일~’‘]+', l)][:2]
    if labels:
        return ' · '.join(labels) + ' 발표', 'press_labels'
    h = re.sub(r'^\s*[\[(【]\s*보도\s*(?:자료|참고)\s*[\])】]\s*', '', ev.get('list_title') or '').strip()
    h = re.split(r'\s[-–]\s', h)[0]
    h = re.sub(r'[「」｢｣『』]', '', h)
    # ① '핵심 명사구 + 행위' 가 '(으)로/통해/하여' 앞에 오면 그것이 제목이다
    m = re.match(r'^(.{6,44}?' + HEADLINE_VERB_CORE + r')(?:으로|로|을\s*통해|를\s*통해|하여|함으로써)\s', h)
    if m:
        core = m.group(1)
    else:
        # ② '…을 위해 / 되도록 / 하도록' 뒤의 주절
        segs = re.split(r'(?:을|를)?\s*(?:위해|위하여|되도록|하도록|있도록|통해)\s*', h)
        core = segs[-1] if len(segs) > 1 and len(re.sub(r'[가-힣]*(?:겠|했|합니다|됩니다).*$', '', segs[-1])) >= 8 else h   # 주절이 너무 짧으면('감독·지원') 조건절까지 둔다
        core = re.sub(r'(을|를|이|가)?\s*(구성하여|마련하여|마련하였습니다|마련하겠습니다|운영하겠습니다|해나가겠습니다|나가겠습니다|해나갑니다|하겠습니다|하였습니다|했습니다|합니다|됩니다|입니다|예정입니다)\.?$', '', core).strip()
        vm = list(HEADLINE_VERB_RE.finditer(core))
        if vm and vm[-1].end() >= 6:
            core = core[:vm[-1].end()]
    core = re.sub(r'(을|를|이|가|은|는)$', '', core.strip(' .,·')).strip()
    core = re.sub(r'(을|를|이|가)\s+' + HEADLINE_VERB_CORE + r'$', r' \2', core).strip()   # '감독을 강화' → '감독 강화', '제도가 개선' → '제도 개선'
    if len(core) > TITLE_MAX:
        cut = core[:TITLE_MAX]
        core = (cut[:cut.rfind(' ')] if ' ' in cut[20:] else cut) + '…'
    return (core or '보도자료') + ' 발표', 'headline'


def make_title(ev, rows, ov):
    """(목록 제목, 한 줄 요약, 출처, 품질). 출처: content(공고문 주요내용) / override(담당자 사유) / press_labels / headline / heads(대비표) / unknown
    품질: ok / abstract(추상어뿐 → 확인 필요로 대체) / unknown"""
    status = ev['status']
    if status == '보도자료':
        t, src = press_title(ev)
        return t, (short_purpose(ev) if ev.get('purpose') else '')[:SUMMARY_MAX], src, 'ok'
    items = []
    src_items = law_reason_items(ev.get('content') or '') if ev.get('source') == 'law_api' else bullets(ev.get('content') or '')
    for b in src_items:
        t, r = compress_item(b)
        if not t and ev.get('source') == 'law_api' and re.search(r'◇\s*주요내용', ev.get('content') or ''):          # 법제처 '가. 제목(조문)' 머리는 변경 행위 낱말이 없어도 그 자체가 제목이다
            h, r = _strip_article_refs(_clean_item(b))
            h = re.sub(r'\s+', ' ', h).strip(' .,')
            t = h if 4 <= len(h) <= ITEM_MAX + 8 else ''
        if t and len(t) >= 4 and not ABSTRACT_ONLY_RE.match(t):
            items.append((t, r))
    # 같은 뜻·하위 설명 중복 제거 (포함 관계)
    uniq = []
    for t, r in items:
        k = re.sub(r'\s', '', t)
        if any(k in re.sub(r'\s', '', u) or re.sub(r'\s', '', u) in k for u, _ in uniq):
            continue
        uniq.append((t, r))
    # 팀 핵심어(해약률·계리가정 …)가 든 항목을 앞으로 — 제목 첫 자리는 가장 실질적인 변경
    items = sorted(uniq, key=lambda x: 0 if DOMAIN_KW_RE.search(x[0]) else 1)
    ov_reason = (ov or {}).get('reason') or ''
    ov_reason = re.sub(r',\s*확정\)', ')', ov_reason)
    ov_reason = re.sub(r'\(\s*확정[^)]*\)|\s*[\(（]?확정[\)）]?\s*$|\s*—.*$', '', ov_reason).strip(' ,·')
    title, src = '', 'unknown'
    if items:
        title = items[0][0]
        if items[0][1] and len(title) + len(items[0][1][0]) + 2 <= TITLE_MAX and items[0][1][0] not in title:
            title = (title[:-1] + ' · ' + items[0][1][0] + ')') if title.endswith(')') else title + f'({items[0][1][0]})'
        if len(items) > 1 and len(title) <= 34 and len(title) + 3 + len(items[1][0]) <= TITLE_MAX:
            title += ' · ' + items[1][0]
        rest = len(items) - (2 if ' · ' in title else 1)
        if rest > 0:
            title += f' 외 {rest}건'
        src = 'content'
    if not title and ov_reason:
        title, src = ov_reason, 'override'
    if not title and ev.get('source') == 'law_api' and law_reason_items(ev.get('content') or ''):   # 변경 행위 낱말이 없는 제개정이유 — 첫 절을 그대로 (법제처 문장)
        first = re.sub(r'\s+', ' ', law_reason_items(ev['content'])[0]).strip()
        first = re.sub(r'^(?:보험회사로\s*하여금|앞으로는|종전에는)\s*', '', first)
        title = first if len(first) <= 52 else first[:52].rsplit(' ', 1)[0] + '…'
        src = 'reason'
    if not title and ev.get('source') == 'law_api' and ev.get('supplement'):   # 국가법령정보센터 부칙만 있는 세칙 개정 — 부칙에 적힌 별표·조문으로라도 제목을 만든다
        sup_arts = find_articles(ev['supplement'])
        if sup_arts:
            title, src, quality0 = ' · '.join(sup_arts[:3]) + ' 개정 (부칙 적용례 기준 · 개정문 확인 필요)', 'supplement', 'unknown'
    quality = 'ok' if src != 'supplement' else 'unknown'
    if not title:
        heads = [item_heading(a, b) for a, b, _ in rows[:3]]
        if heads:
            title = f"주요 변경내용 확인 필요 — {' · '.join(h[:14] for h in heads[:2])}{' 등' if len(rows) > 2 else ''} {len(rows)}개 조문"
            src, quality = 'heads', 'unknown'
        else:
            title, src, quality = '주요 변경내용 확인 필요', 'unknown', 'unknown'
    elif ABSTRACT_ONLY_RE.match(title):
        title, quality = f'주요 변경내용 확인 필요 — {title}', 'abstract'
    # 한 줄 요약: 변경 항목 2~3개 또는 취지 한 문장
    summary = ''
    if items:
        parts = []
        for t, _ in items[:3]:
            if len(' · '.join(parts + [t])) > SUMMARY_MAX:
                break
            parts.append(t)
        summary = ' · '.join(parts)
    if not summary and ev.get('purpose'):
        summary = short_purpose(ev)
    if not summary and ov_reason and ov_reason != title:
        summary = ov_reason
    title = title[:TITLE_MAX + 12].rstrip(' ·,')
    title = re.sub(r'\s*\([^)]*$', '', title)          # 잘린 괄호 꼬리 제거
    return title, summary[:SUMMARY_MAX], src, quality


JOINT_PRESS_SIM = 0.9      # 같은 날 헤드라인 유사도가 이 이상이면 금융위·금감원 공동 보도자료 한 건으로 본다


def _headline_key(ev):
    h = re.sub(r'^\s*[\[(【]\s*보도\s*(?:자료|참고)\s*[\])】]\s*', '', ev.get('list_title') or '')
    h = re.split(r'\s[-–]\s', h)[0]                     # 금융위 쪽 부제('- ｢…방안｣ 마련') 는 뺀다
    return re.sub(r'[^가-힣A-Za-z0-9]', '', h).lower()


def _day_num(d):
    import datetime as _dt
    try:
        return _dt.date.fromisoformat(d).toordinal()
    except Exception:
        return 0


def merge_joint_press(events):
    """금융위·금감원이 같은 날 같은 제목으로 낸 공동 보도자료를 한 건으로 묶는다. 본문·첨부가 많은 쪽(보통 금감원)이 대표(primary),
    나머지는 _merged_into 로 표시만 한다(삭제 아님). 대표 건에는 두 기관의 원문 링크를 모두 둔다 (joint_sources)."""
    press = sorted([e for e in events if e['status'] == '보도자료' and e.get('date')], key=lambda e: e['date'])
    merged = 0
    used = set()
    if True:
        group = press
        for i, a in enumerate(group):
            if a['id'] in used or a.get('_merged_into'):
                continue
            twins = [a]
            for b in group[i + 1:]:
                # 같은 기관 게시물끼리는 묶지 않는다. 배포일은 하루까지 어긋날 수 있다 (금융위 11/7 · 금감원 11/8)
                if b['id'] in used or a.get('source') == b.get('source') or abs(_day_num(a['date']) - _day_num(b['date'])) > 1:
                    continue
                ka, kb = _headline_key(a), _headline_key(b)
                if ka and kb and difflib.SequenceMatcher(None, ka, kb, autojunk=False).ratio() >= JOINT_PRESS_SIM:
                    twins.append(b); used.add(b['id'])
            if len(twins) < 2:
                continue
            richness = lambda e: len(e.get('purpose') or '') + len(e.get('body') or '') + sum(1 for x in e.get('attachments', []) if x.get('extracted')) * 500
            primary = max(twins, key=richness)
            primary['joint_sources'] = [{'label': t['source_label'], 'url': t['url'], 'event_id': t['id']} for t in twins if t is not primary]
            # 제목·요약은 글머리 꼬리표가 있는 쪽(보통 금감원 본문 요약)이 낫다 — 대표 건에 취지문이 없으면 가져온다
            if not (primary.get('purpose') or '').strip():
                best = max((t for t in twins if t is not primary), key=lambda t: len(t.get('purpose') or ''), default=None)
                if best and (best.get('purpose') or '').strip():
                    primary['purpose'] = best['purpose']
            for t in twins:
                if t is not primary:
                    t['_merged_into'] = primary['id']; merged += 1
    return merged


def notice_decision_diff(notice, decided):
    """예고안 ↔ 확정본 대비표 차이: 조문 머리 기준으로 (항목, 예고안 줄수, 확정본 줄수, 판정) 목록 + 문구가 달라진 항목 수"""
    nr, _ = compare_rows(notice); dr, _ = compare_rows(decided)
    key = lambda h: re.sub(r'\s', '', re.sub(r'\(.*?\)', '', h))[:24]
    nmap = {}; dmap = {}
    for ca, cb, _ in nr:
        nmap.setdefault(key(item_heading(ca, cb)), []).append(cb)
    for ca, cb, _ in dr:
        dmap.setdefault(key(item_heading(ca, cb)), []).append(cb)
    rows = []
    for k in list(dict.fromkeys(list(nmap.keys()) + list(dmap.keys()))):
        a, b = nmap.get(k), dmap.get(k)
        if a and not b:
            rows.append((k, len(a), 0, '확정본에서 제외'))
        elif b and not a:
            rows.append((k, 0, len(b), '확정본에서 추가'))
        else:
            ta, tb = norm_line('\n'.join(a)), norm_line('\n'.join(b))
            r = difflib.SequenceMatcher(None, ta, tb, autojunk=False).ratio() if ta and tb else 1.0
            la, lb = sum(len(split_lines(x)) for x in a), sum(len(split_lines(x)) for x in b)
            rows.append((k, la, lb, '동일' if r >= 0.98 else f'문구 변경 (유사도 {r:.2f})'))
    return rows


def build(ev, css, related, rules=None, decided_after=None):
    status = ev['status']
    text = all_text(ev)
    arts = find_articles(text)
    eff, eff_rule, eff_notes, sup = find_effective(ev, effective_text(ev)) if status != '보도자료' else ('', '', '', '')   # 보도자료 본문의 '…부터 시행' 은 규정 시행일이 아니다
    if eff and not ev.get('date_effective'):
        ev = {**ev, 'date_effective': eff}
    if eff_notes and not ev.get('date_effective_notes'):
        ev = {**ev, 'date_effective_notes': eff_notes}
    ev['date_effective_rule'] = eff_rule
    if sup and not ev.get('supplement'):
        ev = {**ev, 'supplement': sup, '_supplement_from': '예고안 첨부'}
    areas, systems = impacts(text)
    rows, unchanged = compare_rows(ev)
    counts = {k: 0 for k in KIND_ORDER}
    line_counts = {k: 0 for k in KIND_ORDER}
    item_tables = []      # (cls, lbl, heading, table_html, line_counts)
    for ca, cb, _ in rows:
        cls, lbl = classify(ca, cb)
        counts[cls] += 1
        t_html, lc = cmp_table(ca, cb)
        for k in KIND_ORDER:
            line_counts[k] += lc[k]
        item_tables.append((cls, lbl, item_heading(ca, cb), t_html, lc))
    strong = ' '.join(x for x in [ev.get('list_title', ''), ev.get('purpose', ''), ev.get('content', ''), (ev.get('body') or '')[:1500]] if x)
    if not strong.strip():
        strong = ' '.join(item_heading(ca, cb) for ca, cb, _ in rows[:40])
    relevance, rel_reason = classify_relevance(ev, strong, related, rules or {})
    ev['_relevance'] = (relevance, rel_reason)
    paras_src = next((a for a in ev.get('attachments', []) if a.get('extracted') and a['extracted'].get('paras')), None)
    secs = sections_from_paras(paras_src['extracted']['paras']) if paras_src else {}
    is_notice = status in ('사전예고', '입법예고')
    if status == '보도자료' and re.match(r'^\s*※', ev.get('purpose') or ''):   # 본문이 '※ 자세한 내용은 첨부파일 참고' 뿐인 금감원 보도자료
        ev = {**ev, 'purpose': ''}
    ov = ((rules or {}).get('overrides') or {}).get(ev['id'], {})
    # 목록 제목 = 대상 + 실질 변경 (지시서 §12). 선행 예고의 취지를 제목으로 물려받지 않는다 — 다른 건일 수 있다
    list_title, summary_line, title_source, title_quality = make_title(ev, rows, ov)
    title_core = list_title
    analysis_kind = '사전예고안 분석' if is_notice else ('보도자료 정리' if status == '보도자료' else '확정 개정 분석')
    h1 = f"[{analysis_kind}] {ev['reg_name']} — {list_title}"
    subt_bits = [ev['reg_name']] + ([' · '.join(arts[:4])] if arts else []) + [f"{fmt_date(ev.get('date'))} {STATUS_LABEL.get(status, status)}"]
    if ev.get('date_comment_due'):
        subt_bits.append(f"의견제출 {fmt_date(ev['date_comment_due'])}까지")
    if ev.get('date_effective'):
        subt_bits.append((f"시행 예정 {planned_label(ev['date_effective'])} (예고안 기준)" if is_notice else f"시행 {fmt_date(ev['date_effective'])} ({ev.get('date_effective_source') or '발령문 기준'})"))
    elif is_notice and eff_rule:
        subt_bits.append(f"시행 예정: {eff_rule} (예고안 기준)")
    lead = ev.get('purpose') or (ev.get('body') or '')[:160] or ev.get('list_title', '')
    lead = re.sub(r'^[□◦○ㅇ\s]+', '', lead)

    # 3차(P0-7): 문서 성격 / 규정 상태 / 시행 여부 / 적용 기준일 / 최종 원문 확인 여부 — 결론 첫 표 5항목 + 첫 두 문장
    notice_label = {'사전예고': '사전예고안', '입법예고': (ev.get('notice_kind') or '입법예고') + '안'}.get(status, '')
    doc_nature = {'사전예고': '사전예고문 (금감원 시행세칙 개정안)', '입법예고': f"{ev.get('notice_kind') or '입법예고'}문 (개정안)", '공포': '고시문 (확정 · 발령)',
                  '시행': '확정 개정 게시문 (발령)', '보도자료': '보도자료 (설명 자료, 조문 아님)', '철회': '철회 공고'}.get(status, status)
    eff_planned = eff if (is_notice and eff) else ''
    if is_notice:
        reg_state = '미확정 — ' + ('예고 중 (의견제출 ' + fmt_date(ev['date_comment_due']) + '까지)' if ev.get('date_comment_due') else '예고 중')
        if decided_after:
            reg_state = f"확정 발령됨 — {fmt_date(decided_after.get('date'))} {STATUS_LABEL.get(decided_after['status'], '')} (확정본 리포트 참조)"
        eff_lbl = planned_label(eff_planned) if eff_planned else eff_rule
        eff_text = f"미시행 — 시행 예정 {eff_lbl} (예고안 부칙 기준 · 확정 아님)" if eff_planned else (f"미시행 — 시행 예정: {eff_rule} (예고안 부칙 기준 · 확정 아님)" if eff_rule else '미시행 — 예고안에 시행일 문구 없음 (확정본 부칙에서 정함)')
        apply_date = f"{eff_lbl} (예정 · 확정 전 적용하지 않음)" if (eff_planned or eff_rule) else '미확인 (확정 전)'
    elif status == '보도자료':
        reg_state, eff_text, apply_date = '해당 없음 — 규정이 아닌 설명 자료', '해당 없음', '해당 없음 (연결된 예고·발령 건에서 확인)'
    else:
        reg_state = f"확정 (발령) — {fmt_date(ev.get('date'))} {'고시' if status == '공포' else '개정 게시'}"
        eff_src = ev.get('date_effective_source') or '발령문 본문 추출'
        eff_ok = eff_src.startswith('국가법령정보센터')
        eff_text = (f"시행일 {fmt_date(ev['date_effective'])} ({eff_src}{' 확인' if eff_ok else ' · 부칙 확인 필요'})" + (f" · {ev['date_effective_notes']}" if ev.get('date_effective_notes') else '')) if ev.get('date_effective') else (f"시행일: {eff_rule} (발령문 부칙)" if eff_rule else '시행일 미확인 — 부칙에서 확인')
        apply_date = (fmt_date(ev['date_effective']) + (' (부칙 확인됨)' if eff_ok else ' (부칙 확인 후 확정)')) if ev.get('date_effective') else (f'{eff_rule} (부칙)' if eff_rule else '미확인')
    verify = '원문 게시물·첨부 자동 수집본 — 담당자 원문 대조 미완료'
    if is_notice:
        legal = (f"본 자료는 {fmt_date(ev.get('date'))} {notice_label} 기준 분석이다. "
                 + (f"확정 발령은 {fmt_date(decided_after.get('date'))}에 확인됐으며 확정본 조문은 확정 건 리포트에서 본다." if decided_after
                    else (f"예고안 부칙은 {eff_lbl} 시행을 예정하고 있으나 확정 발령·시행일은 미확인이며, 확정본 확인 전에는 현행 산출기준에 적용하지 않는다." if eff_planned
                          else (f"예고안 부칙은 시행일을 '{eff_rule}'(으)로 정하고 있어 확정 발령일이 곧 시행 시점이며, 확정본 확인 전에는 현행 산출기준에 적용하지 않는다." if eff_rule
                                else "예고안에 시행일 문구가 없어 확정 발령·시행일은 미확인이며, 확정본 확인 전에는 현행 산출기준에 적용하지 않는다."))))
    elif status == '보도자료':
        legal = f"본 자료는 {fmt_date(ev.get('date'))} 보도자료 정리다. 규정 조문이 아니고 효력도 없으며, 실제 개정 상태는 연결된 예고·발령 건에서 확인한다."
    else:
        legal = (f"본 자료는 {fmt_date(ev.get('date'))} 확정 {'고시' if status == '공포' else '개정 게시'}(발령) 기준 분석이다. "
                 + ((f"시행일은 {fmt_date(ev['date_effective'])}({ev.get('date_effective_source') or '발령문 본문 추출'})이며 " + ('경과조치만 확인하고 그 날부터 산출기준에 적용한다.' if (ev.get('date_effective_source') or '').startswith('국가법령정보센터') else '부칙·경과조치를 확인한 뒤 그 날부터 산출기준에 적용한다.')) if ev.get('date_effective')
                    else "시행일은 미확인이며 부칙에서 확인하기 전에는 적용 시점을 확정하지 않는다."))
    # 결론 요약표
    sumrows = [('문서 성격', doc_nature), ('규정 상태', reg_state), ('시행 여부', eff_text), ('적용 기준일', apply_date), ('최종 원문 확인 여부', verify),
               ('규정', f"{ev['reg_name']}" + (f" · {' · '.join(arts[:6])}" if arts else '')),
               ('단계', STATUS_LABEL.get(status, status) + (f" ({ev.get('notice_kind')})" if ev.get('notice_kind') else '')),
               ('일자', ('예고 ' if is_notice else ('고시 ' if status == '공포' else ('배포 ' if status == '보도자료' else '게시 '))) + fmt_date(ev.get('date')))]
    if ev.get('date_comment_due'):
        sumrows.append(('의견제출 시한', fmt_date(ev['date_comment_due'])))
    if rows:
        sumrows.append(('변경 규모', f"조문 {len(rows)}개 — {counts_text(counts)}" + (f" · 변경 없음 {len(unchanged)}" if unchanged else '')
                        + f" / 줄 단위 {counts_text(line_counts)} (조문 단위와 줄 단위는 서로 다른 집계라 합산하지 않는다 · 첨부 대비표 기준)"))
    sumrows.append(('계리결산팀 관련성', f"{relevance} — {rel_reason}"))
    if areas:
        sumrows.append(('영향 영역', ' · '.join(areas)))
    sumrows.append(('소관', ev.get('authority') or '—'))
    if related and ev.get('_link_confidence') != 'low':
        sumrows.append((LINK_CONFIDENCE_LABEL.get(ev.get('_link_confidence') or 'medium'),
                        f"{fmt_date(related.get('date'))} {related['reg_name']} {STATUS_LABEL.get(related['status'], related['status'])} — 근거: {ev.get('_link_evidence') or '조문 겹침'}"))

    # 2장 주요 내용
    main_items = bullets(ev.get('content') or '')
    for k, v in secs.items():
        if re.search(r'주요\s*내용|개정\s*내용|변경\s*내용', k):
            main_items = [re.sub(r'^[□◦○ㅇ\s\U000f0000-\U000fffff]+', '', p) for p in v if len(p) > 3] or main_items
            break
    if not main_items and ev.get('body'):
        main_items = bullets(ev['body'][:3000])
    reason_items = []
    for k, v in secs.items():
        if re.search(r'취지|이유|배경', k):
            reason_items = [re.sub(r'^[□◦○ㅇ\s]+', '', p) for p in v if len(p) > 3]
            break

    diff_rows = notice_decision_diff(related, ev) if (related and not is_notice and status != '보도자료' and ev.get('_link_confidence') == 'high') else []

    # 조치 사항
    acts = []
    if is_notice:
        acts.append(('확정 공포 조문과 대조', '사전예고안은 의견수렴 결과 문구가 바뀔 수 있다. 공포·시행 시 확정본과 이 대비표를 다시 맞춘다.', '대'))
    for a in areas[:4]:
        acts.append((f'{a} 영향 분석', f'{a} 관련 현행 산출 로직·가정 테이블과 개정 내용을 대조해 변경 필요 항목을 뽑는다.', '중'))
    if systems:
        acts.append((' · '.join(systems) + ' 반영 계획', '시행일' + (f'({fmt_date(ev["date_effective"])})' if ev.get('date_effective') else '') + ' 전에 반영 범위·일정·담당을 정한다.', '중'))
    acts.append(('내부 공유', '계리결산팀 주간업무 보고에 개정 요지와 조치 항목을 등록한다.', '소'))

    H = []
    H.append(f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">')
    H.append(f'<title>{esc(h1)}</title><link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet"><style>{css}</style></head><body><div class="wrap">')
    H.append(f'<div class="top"><span class="tag">{esc(STATUS_TAG.get(status, status))}</span><h1>{esc(h1)}</h1><p class="subt">{esc(" · ".join(subt_bits))}</p></div>')
    nav = ['<a href="#c">결론</a>', '<a href="#1">개요</a>', '<a href="#2">주요 내용</a>']
    if rows:
        nav.append('<a href="#3">신·구 조문 대비</a>')
    if diff_rows:
        nav.append('<a href="#3a">예고안 대비 확정본</a>')
    nav += ['<a href="#4">조치 사항</a>', '<a href="#a">부록</a>']
    H.append(f'<div class="nav"><div class="in">{"".join(nav)}</div></div><div class="sec">')

    # 결론
    H.append('<h2 id="c">결론</h2>')
    H.append(f'<p class="lead"><span class="who fact">원문 사실</span>{esc(legal)}</p>')
    H.append(f'<p>{esc(lead)}</p>')
    H.append('<div class="tw"><table class="wrap-ok2"><thead><tr><th>구분</th><th>내용</th></tr></thead><tbody>')
    for i, (k, v) in enumerate(sumrows):
        H.append(f'<tr{" class=hl" if i == 0 else ""}><td class="l"><b>{esc(k)}</b></td><td class="l">{esc(v)}</td></tr>')
    H.append('</tbody></table></div>')
    if relevance == '무관':
        H.append('<div class="callout neutral"><b>계리결산팀 업무와 직접 관련이 없는 개정이다.</b><p>IFRS17 부채결산·계리적 가정·경제적 가정·계리모델 현금흐름에 영향을 주지 않는다 (' + esc(rel_reason) + '). 참고용으로만 보관한다.</p></div>')
    elif relevance == '참고':
        H.append('<div class="callout neutral"><b>계리결산팀 참고 사항이다.</b><p>' + esc(rel_reason) + '. 결산 산출물·지급여력 등 인접 영역이라 내용은 확인하되 모델 변경 대상은 아니다.</p></div>')
    if is_notice and decided_after:
        H.append(f'<div class="callout ok"><b>이 예고안은 {fmt_date(decided_after.get("date"))}에 확정 발령됐다.</b><p>확정본 조문·시행일은 확정 건 리포트(규정 개정이력 › 진행 현황에서 연결)에서 본다. 예고안과 확정본의 차이는 확정 건 리포트 3-A 절에 있다.</p></div>')
    elif is_notice:
        H.append('<div class="callout"><b>사전예고안이다.</b><p>확정 공포 조문과 다를 수 있으므로 적용 전 확정본 대조가 필요하다. 의견제출 시한' + (f' {fmt_date(ev["date_comment_due"])}' if ev.get('date_comment_due') else '') + ' 이후 금감원·금융위 게시판에서 확정 여부를 확인한다.</p></div>')
    elif status == '공포':
        H.append('<div class="callout ok"><b>확정 고시다.</b><p>금융위원회 고시로 확정된 내용이다. 시행일과 경과규정(부칙)을 확인해 적용 시점을 맞춘다.</p></div>')
    elif status == '보도자료':
        H.append('<div class="callout neutral"><b>보도자료다.</b><p>제도 방향·의결 사실을 알리는 자료로 조문 자체가 아니다. 규정 개정이력 화면의 진행 현황에서 같은 규정의 예고·확정 건과 함께 본다.</p></div>')
    else:
        H.append('<div class="callout ok"><b>확정 개정이다.</b><p>금융감독원이 제·개정 결과를 게시한 건이다. 첨부 신·구 조문 대비표가 최종 조문이다.</p></div>')

    # 1. 개요
    H.append('<h2 id="1">1. 개정 개요</h2><h3>1-1. 어떤 규정이 바뀌나</h3>')
    H.append(f'<p>{esc(ev["reg_name"])}' + (f' 중 <strong>{esc(" · ".join(arts[:6]))}</strong>' if arts else '') + f' 을(를) 대상으로 한다. 소관은 {esc(ev.get("authority") or "—")} 이다.</p>')
    if reason_items:
        H.append('<div class="callout neutral"><b>개정 취지</b>' + ''.join(f'<p>{esc(p)}</p>' for p in reason_items[:4]) + '</div>')
    H.append('<h3>1-2. 일정</h3><div class="tw"><table class="mid wrap-ok"><thead><tr><th>단계</th><th>시점</th><th>내용</th></tr></thead><tbody>')
    if ev.get('date_notice'):
        H.append(f'<tr><td class="l">{"사전예고" if status == "사전예고" else esc(ev.get("notice_kind") or "입법예고")}</td><td>{fmt_date(ev["date_notice"])}</td><td class="l">개정안 공고 · 의견 수렴</td></tr>')
    if ev.get('date_comment_due'):
        H.append(f'<tr><td class="l">의견제출</td><td>{fmt_date(ev["date_comment_due"])}</td><td class="l">도착 기준</td></tr>')
    if ev.get('date_promulgated'):
        H.append(f'<tr><td class="l">{"고시" if status == "공포" else "개정 게시"}</td><td>{fmt_date(ev["date_promulgated"])}</td><td class="l">{esc(ev.get("gazette_no") and ("금융위원회 고시 제" + ev["gazette_no"] + "호") or "확정 조문 공개")}</td></tr>')
    if ev.get('date_press'):
        H.append(f'<tr><td class="l">보도자료</td><td>{fmt_date(ev["date_press"])}</td><td class="l">{esc(ev.get("authority") or "")} 배포</td></tr>')
    if ev.get('date_effective') and is_notice:
        H.append(f'<tr><td class="l">시행 예정</td><td>{planned_label(ev["date_effective"])}</td><td class="l">예고안 부칙 기준 · 확정 아님 (확정본 부칙에서 다시 정함){(" · " + esc(ev["date_effective_notes"])) if ev.get("date_effective_notes") else ""}</td></tr>')
    elif is_notice and eff_rule:
        H.append(f'<tr><td class="l">시행 예정</td><td>{esc(eff_rule)}</td><td class="l">예고안 부칙 기준 · 날짜 대신 조건으로 정함 (확정 발령 시 확정){(" · " + esc(ev["date_effective_notes"])) if ev.get("date_effective_notes") else ""}</td></tr>')
    elif ev.get('date_effective'):
        src = ev.get('date_effective_source') or '발령문 본문 추출'
        H.append(f'<tr class="hl"><td class="l">시행</td><td>{fmt_date(ev["date_effective"])}</td><td class="l">{esc(src)}{" 확인" if src.startswith("국가법령정보센터") else " · 부칙 확인 필요"}{(" · " + esc(ev["date_effective_notes"])) if ev.get("date_effective_notes") else ""}</td></tr>')
    elif not is_notice and status != '보도자료' and eff_rule:
        H.append(f'<tr class="hl"><td class="l">시행</td><td>{esc(eff_rule)}</td><td class="l">발령문 부칙 — 날짜 대신 조건으로 정함</td></tr>')
    elif not is_notice and status != '보도자료':
        H.append('<tr><td class="l">시행</td><td>—</td><td class="l">부칙에서 확인 필요 (자동 추출 안 됨)</td></tr>')
    H.append('</tbody></table></div>')
    if ev.get('supplement'):
        H.append(f'<div class="callout neutral"><span class="who fact">원문 사실</span><b>부칙{" (예고안 첨부)" if ev.get("_supplement_from") else ""}</b><p>{esc(ev["supplement"][:600])}</p></div>')
    if ev.get('contact'):
        H.append(f'<p class="note">담당 · {esc(ev["contact"])}</p>')

    # 2. 주요 내용
    H.append('<h2 id="2">2. 주요 내용 <span class="who fact">원문 사실</span></h2>')
    if main_items:
        H.append('<div class="tw"><table class="wrap-ok2"><thead><tr><th>#</th><th>내용 (공고문 주요 내용 그대로)</th></tr></thead><tbody>')
        for i, p in enumerate(main_items[:20], 1):
            H.append(f'<tr><td>{i}</td><td class="l">{esc(p)}</td></tr>')
        H.append('</tbody></table></div>')
    else:
        H.append('<p>공고문에 요약된 주요 내용이 없다. 부록의 원문 추출 전문과 첨부 파일을 본다.</p>')
    if areas:
        H.append(f'<p><span class="who ai">AI 해석</span>계리결산 관점의 영향 영역은 <strong>{esc(" · ".join(areas))}</strong> 이고, 손볼 시스템은 {esc(" · ".join(systems) or "—")} 이다. 본문 키워드로 자동 분류한 것이며 BEL·CSM·손실요소 영향은 내부 산출자료가 없어 <b>영향 가능성 · 정량 미산출</b>이다. <span class="who todo">당사 확인 필요</span></p>')

    # 3. 신·구 조문 대비
    if rows:
        H.append('<h2 id="3">3. 신·구 조문 대비</h2>')
        H.append(f'<p>첨부 대비표에서 추출해 조문 단위로 묶은 {len(rows)}개 항목이다. 현행과 개정안을 <strong>줄 단위로 맞춰</strong> 놓았고, 왼쪽 구분 칸이 그 줄의 변경 종류다. '
                 '바뀐 낱말은 현행 쪽은 <em class="da">붉은 밑줄</em>, 개정안 쪽은 <em>초록 밑줄</em>로 표시했다. 개정안 칸의 <span class="mk">(현행과 같음)</span> 은 원문의 점선(———) 자리로 현행 문구가 그대로 유지된다는 뜻이고, 〈신설〉·〈삭제〉·〈이동〉 표시는 원문 그대로다.'
                 + (f' 바뀐 내용이 없는 {len(unchanged)}개 조문(' + esc(' · '.join(unchanged[:8])) + ('…' if len(unchanged) > 8 else '') + ')은 맥락용이라 뺐다.' if unchanged else '') + '</p>')
        # 3-0. 변경 이력 요약표: 항목별 종류 + 줄 단위 집계
        H.append('<h3>3-0. 변경 이력 요약</h3><div class="tw"><table class="mid wrap-ok"><thead><tr><th>#</th><th>조문 · 항목</th><th>종류</th><th>줄 단위 변경</th></tr></thead><tbody>')
        for i, (cls, lbl, head, _, lc) in enumerate(item_tables, 1):
            H.append(f'<tr><td>{i}</td><td class="l">{esc(head)}</td><td><span class="bdg {cls}">{lbl}</span></td><td class="l">{esc(counts_text(lc))}' + (f' <span class="mk">(동일 {lc["s"]})</span>' if lc['s'] else '') + '</td></tr>')
        H.append(f'<tr class="tot"><td></td><td class="l">합계 {len(rows)}개 항목</td><td class="l">{esc(counts_text(counts))}</td><td class="l">{esc(counts_text(line_counts))}</td></tr></tbody></table></div>')
        H.append('<p class="note">종류 판정: 〈신설〉·현행 공란 → 신설, 〈삭제〉·개정안 공란 → 삭제, "…에서 이동" 표기 → 이동, 그 외 → 변경. 줄 짝짓기는 머리번호(①, 1., 가.)와 문구 유사도로 자동 정렬한 것이라 원문과 다르면 첨부를 본다.</p>')
        for i, (cls, lbl, head, t_html, lc) in enumerate(item_tables[:MAX_ROWS_IN_REPORT], 1):
            H.append(f'<h3>3-{i}. <span class="bdg {cls}">{lbl}</span>{esc(head)} <span class="hsub">{esc(counts_text(lc))}</span></h3>')
            H.append(t_html)
        if len(rows) > MAX_ROWS_IN_REPORT:
            H.append(f'<p class="note">나머지 {len(rows) - MAX_ROWS_IN_REPORT}개 항목은 부록 C 에 있다.</p>')
    else:
        H.append('<h2 id="3">3. 신·구 조문 대비</h2><p>첨부 파일에서 현행·개정안 대비표를 자동으로 추출하지 못했다' + (' (hwp 바이너리 또는 PDF).' if ev.get('attachments') else ' (첨부 없음).') + ' 부록의 첨부 링크에서 원문을 연다.</p>')

    if diff_rows:
        changed = [r for r in diff_rows if r[3] != '동일']
        H.append(f'<h2 id="3a">3-A. 예고안 대비 확정본 차이 <span class="who ai">AI 해석</span></h2>')
        H.append(f'<p>{fmt_date(related.get("date"))} {esc(STATUS_LABEL.get(related["status"], ""))}의 대비표와 이 확정본 대비표를 조문 머리 기준으로 맞춘 결과다. 항목 {len(diff_rows)}개 중 {len(changed)}개가 다르다'
                 + (' (문구가 바뀌었거나 항목이 추가·제외됨). 바뀐 항목은 확정본 조문을 기준으로 다시 본다.' if changed else '. 예고안과 확정본의 조문 구성이 같다 — 단, 줄 단위 문구 유사도 0.98 이상을 동일로 본 것이라 세부 문구는 3장에서 확인한다.') + '</p>')
        H.append('<div class="tw"><table class="mid wrap-ok"><thead><tr><th>조문 · 항목</th><th>예고안 줄</th><th>확정본 줄</th><th>판정</th></tr></thead><tbody>')
        for k, la, lb, verdict in diff_rows[:60]:
            H.append(f'<tr{" class=hl" if verdict != "동일" else ""}><td class="l">{esc(k)}</td><td>{la}</td><td>{lb}</td><td class="l">{esc(verdict)}</td></tr>')
        H.append('</tbody></table></div>')
    # 4. 조치 사항
    H.append('<h2 id="4">4. 조치 사항 <span class="who todo">당사 확인 필요</span></h2><div class="tw"><table class="act wrap-ok"><thead><tr><th>순위</th><th>과제</th><th>영향</th></tr></thead><tbody>')
    for i, (t, d, lv) in enumerate(acts, 1):
        H.append(f'<tr{" class=hl" if i == 1 else ""}><td>{i}</td><td class="l"><b>{esc(t)}</b><span class="sub2">{esc(d)}</span></td><td>{lv}</td></tr>')
    H.append('</tbody></table></div><p class="note">조치 항목은 개정 내용 키워드로 자동 생성한 초안이다. 규정 개정이력 화면에서 담당·기한·상태를 관리한다.</p>')

    # 부록
    H.append('<h2 id="a">부록</h2>')
    H.append('<details><summary>A. 출처 · 첨부 파일</summary><div class="body">')
    H.append(f'<p><a href="{esc(ev["url"])}" target="_blank" rel="noopener">{esc(ev["source_label"])} 원문 게시물 ↗</a>' + ''.join(f' · <a href="{esc(j["url"])}" target="_blank" rel="noopener">{esc(j["label"])} (공동 배포) ↗</a>' for j in ev.get('joint_sources', [])) + '</p>')
    if ev.get('attachments'):
        H.append('<div class="tw"><table class="wrap-ok2"><thead><tr><th>#</th><th>파일</th><th>추출</th></tr></thead><tbody>')
        for i, a in enumerate(ev['attachments'], 1):
            ex = a.get('extracted')
            st = f"문단 {len(ex['paras'])} · 표 {len(ex['tables'])}" if ex else ('실패: ' + a['error'][:40] if a.get('error') else '미추출')
            H.append(f'<tr><td>{i}</td><td class="l"><a href="{esc(a["url"])}" target="_blank" rel="noopener">{esc(a["name"])}</a></td><td class="l">{esc(st)}</td></tr>')
        H.append('</tbody></table></div>')
    H.append('</div></details>')
    if paras_src:
        H.append(f'<details><summary>B. 원문 추출 전문 — {esc(paras_src["name"][:50])}</summary><div class="body">')
        for p in paras_src['extracted']['paras'][:400]:
            H.append(f'<p>{esc(p)}</p>')
        H.append('</div></details>')
    elif ev.get('body'):
        H.append('<details><summary>B. 공고문 전문</summary><div class="body">' + ''.join(f'<p>{esc(p)}</p>' for p in bullets(ev['body'])[:60]) + '</div></details>')
    if len(rows) > MAX_ROWS_IN_REPORT:
        H.append('<details><summary>C. 신·구 조문 대비 — 나머지 항목</summary><div class="body">')
        for i, (cls, lbl, head, t_html, lc) in enumerate(item_tables[MAX_ROWS_IN_REPORT:], MAX_ROWS_IN_REPORT + 1):
            H.append(f'<h3>3-{i}. <span class="bdg {cls}">{lbl}</span>{esc(head)} <span class="hsub">{esc(counts_text(lc))}</span></h3>')
            H.append(t_html)
        H.append('</div></details>')
    H.append('<p class="note">이 리포트는 공개 게시판(금융감독원·금융위원회)의 공고문과 첨부에서 자동 생성했다. 해석·분석이 아닌 원문 정리이며, 확정본은 원문 링크에서 확인한다.</p>')
    H.append('</div></div></body></html>')

    meta = {
        'title': h1, 'articles': arts, 'impact_areas': areas, 'impact_systems': systems,
        'change_new': counts['n'], 'change_mod': counts['c'], 'change_del': counts['m'], 'change_move': counts['v'], 'compare_rows': len(rows),
        'line_counts': {KIND_LABEL[k]: line_counts[k] for k in KIND_ORDER},
        'summary': (ev.get('purpose') or lead)[:400], 'actions': [{'no': i + 1, 'task': t, 'owner': '', 'due': '', 'state': '대기'} for i, (t, _, _) in enumerate(acts)],
        'tags': list(dict.fromkeys([ev['reg_name']] + areas[:3] + arts[:3])),
        'date_effective': ev.get('date_effective', ''), 'date_effective_rule': eff_rule, 'date_effective_notes': ev.get('date_effective_notes') or '', 'supplement': (ev.get('supplement') or '')[:800],
        'relevance': relevance, 'relevance_reason': rel_reason,
        'list_title': list_title, 'summary_line': summary_line, 'title_source': title_source, 'title_quality': title_quality,
        'related_notice_id': ev.get('related_notice_id'), 'related_confidence': ev.get('_link_confidence') or '', 'related_evidence': ev.get('_link_evidence') or '',
        'unchanged': len(unchanged),
        'analysis_kind': analysis_kind, 'legal_status': legal, 'joint_sources': ev.get('joint_sources', []), 'merged_into': ev.get('_merged_into'),
        'decided_after_id': decided_after['id'] if decided_after else None, 'diff_changed': len([r for r in diff_rows if r[3] != '동일']) if diff_rows else None,
    }
    return '\n'.join(H), meta


def main():
    ap = argparse.ArgumentParser(description='규정 개정 이벤트 JSON → 리포트 HTML')
    ap.add_argument('--data', required=True, help='scripts/collect_reg_history.py 산출 JSON')
    ap.add_argument('--out-dir', required=True, help='HTML 출력 폴더')
    ap.add_argument('--ids', default='', help='특정 이벤트 id 만 (쉼표)')
    a = ap.parse_args()
    events = json.load(open(a.data, encoding='utf-8'))
    by_id = {e['id']: e for e in events}
    want = set(x.strip() for x in a.ids.split(',') if x.strip())
    css = load_css()
    rules = load_relevance_rules()
    relink(events)
    merged = merge_joint_press(events)
    print(f'공동 보도자료 통합 {merged}건', file=sys.stderr)
    decided_of = {e['related_notice_id']: e for e in events if e.get('related_notice_id') and e.get('_link_confidence') == 'high' and e['status'] in ('공포', '시행')}
    GOSI_EFFECTIVE.clear()
    GOSI_EFFECTIVE.update({e['date']: e['date_effective'] for e in events if e['status'] in ('공포', '시행') and e.get('reg_name') == '보험업감독규정' and e.get('date') and e.get('date_effective')})
    os.makedirs(a.out_dir, exist_ok=True)
    index = {}
    # 예고 → 확정 순으로 돌려야 확정 건이 선행 예고의 관련성 판정을 준용할 수 있다
    order = sorted(events, key=lambda e: (0 if e['status'] in ('사전예고', '입법예고') else 1, e.get('date', '')))
    for ev in order:
        if want and ev['id'] not in want:
            continue
        # low(규정명·날짜만) 연결은 제목·관련성 준용에 쓰지 않는다 — 다른 개정 건일 가능성이 크다
        related = by_id.get(ev.get('related_notice_id')) if ev.get('_link_confidence') in ('high', 'medium') else None
        htmlstr, meta = build(ev, css, related, rules, decided_of.get(ev['id']))
        fn = os.path.join(a.out_dir, ev['id'] + '.html')
        open(fn, 'w', encoding='utf-8').write(htmlstr)
        index[ev['id']] = {'file': fn, **meta}
        print(f"  {ev['id']} {ev.get('date')} {ev['status']} [{meta['relevance']}] rows={meta['compare_rows']}+{meta['unchanged']} → {meta['title'][:50]}", file=sys.stderr)
    # 부분 생성(--ids) 때 기존 색인을 보존
    idx_path = os.path.join(a.out_dir, '_index.json')
    if want and os.path.exists(idx_path):
        old = json.load(open(idx_path, encoding='utf-8')); old.update(index); index = old
    json.dump(index, open(idx_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'완료: {len(index)}건 → {a.out_dir}', file=sys.stderr)


if __name__ == '__main__':
    main()
