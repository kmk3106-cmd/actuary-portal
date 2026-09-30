"""
주간업무 월결산 리포트 생성기.

해당 월의 주간업무를 모아 **완료 / 미진 / 진행중 / 착수예정** 4분류로 정리한 xlsx 를 만든다.
- 같은 업무가 여러 주차에 '연장'으로 반복 등장하므로 (담당자, 업무내용) 기준으로 **가장 최근 주차 1건만** 집계.
- 표준분류(reports/category_rules.json) 로 그룹핑·정렬 (make_weekly_report 와 동일 SSOT).

분류 기준 (기준일 = --asof, 기본값은 해당 월 말일):
  완료     : 상태 '완료' 또는 진척율 100% 또는 업무구분 '종료'
  미진     : 미완료인데 완료예정일이 기준일 이전(지연) 또는 업무구분 '보류'
  착수예정 : 미완료·미지연이고 상태 '미착수' 또는 진척율 0/미기재
  진행중   : 그 외 (진행 중이며 아직 기한 내)

사용 예)
  python reports/make_monthly_closing.py --ym 202609 --url https://portal.kkuks.com --out reports/output/월결산_202609.xlsx
  python reports/make_monthly_closing.py --ym 202609 --data /tmp/weekly.json --out reports/output/월결산_202609.xlsx
"""
import argparse
import calendar
import json
import os
import re
import sys
import urllib.request
from collections import OrderedDict
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_weekly_report import (  # noqa: E402
    normalize_category, load_category_rules, CANONICAL_ORDER, _sort_members,
    _norm_progress, TITLE_FONT, SUB_FONT, HEAD_FONT, BODY_FONT, BOLD_FONT, CAT_FONT, FOOT_FONT,
    TITLE_FILL, SUB_FILL, HEAD_FILL, CAT_FILL, FOOT_FILL, BORDER_ALL, CENTER, LEFT,
)

# ── 4분류 정의 (표기 순서 · 색) ─────────────────────────────
BUCKETS = ['완료', '미진', '진행중', '착수예정']
BUCKET_FILL = {
    '완료':     ('D1FAE5', '065F46'),   # 녹색
    '미진':     ('FEE2E2', '991B1B'),   # 빨강
    '진행중':   ('DBEAFE', '1E40AF'),   # 파랑
    '착수예정': ('F1F5F9', '475569'),   # 회색
}
TABLE_LIMIT = 3000   # /tables 조회 상한


# ── 유틸 ──────────────────────────────────────────────────
def parse_date(v):
    """'2026-09-30' / '2026-10.02' / '20260928' 등을 date 로. 날짜가 아니면 None."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r'^(\d{4})[.\-/]?(\d{1,2})[.\-/]?(\d{1,2})$', s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def norm_text(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def month_bounds(ym):
    y, m = int(ym[:4]), int(ym[4:6])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


ONGOING_EXTS = ('연장', '상시')   # 이월/상시 = 이미 진행 중인 업무


def classify(t, asof):
    """행 1건을 4분류 중 하나로 (우선순위 순)."""
    status = norm_text(t.get('status'))
    ext = norm_text(t.get('extension_type'))
    prog = _norm_progress(t.get('progress'))
    if status == '완료' or ext == '종료' or (prog is not None and prog >= 1.0):
        return '완료'
    if ext == '보류':
        return '미진'
    ed = parse_date(t.get('end_date'))
    if ed is not None and ed < asof:
        return '미진'
    if status == '진행중':
        return '진행중'
    if status == '미착수':
        return '착수예정'
    if prog is not None and prog > 0:
        return '진행중'
    # 상태·진척율 미기재: 이월(연장/상시)됐거나 2주 이상 등장했으면 사실상 진행 중
    if ext in ONGOING_EXTS or int(t.get('_seen') or 1) >= 2:
        return '진행중'
    return '착수예정'


def load_rows(args):
    if args.data:
        with open(args.data, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, list) else (d.get('rows') or d.get('data') or [])
    url = args.url.rstrip('/') + '/tables/weekly_tasks?limit=%d' % TABLE_LIMIT
    with urllib.request.urlopen(url, timeout=30) as r:
        d = json.loads(r.read().decode('utf-8'))
    return d.get('rows') or d.get('data') or []


def dedupe_latest(rows):
    """(담당자, 업무내용) 별 최근 주차 1건. 주차 번호 → updated_at 순으로 최신 판단."""
    best = OrderedDict()
    seen = {}
    for t in rows:
        key = (norm_text(t.get('member_name')), norm_text(t.get('task_content')).lower())
        if not key[0] or not key[1]:
            continue
        seen[key] = seen.get(key, 0) + 1
        rank = (int(t.get('year') or 0), int(t.get('week_no') or 0), int(t.get('updated_at') or 0))
        if key not in best or rank > best[key][0]:
            best[key] = (rank, t)
    out = []
    for key, (_, t) in best.items():
        t['_seen'] = seen[key]   # 등장 주차 수 (분류 보조 신호)
        out.append(t)
    return out


# ── xlsx ───────────────────────────────────────────────────
def build(rows_by_bucket, ym, asof, weeks, out, cat_rules):
    wb = Workbook()
    ws = wb.active
    ws.title = '월결산_%s' % ym
    widths = {'A': 14, 'B': 18, 'C': 9, 'D': 46, 'E': 9, 'F': 9, 'G': 12, 'H': 12, 'I': 14, 'J': 30}
    for c, w in widths.items():
        ws.column_dimensions[c].width = w

    ws.merge_cells('A1:J1')
    ws['A1'] = '계리결산팀 주간업무 월결산 (%s년 %s월)' % (ym[:4], int(ym[4:6]))
    ws['A1'].font = TITLE_FONT; ws['A1'].fill = TITLE_FILL; ws['A1'].alignment = CENTER
    ws.row_dimensions[1].height = 28
    ws.merge_cells('A2:J2')
    ws['A2'] = '기준일 %s   |   집계 주차: %s   |   동일 업무는 최근 주차 상태로 1건 집계' % (
        asof.strftime('%Y.%m.%d'), ', '.join(weeks))
    ws['A2'].font = SUB_FONT; ws['A2'].fill = SUB_FILL; ws['A2'].alignment = CENTER
    ws.row_dimensions[2].height = 22

    # 요약 표
    row = 4
    ws.cell(row=row, column=1, value='구분').font = HEAD_FONT
    ws.cell(row=row, column=2, value='건수').font = HEAD_FONT
    ws.cell(row=row, column=3, value='비중').font = HEAD_FONT
    for c in (1, 2, 3):
        ws.cell(row=row, column=c).fill = HEAD_FILL; ws.cell(row=row, column=c).alignment = CENTER
        ws.cell(row=row, column=c).border = BORDER_ALL
    total = sum(len(v) for v in rows_by_bucket.values())
    row += 1
    for b in BUCKETS:
        n = len(rows_by_bucket[b])
        bg, fg = BUCKET_FILL[b]
        ws.cell(row=row, column=1, value=b).font = Font(name='맑은 고딕', size=10, bold=True, color=fg)
        ws.cell(row=row, column=1).fill = PatternFill('solid', fgColor=bg)
        ws.cell(row=row, column=2, value=n)
        ws.cell(row=row, column=3, value=(n / total) if total else 0).number_format = '0%'
        for c in (1, 2, 3):
            ws.cell(row=row, column=c).border = BORDER_ALL; ws.cell(row=row, column=c).alignment = CENTER
        row += 1
    ws.cell(row=row, column=1, value='합계').font = BOLD_FONT
    ws.cell(row=row, column=2, value=total).font = BOLD_FONT
    ws.cell(row=row, column=3, value=1 if total else 0).number_format = '0%'
    for c in (1, 2, 3):
        ws.cell(row=row, column=c).border = BORDER_ALL; ws.cell(row=row, column=c).alignment = CENTER
    row += 2

    headers = ['표준분류', '담당', '업무구분', '업무내용', '진척율', '상태', '시작일', '완료(예정)', '최근주차', '이슈 · 비고']
    sort_order = (cat_rules or {}).get('sort_order') or CANONICAL_ORDER

    for b in BUCKETS:
        items = rows_by_bucket[b]
        bg, fg = BUCKET_FILL[b]
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
        ws.cell(row=row, column=1, value='■ %s  (%d건)' % (b, len(items))).font = Font(
            name='맑은 고딕', size=12, bold=True, color=fg)
        ws.cell(row=row, column=1).fill = PatternFill('solid', fgColor=bg)
        ws.cell(row=row, column=1).alignment = LEFT
        ws.row_dimensions[row].height = 24
        row += 1
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=row, column=i, value=h)
            c.font = HEAD_FONT; c.fill = HEAD_FILL; c.alignment = CENTER; c.border = BORDER_ALL
        row += 1
        if not items:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
            ws.cell(row=row, column=1, value='(해당 없음)').font = FOOT_FONT
            row += 2
            continue
        # 정렬: 표준분류 순 → 담당 순
        def _k(t):
            std = t['_std']
            o = sort_order.index(std) if std in sort_order else 999
            return (o, _sort_members([t.get('member_name') or ''])[0])
        for t in sorted(items, key=_k):
            prog = _norm_progress(t.get('progress'))
            vals = [
                t['_std'], t.get('member_name') or '', norm_text(t.get('extension_type')) or None,
                norm_text(t.get('task_content')), prog, norm_text(t.get('status')) or None,
                norm_text(t.get('start_date')) or None, norm_text(t.get('end_date')) or None,
                t.get('week_label') or '', norm_text(t.get('issue_note')) or None,
            ]
            for i, v in enumerate(vals, 1):
                c = ws.cell(row=row, column=i, value=v)
                c.font = BODY_FONT; c.border = BORDER_ALL
                c.alignment = CENTER if i in (2, 3, 5, 6, 7, 8, 9) else LEFT
            if prog is not None:
                ws.cell(row=row, column=5).number_format = '0%'
            ws.cell(row=row, column=1).font = CAT_FONT
            ws.row_dimensions[row].height = 24
            row += 1
        row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
    ws.cell(row=row, column=1, value=(
        '※ 완료: 상태 완료·진척100%·종료  |  미진: 완료예정일 경과 미완료·보류  |  '
        '착수예정: 미착수·진척 0%  |  진행중: 그 외')).font = FOOT_FONT
    ws.cell(row=row, column=1).fill = FOOT_FILL
    ws.freeze_panes = 'A4'

    # 인별 요약 시트
    ws2 = wb.create_sheet('인별요약')
    members = _sort_members(sorted({t.get('member_name') for b in BUCKETS for t in rows_by_bucket[b] if t.get('member_name')}))
    hdr = ['팀원'] + BUCKETS + ['합계']
    for i, h in enumerate(hdr, 1):
        c = ws2.cell(row=1, column=i, value=h)
        c.font = HEAD_FONT; c.fill = HEAD_FILL; c.alignment = CENTER; c.border = BORDER_ALL
    ws2.column_dimensions['A'].width = 12
    for m_i, m in enumerate(members, 2):
        ws2.cell(row=m_i, column=1, value=m).font = BOLD_FONT
        tot = 0
        for b_i, b in enumerate(BUCKETS, 2):
            n = sum(1 for t in rows_by_bucket[b] if t.get('member_name') == m)
            tot += n
            ws2.cell(row=m_i, column=b_i, value=n)
        ws2.cell(row=m_i, column=len(hdr), value=tot).font = BOLD_FONT
        for c in range(1, len(hdr) + 1):
            ws2.cell(row=m_i, column=c).border = BORDER_ALL; ws2.cell(row=m_i, column=c).alignment = CENTER
    ws2.freeze_panes = 'B2'

    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    wb.save(out)


def main():
    ap = argparse.ArgumentParser(description='주간업무 월결산 (완료/미진/진행중/착수예정) xlsx 생성')
    ap.add_argument('--ym', required=True, help='기준 연월 YYYYMM (예: 202609)')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--data', help='weekly_tasks JSON 파일 경로')
    src.add_argument('--url', help='포탈 URL (예: https://portal.kkuks.com) — /tables/weekly_tasks 조회')
    ap.add_argument('--out', required=True, help='출력 xlsx 경로')
    ap.add_argument('--asof', default=None, help='기준일 YYYY-MM-DD (기본: 해당 월 말일)')
    ap.add_argument('--category-rules', default=None, help='표준분류 규칙 JSON (기본: reports/category_rules.json)')
    ap.add_argument('--print', action='store_true', help='결과 요약을 콘솔에도 출력')
    args = ap.parse_args()

    if not re.match(r'^\d{6}$', args.ym):
        print('ERROR: --ym 은 YYYYMM 형식', file=sys.stderr); sys.exit(2)
    m_start, m_end = month_bounds(args.ym)
    asof = date.fromisoformat(args.asof) if args.asof else m_end
    cat_rules = load_category_rules(args.category_rules)

    rows = load_rows(args)
    # 해당 월 주차만 (기준일 base_date 의 월) · 정크 제외
    month_rows = [t for t in rows
                  if str(t.get('base_date') or '')[:7] == m_start.strftime('%Y-%m')
                  and not str(t.get('member_name') or '').startswith('bench')]
    weeks = sorted({t.get('week_label') for t in month_rows if t.get('week_label')},
                   key=lambda s: int(re.search(r'(\d+)주차', s).group(1)) if re.search(r'(\d+)주차', s) else 0)
    latest = dedupe_latest(month_rows)

    rows_by_bucket = OrderedDict((b, []) for b in BUCKETS)
    for t in latest:
        t['_std'] = normalize_category(t.get('category'), t.get('task_content'), t.get('work_type_detail'), cat_rules)
        rows_by_bucket[classify(t, asof)].append(t)

    build(rows_by_bucket, args.ym, asof, weeks, args.out, cat_rules)
    print('OK: %s | 원행 %d → 중복제거 %d | %s' % (
        args.out, len(month_rows), len(latest),
        ' · '.join('%s %d' % (b, len(rows_by_bucket[b])) for b in BUCKETS)))

    if args.print:
        for b in BUCKETS:
            print('\n■ %s (%d건)' % (b, len(rows_by_bucket[b])))
            for t in rows_by_bucket[b]:
                p = _norm_progress(t.get('progress'))
                print('  [%s] %s | %s | %s | 예정 %s' % (
                    t['_std'], t.get('member_name'), norm_text(t.get('task_content'))[:44],
                    ('%d%%' % round(p * 100)) if p is not None else '-', t.get('end_date') or '-'))


if __name__ == '__main__':
    main()
