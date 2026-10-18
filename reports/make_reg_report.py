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


EFFECTIVE_RE = re.compile(r'(\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})\s*일?\s*부터\s*시행')


def find_effective(ev, text):
    """부칙 문구('… 2026년 6월 30일부터 시행한다') 에서 시행일 추출. 공고문의 '고시한 날부터 시행' 은 게시일로 본다."""
    if ev.get('date_effective'):
        return ev['date_effective']
    m = EFFECTIVE_RE.search(text)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    if ev['status'] in ('공포', '시행') and re.search(r'(?:고시|공포|발령)한\s*날부터\s*시행', text):
        return ev.get('date', '')
    return ''


def short_purpose(ev):
    p = ev.get('purpose') or ''
    p = re.sub(r'^[\sㅁ□◦○ㅇ▪■•\-]*(?:\d+\.\s*|[가-힣]\.\s)?', '', p)   # 글머리표·번호 제거
    p = re.split(r'(?<=[다요])\s|\s\(|\s에\s따라', p)[0] if p else ''
    if not p:
        p = ev.get('list_title', '')
    return (p[:70] + '…') if len(p) > 70 else p


def relink(events):
    """확정 건(공포·시행) ↔ 선행 예고 연결. 같은 규정, 확정일 이전 240일 안, 의견제출 시한이 확정일 이전인 예고 중
    조문·별표 겹침이 가장 많은 것(없으면 가장 가까운 것). 수집기의 단순 '가장 가까운 예고' 연결을 덮어쓴다."""
    def arts_of(e):
        return set(find_articles(all_text(e))) | set(e.get('articles') or [])
    notices = [e for e in events if e['status'] in ('사전예고', '입법예고') and e.get('date')]
    na = {n['id']: arts_of(n) for n in notices}
    for e in events:
        if e['status'] not in ('공포', '시행') or not e.get('date'):
            continue
        ea = arts_of(e)
        best = None
        for n in notices:
            if n['reg_name'].split(' ·')[0] != e['reg_name'].split(' ·')[0] or n['date'] > e['date']:
                continue
            gap = int(e['date'].replace('-', '')) - int(n['date'].replace('-', ''))
            if gap > 240:
                continue
            # 의견제출 시한 전에 확정 게시되는 경우도 실제로 있어(’26.4 K-ICS 건) 시한으로는 거르지 않는다
            overlap = len(ea & na[n['id']])
            key = (overlap, -gap)
            if best is None or key > best[0]:
                best = (key, n['id'], n)
        if best and (best[0][0] > 0 or not ea):
            n = best[2]
            e['related_notice_id'] = best[1]
            # 강한 연결: 조문 겹침 2개 이상이거나, 예고 의견제출 시한이 지난 뒤의 확정 게시
            e['_link_strong'] = best[0][0] >= 2 or bool(n.get('date_comment_due') and n['date_comment_due'] <= e['date'])
        else:
            e['related_notice_id'] = None
            e['_link_strong'] = False


def build(ev, css, related, rules=None):
    status = ev['status']
    text = all_text(ev)
    arts = find_articles(text)
    eff = find_effective(ev, text)
    if eff and not ev.get('date_effective'):
        ev = {**ev, 'date_effective': eff}
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
    title_core = short_purpose(ev)
    if (not ev.get('purpose')) and related and related.get('purpose') and ev.get('_link_strong'):
        title_core = short_purpose(related)
    elif not ev.get('purpose') and not ev.get('body') and (arts or rows):
        title_core = f"{' · '.join(arts[:3]) + ' 등 ' if arts else ''}{len(rows)}개 항목 개정" if rows else f"{' · '.join(arts[:3])} 개정"
    # 공고문 취지가 없는 확정 건은 담당자 판정 사유(config overrides) 가 가장 좋은 한 줄 요약이다
    ov = ((rules or {}).get('overrides') or {}).get(ev['id'], {})
    if (not title_core or title_core == f"{ev['reg_name']} 개정" or re.fullmatch(r'\d+개 항목 개정', title_core)) and ov.get('reason'):
        title_core = re.sub(r'\(확정\)$', '', ov['reason']).strip()
    if not title_core:
        title_core = f"{ev['reg_name']} 개정"
    h1 = f"{ev['reg_name']} 개정 — {title_core}" if not title_core.startswith(ev['reg_name']) else title_core
    if status == '보도자료':
        # 보도자료는 헤드라인이 가장 좋은 제목이다. '[보도자료]'·'[보도참고]' 머리말은 뗀다
        headline = re.sub(r'^\s*[\[(【]\s*보도\s*(?:자료|참고)\s*[\])】]\s*', '', ev.get('list_title') or '').strip() or title_core
        title_core, h1 = headline, f"{ev['reg_name']} 보도자료 — {headline}"
        if re.match(r'^\s*※', ev.get('purpose') or ''):            # 본문이 '※ 자세한 내용은 첨부파일 참고' 뿐인 금감원 보도자료
            ev = {**ev, 'purpose': ''}
    subt_bits = [ev['reg_name']] + ([' · '.join(arts[:4])] if arts else []) + [f"{fmt_date(ev.get('date'))} {STATUS_LABEL.get(status, status)}"]
    if ev.get('date_comment_due'):
        subt_bits.append(f"의견제출 {fmt_date(ev['date_comment_due'])}까지")
    if ev.get('date_effective'):
        subt_bits.append(f"시행 {fmt_date(ev['date_effective'])}")
    lead = ev.get('purpose') or (ev.get('body') or '')[:160] or ev.get('list_title', '')
    lead = re.sub(r'^[□◦○ㅇ\s]+', '', lead)

    # 결론 요약표
    sumrows = [('규정', f"{ev['reg_name']}" + (f" · {' · '.join(arts[:6])}" if arts else '')),
               ('단계', STATUS_LABEL.get(status, status) + (f" ({ev.get('notice_kind')})" if ev.get('notice_kind') else '')),
               ('일자', ('예고 ' if is_notice else ('고시 ' if status == '공포' else ('배포 ' if status == '보도자료' else '게시 '))) + fmt_date(ev.get('date')))]
    if ev.get('date_comment_due'):
        sumrows.append(('의견제출 시한', fmt_date(ev['date_comment_due'])))
    if ev.get('date_effective'):
        sumrows.append(('시행일', fmt_date(ev['date_effective'])))
    if rows:
        sumrows.append(('변경 규모', f"조문 {len(rows)}개 — {counts_text(counts)}" + (f" · 변경 없음 {len(unchanged)}" if unchanged else '')
                        + f" / 줄 단위 {counts_text(line_counts)} (첨부 대비표 기준)"))
    sumrows.append(('계리결산팀 관련성', f"{relevance} — {rel_reason}"))
    if areas:
        sumrows.append(('영향 영역', ' · '.join(areas)))
    sumrows.append(('소관', ev.get('authority') or '—'))
    if related:
        sumrows.append(('선행 예고' if ev.get('_link_strong') else '선행 예고 (추정)', f"{fmt_date(related.get('date'))} {related['reg_name']} {STATUS_LABEL.get(related['status'], related['status'])}" + ('' if ev.get('_link_strong') else ' — 조문 겹침으로 추정한 연결이라 확인 필요')))

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
    nav += ['<a href="#4">조치 사항</a>', '<a href="#a">부록</a>']
    H.append(f'<div class="nav"><div class="in">{"".join(nav)}</div></div><div class="sec">')

    # 결론
    H.append('<h2 id="c">결론</h2>')
    H.append(f'<p class="lead">{esc(lead)}</p>')
    H.append('<div class="tw"><table class="wrap-ok2"><thead><tr><th>구분</th><th>내용</th></tr></thead><tbody>')
    for i, (k, v) in enumerate(sumrows):
        H.append(f'<tr{" class=hl" if i == 0 else ""}><td class="l"><b>{esc(k)}</b></td><td class="l">{esc(v)}</td></tr>')
    H.append('</tbody></table></div>')
    if relevance == '무관':
        H.append('<div class="callout neutral"><b>계리결산팀 업무와 직접 관련이 없는 개정이다.</b><p>IFRS17 부채결산·계리적 가정·경제적 가정·계리모델 현금흐름에 영향을 주지 않는다 (' + esc(rel_reason) + '). 참고용으로만 보관한다.</p></div>')
    elif relevance == '참고':
        H.append('<div class="callout neutral"><b>계리결산팀 참고 사항이다.</b><p>' + esc(rel_reason) + '. 결산 산출물·지급여력 등 인접 영역이라 내용은 확인하되 모델 변경 대상은 아니다.</p></div>')
    if is_notice:
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
    if ev.get('date_effective'):
        H.append(f'<tr class="hl"><td class="l">시행</td><td>{fmt_date(ev["date_effective"])}</td><td class="l">부칙 기준</td></tr>')
    elif not is_notice and status != '보도자료':
        H.append('<tr><td class="l">시행</td><td>—</td><td class="l">부칙에서 확인 필요 (자동 추출 안 됨)</td></tr>')
    H.append('</tbody></table></div>')
    if ev.get('contact'):
        H.append(f'<p class="note">담당 · {esc(ev["contact"])}</p>')

    # 2. 주요 내용
    H.append('<h2 id="2">2. 주요 내용</h2>')
    if main_items:
        H.append('<div class="tw"><table class="wrap-ok2"><thead><tr><th>#</th><th>내용</th></tr></thead><tbody>')
        for i, p in enumerate(main_items[:20], 1):
            H.append(f'<tr><td>{i}</td><td class="l">{esc(p)}</td></tr>')
        H.append('</tbody></table></div>')
    else:
        H.append('<p>공고문에 요약된 주요 내용이 없다. 부록의 원문 추출 전문과 첨부 파일을 본다.</p>')
    if areas:
        H.append(f'<p>계리결산 관점의 영향 영역은 <strong>{esc(" · ".join(areas))}</strong> 이고, 손볼 시스템은 {esc(" · ".join(systems) or "—")} 이다. 영향 영역은 본문 키워드로 자동 분류한 것이라 담당자가 확인한다.</p>')

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

    # 4. 조치 사항
    H.append('<h2 id="4">4. 조치 사항</h2><div class="tw"><table class="act wrap-ok"><thead><tr><th>순위</th><th>과제</th><th>영향</th></tr></thead><tbody>')
    for i, (t, d, lv) in enumerate(acts, 1):
        H.append(f'<tr{" class=hl" if i == 1 else ""}><td>{i}</td><td class="l"><b>{esc(t)}</b><span class="sub2">{esc(d)}</span></td><td>{lv}</td></tr>')
    H.append('</tbody></table></div><p class="note">조치 항목은 개정 내용 키워드로 자동 생성한 초안이다. 규정 개정이력 화면에서 담당·기한·상태를 관리한다.</p>')

    # 부록
    H.append('<h2 id="a">부록</h2>')
    H.append('<details><summary>A. 출처 · 첨부 파일</summary><div class="body">')
    H.append(f'<p><a href="{esc(ev["url"])}" target="_blank" rel="noopener">{esc(ev["source_label"])} 원문 게시물 ↗</a></p>')
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
        'date_effective': ev.get('date_effective', ''),
        'relevance': relevance, 'relevance_reason': rel_reason,
        'related_notice_id': ev.get('related_notice_id'), 'unchanged': len(unchanged),
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
    os.makedirs(a.out_dir, exist_ok=True)
    index = {}
    # 예고 → 확정 순으로 돌려야 확정 건이 선행 예고의 관련성 판정을 준용할 수 있다
    order = sorted(events, key=lambda e: (0 if e['status'] in ('사전예고', '입법예고') else 1, e.get('date', '')))
    for ev in order:
        if want and ev['id'] not in want:
            continue
        related = by_id.get(ev.get('related_notice_id'))
        htmlstr, meta = build(ev, css, related, rules)
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
