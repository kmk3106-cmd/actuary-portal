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
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, '..', 'templates', 'report-template.html')
MAX_ROWS_IN_REPORT = 60          # 대비표 행이 이보다 많으면 나머지는 부록으로
DASH_RE = re.compile(r'[-─—―–‒ー=]{4,}')
STATUS_LABEL = {'사전예고': '사전예고', '입법예고': '규정변경예고', '공포': '확정 고시', '시행': '확정 개정'}
STATUS_TAG = {'사전예고': '사전예고', '입법예고': '규정변경예고', '공포': '고시', '시행': '개정·시행'}
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


ITEM_START_RE = re.compile(r'^\s*(?:제\s?\d+(?:-\d+)?조|\[?별표\s?\d+|\[?별지\s?(?:제\s?)?\d+|[가-힣]\.\s|\d+\.\s|[Ⅰ-Ⅻ]\.|[ⅰ-ⅹ]\)|제\d+장|제\d+절)')
COMPARE_FILE_RE = re.compile(r'대비|신구|신·구|개정안|고시|세칙|규정')


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
                starts = bool(ITEM_START_RE.match(cb) or ITEM_START_RE.match(ca))
                if cur is None or starts:
                    cur = [ca, cb, a['name']]; items.append(cur)
                else:
                    cur[0] = (cur[0] + '\n' + ca).strip('\n'); cur[1] = (cur[1] + '\n' + cb).strip('\n')
    return [tuple(x) for x in items]


def classify(ca, cb):
    a, b = re.sub(r'\s', '', ca), re.sub(r'\s', '', cb)
    if (not a or re.fullmatch(r'[<＜(]?신설[>＞)]?', a)) and b:
        return 'n', '신설'
    if re.search(r'[<＜(]?삭제[>＞)]?', b) and len(b) <= 12:
        return 'm', '삭제'
    if not b and a:
        return 'm', '삭제'
    return 'c', '변경'


def law_html(cell, side):
    out = []
    for line in [x for x in str(cell).split('\n') if x.strip()]:
        s = esc(line.strip())
        s = DASH_RE.sub('<span class="mk">(현행과 같음)</span>', s)
        s = re.sub(r'[<＜]\s*(신\s*설|삭\s*제|생\s*략)\s*[>＞]', lambda m: '<span class="nil">〈' + re.sub(r'\s', '', m.group(1)) + '〉</span>', s)
        s = s.replace('(현행과 같음)', '<span class="mk">(현행과 같음)</span>') if '(현행과 같음)' in line else s
        ind = ' class="ind"' if re.match(r'\s*(?:[①-⑳]|\d+\.|[가-힣]\.|[ⅰ-ⅹ]|[ivx]+\)|[㉮-㉻]|[ⓐ-ⓩ]|-|•|◦|○)', line.strip()) and not re.match(r'제\d', line.strip()) else ''
        out.append(f'<p{ind}>{s}</p>')
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


def build(ev, css, related):
    status = ev['status']
    text = all_text(ev)
    arts = find_articles(text)
    eff = find_effective(ev, text)
    if eff and not ev.get('date_effective'):
        ev = {**ev, 'date_effective': eff}
    areas, systems = impacts(text)
    rows = compare_rows(ev)
    counts = {'n': 0, 'c': 0, 'm': 0}
    for ca, cb, _ in rows:
        counts[classify(ca, cb)[0]] += 1
    paras_src = next((a for a in ev.get('attachments', []) if a.get('extracted') and a['extracted'].get('paras')), None)
    secs = sections_from_paras(paras_src['extracted']['paras']) if paras_src else {}
    is_notice = status in ('사전예고', '입법예고')
    title_core = short_purpose(ev)
    if (not ev.get('purpose')) and related and related.get('purpose'):
        title_core = short_purpose(related)
    elif not ev.get('purpose') and not ev.get('body') and (arts or rows):
        title_core = f"{' · '.join(arts[:3]) + ' 등 ' if arts else ''}{len(rows)}개 항목 개정" if rows else f"{' · '.join(arts[:3])} 개정"
    if not title_core:
        title_core = f"{ev['reg_name']} 개정"
    h1 = f"{ev['reg_name']} 개정 — {title_core}" if not title_core.startswith(ev['reg_name']) else title_core
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
               ('일자', ('예고 ' if is_notice else ('고시 ' if status == '공포' else '게시 ')) + fmt_date(ev.get('date')))]
    if ev.get('date_comment_due'):
        sumrows.append(('의견제출 시한', fmt_date(ev['date_comment_due'])))
    if ev.get('date_effective'):
        sumrows.append(('시행일', fmt_date(ev['date_effective'])))
    if rows:
        sumrows.append(('변경 규모', f"신설 {counts['n']} · 변경 {counts['c']} · 이동·삭제 {counts['m']} (첨부 대비표 기준)"))
    if areas:
        sumrows.append(('영향 영역', ' · '.join(areas)))
    sumrows.append(('소관', ev.get('authority') or '—'))
    if related:
        sumrows.append(('선행 예고', f"{fmt_date(related.get('date'))} {related['reg_name']} 사전예고"))

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
    if is_notice:
        H.append('<div class="callout"><b>사전예고안이다.</b><p>확정 공포 조문과 다를 수 있으므로 적용 전 확정본 대조가 필요하다. 의견제출 시한' + (f' {fmt_date(ev["date_comment_due"])}' if ev.get('date_comment_due') else '') + ' 이후 금감원·금융위 게시판에서 확정 여부를 확인한다.</p></div>')
    elif status == '공포':
        H.append('<div class="callout ok"><b>확정 고시다.</b><p>금융위원회 고시로 확정된 내용이다. 시행일과 경과규정(부칙)을 확인해 적용 시점을 맞춘다.</p></div>')
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
    if ev.get('date_effective'):
        H.append(f'<tr class="hl"><td class="l">시행</td><td>{fmt_date(ev["date_effective"])}</td><td class="l">부칙 기준</td></tr>')
    elif not is_notice:
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
        H.append(f'<p>첨부 대비표에서 추출한 {len(rows)}개 항목이다. 개정안 칸의 <span class="mk">(현행과 같음)</span> 은 원문의 점선(———) 자리로, 현행 문구가 그대로 유지된다는 뜻이다. 신설·삭제 표시는 원문 그대로다.</p>')
        for i, (ca, cb, src) in enumerate(rows[:MAX_ROWS_IN_REPORT], 1):
            cls, lbl = classify(ca, cb)
            head = (cb or ca).strip().split('\n')[0]
            head = re.sub(r'\s+', ' ', head)[:60]
            H.append(f'<h3>3-{i}. <span class="bdg {cls}">{lbl}</span>{esc(head)}</h3>')
            H.append('<div class="cmp"><div class="col col-a"><div class="cmph">현행</div><div class="law">' + law_html(ca, 'a') + '</div></div>'
                     '<div class="col col-b"><div class="cmph">개정안</div><div class="law">' + law_html(cb, 'b') + '</div></div></div>')
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
        for i, (ca, cb, src) in enumerate(rows[MAX_ROWS_IN_REPORT:], MAX_ROWS_IN_REPORT + 1):
            cls, lbl = classify(ca, cb)
            head_c = re.sub(r'\s+', ' ', (cb or ca).strip().split('\n')[0])[:60]
            H.append(f'<h3>3-{i}. <span class="bdg {cls}">{lbl}</span>{esc(head_c)}</h3>')
            H.append('<div class="cmp"><div class="col col-a"><div class="cmph">현행</div><div class="law">' + law_html(ca, 'a') + '</div></div><div class="col col-b"><div class="cmph">개정안</div><div class="law">' + law_html(cb, 'b') + '</div></div></div>')
        H.append('</div></details>')
    H.append('<p class="note">이 리포트는 공개 게시판(금융감독원·금융위원회)의 공고문과 첨부에서 자동 생성했다. 해석·분석이 아닌 원문 정리이며, 확정본은 원문 링크에서 확인한다.</p>')
    H.append('</div></div></body></html>')

    meta = {
        'title': h1, 'articles': arts, 'impact_areas': areas, 'impact_systems': systems,
        'change_new': counts['n'], 'change_mod': counts['c'], 'change_del': counts['m'], 'compare_rows': len(rows),
        'summary': (ev.get('purpose') or lead)[:400], 'actions': [{'no': i + 1, 'task': t, 'owner': '', 'due': '', 'state': '대기'} for i, (t, _, _) in enumerate(acts)],
        'tags': list(dict.fromkeys([ev['reg_name']] + areas[:3] + arts[:3])),
        'date_effective': ev.get('date_effective', ''),
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
    os.makedirs(a.out_dir, exist_ok=True)
    index = {}
    for ev in events:
        if want and ev['id'] not in want:
            continue
        related = by_id.get(ev.get('related_notice_id'))
        htmlstr, meta = build(ev, css, related)
        fn = os.path.join(a.out_dir, ev['id'] + '.html')
        open(fn, 'w', encoding='utf-8').write(htmlstr)
        index[ev['id']] = {'file': fn, **meta}
        print(f"  {ev['id']} {ev.get('date')} {ev['status']} rows={meta['compare_rows']} → {meta['title'][:60]}", file=sys.stderr)
    json.dump(index, open(os.path.join(a.out_dir, '_index.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'완료: {len(index)}건 → {a.out_dir}', file=sys.stderr)


if __name__ == '__main__':
    main()
