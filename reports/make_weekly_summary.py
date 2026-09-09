"""
계리결산팀 주간업무 기간 집계 xlsx 생성기.

- 입력 : --data JSON (weekly_tasks 배열)
- 기간 : --period month|quarter|year --value (해당 기간 값)
- 그룹 : --groupby member|worktype|all
- 출력 : --out xlsx

시트 구성 (groupby=all):
  1) 인별 집계    — 팀원 × { 총·완료·진행중·미착수·평균진척 · 유형별건수 · 업무구분별건수 }
  2) 업무유형별   — 유형(Ⅰ~Ⅵ) × { 총·완료·진행중·미착수·평균진척 · 팀원별건수 }
  3) 원 데이터    — 기간에 속한 모든 task rows (참고용)
"""
import argparse
import json
import os
import sys
from collections import OrderedDict
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import CellIsRule


MEMBER_ORDER = [
    '한인석', '고인수', '마혜원', '이상현', '이동민', '예대호',
    '김예은', '강세진', '오정택', '이용우', '김채린', '이성원',
]

WORK_TYPES = [
    ('Ⅰ', 'IFRS17 결산'),
    ('Ⅱ', '결산 실무'),
    ('Ⅲ', '차세대'),
    ('Ⅳ', '모델·시스템'),
    ('Ⅴ', '대내외 대응'),
    ('Ⅵ', '관리회계·기타'),
]
EXTS = ['신규', '연장', '종료', '상시', '보류']

TITLE_FONT = Font(name='맑은 고딕', size=15, bold=True, color='FFFFFF')
SUB_FONT   = Font(name='맑은 고딕', size=11, bold=True, color='FFFFFF')
HEAD_FONT  = Font(name='맑은 고딕', size=10, bold=True, color='FFFFFF')
BODY_FONT  = Font(name='맑은 고딕', size=10)
BOLD_FONT  = Font(name='맑은 고딕', size=11, bold=True, color='0F172A')
NUM_FONT   = Font(name='맑은 고딕', size=10, color='334155')

TITLE_FILL = PatternFill('solid', fgColor='1E3A5F')
SUB_FILL   = PatternFill('solid', fgColor='334155')
HEAD_FILL  = PatternFill('solid', fgColor='475569')
NAME_FILL  = PatternFill('solid', fgColor='EFF6FF')
TOTAL_FILL = PatternFill('solid', fgColor='F1F5F9')

THIN = Side(border_style='thin', color='CBD5E1')
BORDER_ALL = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
LEFT   = Alignment(horizontal='left',   vertical='center', wrap_text=True)


def _norm_progress(v):
    if v is None or v == '':
        return None
    try:
        f = float(v)
        return max(0.0, min(1.0, f))
    except Exception:
        return None


def _period_label(year, period, value):
    if period == 'year':
        return f"{year}년 전체"
    if period == 'month':
        return f"{year}년 {value}월"
    return f"{year}년 {value}분기"


def _sort_members(names):
    ordered = [n for n in MEMBER_ORDER if n in names]
    extras = sorted([n for n in names if n not in ordered], key=lambda x: (x or ''))
    return ordered + extras


def _bucket_of(t):
    """(status_class, is_progress_valid, progress_value)"""
    status = (t.get('status') or '').strip()
    pg = _norm_progress(t.get('progress'))
    done = (status == '완료') or (pg is not None and pg >= 1)
    doing = not done and ((pg is not None and pg > 0) or status == '진행중')
    none = not done and not doing
    return done, doing, none, pg


def aggregate(tasks):
    valid = [t for t in tasks if (t.get('task_content') or '').strip()]
    # 인별
    by_member = OrderedDict()
    # 업무유형별
    by_wt = OrderedDict((k, {'label': label, 'total': 0, 'done': 0, 'doing': 0, 'none': 0,
                             'pg_sum': 0.0, 'pg_cnt': 0, 'by_member': {}})
                        for k, label in WORK_TYPES)
    by_wt['(미지정)'] = {'label': '(미지정)', 'total': 0, 'done': 0, 'doing': 0, 'none': 0,
                         'pg_sum': 0.0, 'pg_cnt': 0, 'by_member': {}}

    members_seen = set()
    for t in valid:
        m = (t.get('member_name') or '(미지정)').strip()
        wt = (t.get('work_type') or '(미지정)').strip()
        if wt not in by_wt:
            wt = '(미지정)'
        ext = (t.get('extension_type') or '(미지정)').strip()
        members_seen.add(m)

        if m not in by_member:
            by_member[m] = {
                'total': 0, 'done': 0, 'doing': 0, 'none': 0,
                'pg_sum': 0.0, 'pg_cnt': 0,
                'by_worktype': {k: 0 for k, _ in WORK_TYPES}, 'by_worktype_etc': 0,
                'by_ext': {e: 0 for e in EXTS}, 'by_ext_etc': 0,
            }
        done, doing, none, pg = _bucket_of(t)
        b = by_member[m]
        b['total'] += 1
        b['done']  += 1 if done else 0
        b['doing'] += 1 if doing else 0
        b['none']  += 1 if none else 0
        if pg is not None:
            b['pg_sum'] += pg; b['pg_cnt'] += 1
        if wt in b['by_worktype']:
            b['by_worktype'][wt] += 1
        else:
            b['by_worktype_etc'] += 1
        if ext in b['by_ext']:
            b['by_ext'][ext] += 1
        else:
            b['by_ext_etc'] += 1

        w = by_wt[wt]
        w['total'] += 1
        w['done']  += 1 if done else 0
        w['doing'] += 1 if doing else 0
        w['none']  += 1 if none else 0
        if pg is not None:
            w['pg_sum'] += pg; w['pg_cnt'] += 1
        w['by_member'][m] = w['by_member'].get(m, 0) + 1

    ordered_members = _sort_members(list(members_seen))
    # OrderedDict 재구성 (정렬)
    by_member = OrderedDict((n, by_member[n]) for n in ordered_members if n in by_member)
    return by_member, by_wt, ordered_members


def _header_block(ws, title, subtitle, last_col_letter):
    ws.merge_cells(f'A1:{last_col_letter}1')
    ws['A1'] = title
    ws['A1'].font = TITLE_FONT; ws['A1'].fill = TITLE_FILL; ws['A1'].alignment = CENTER
    ws.row_dimensions[1].height = 28
    ws.merge_cells(f'A2:{last_col_letter}2')
    ws['A2'] = subtitle
    ws['A2'].font = SUB_FONT; ws['A2'].fill = SUB_FILL; ws['A2'].alignment = CENTER
    ws.row_dimensions[2].height = 22


def _write_headers(ws, row, headers):
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = HEAD_FONT; c.fill = HEAD_FILL; c.alignment = CENTER; c.border = BORDER_ALL
    ws.row_dimensions[row].height = 24


def build_member_sheet(wb, period_label, by_member, ordered_members):
    ws = wb.create_sheet('인별 집계')
    # 컬럼 : 팀원 · 총 · 완료 · 진행중 · 미착수 · 평균진척 · Ⅰ~Ⅵ · 신규 · 연장 · 종료 · 상시 · 보류
    headers = ['팀원', '총', '완료', '진행중', '미착수', '평균 진척율'] + \
              [f'{k} ({label})' for k, label in WORK_TYPES] + EXTS
    widths = [10, 6, 6, 6, 6, 10] + [10] * 6 + [7] * 5
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    last_col = get_column_letter(len(headers))
    _header_block(ws, '인별 실적 집계', period_label, last_col)
    _write_headers(ws, 3, headers)

    row = 4
    for name in ordered_members:
        b = by_member[name]
        a = ws.cell(row=row, column=1, value=name)
        a.font = BOLD_FONT; a.fill = NAME_FILL; a.alignment = CENTER; a.border = BORDER_ALL
        ws.cell(row=row, column=2, value=b['total'])
        ws.cell(row=row, column=3, value=b['done'])
        ws.cell(row=row, column=4, value=b['doing'])
        ws.cell(row=row, column=5, value=b['none'])
        avg = (b['pg_sum'] / b['pg_cnt']) if b['pg_cnt'] > 0 else None
        avg_cell = ws.cell(row=row, column=6, value=(avg if avg is not None else '-'))
        if avg is not None:
            avg_cell.number_format = '0.0%'
        col = 7
        for k, _ in WORK_TYPES:
            ws.cell(row=row, column=col, value=b['by_worktype'].get(k, 0)); col += 1
        for ext in EXTS:
            ws.cell(row=row, column=col, value=b['by_ext'].get(ext, 0)); col += 1
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=row, column=c)
            cell.border = BORDER_ALL
            if c > 1: cell.alignment = CENTER; cell.font = NUM_FONT
        ws.row_dimensions[row].height = 22
        row += 1

    # 합계
    total_r = row
    ws.cell(row=total_r, column=1, value='합계').font = BOLD_FONT
    ws.cell(row=total_r, column=1).alignment = CENTER
    ws.cell(row=total_r, column=1).fill = TOTAL_FILL
    for col in range(2, len(headers) + 1):
        letter = get_column_letter(col)
        if col == 6:
            ws.cell(row=total_r, column=col,
                    value=f'=IFERROR(SUMPRODUCT(F4:F{row - 1},B4:B{row - 1})/SUM(B4:B{row - 1}),"-")')
            ws.cell(row=total_r, column=col).number_format = '0.0%'
        else:
            ws.cell(row=total_r, column=col, value=f'=SUM({letter}4:{letter}{row - 1})')
        ws.cell(row=total_r, column=col).font = BOLD_FONT
        ws.cell(row=total_r, column=col).alignment = CENTER
        ws.cell(row=total_r, column=col).fill = TOTAL_FILL
    for c in range(1, len(headers) + 1):
        ws.cell(row=total_r, column=c).border = BORDER_ALL

    ws.freeze_panes = 'B4'


def build_worktype_sheet(wb, period_label, by_wt, ordered_members):
    ws = wb.create_sheet('업무유형별 집계')
    # 컬럼 : 업무유형 · 설명 · 총 · 완료 · 진행중 · 미착수 · 평균진척 · 팀원1..N
    headers = ['업무유형', '설명', '총', '완료', '진행중', '미착수', '평균 진척율'] + ordered_members
    widths = [10, 20, 6, 6, 6, 6, 10] + [10] * len(ordered_members)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    last_col = get_column_letter(len(headers))
    _header_block(ws, '업무유형별 실적 집계', period_label, last_col)
    _write_headers(ws, 3, headers)

    row = 4
    for k, label in WORK_TYPES:
        w = by_wt[k]
        ws.cell(row=row, column=1, value=k).font = BOLD_FONT
        ws.cell(row=row, column=1).alignment = CENTER; ws.cell(row=row, column=1).fill = NAME_FILL
        ws.cell(row=row, column=2, value=label).alignment = LEFT
        ws.cell(row=row, column=3, value=w['total'])
        ws.cell(row=row, column=4, value=w['done'])
        ws.cell(row=row, column=5, value=w['doing'])
        ws.cell(row=row, column=6, value=w['none'])
        avg = (w['pg_sum'] / w['pg_cnt']) if w['pg_cnt'] > 0 else None
        c7 = ws.cell(row=row, column=7, value=(avg if avg is not None else '-'))
        if avg is not None: c7.number_format = '0.0%'
        col = 8
        for m in ordered_members:
            ws.cell(row=row, column=col, value=w['by_member'].get(m, 0)); col += 1
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=row, column=c)
            cell.border = BORDER_ALL
            if c > 2:
                cell.font = NUM_FONT
                cell.alignment = CENTER
        ws.row_dimensions[row].height = 22
        row += 1

    # 미지정
    if by_wt.get('(미지정)', {}).get('total', 0) > 0:
        w = by_wt['(미지정)']
        ws.cell(row=row, column=1, value='(미지정)').font = BOLD_FONT
        ws.cell(row=row, column=1).alignment = CENTER
        ws.cell(row=row, column=1).fill = PatternFill('solid', fgColor='FEF3C7')
        ws.cell(row=row, column=2, value='업무유형 미지정 - 팀장이 재분류 필요')
        ws.cell(row=row, column=3, value=w['total'])
        ws.cell(row=row, column=4, value=w['done'])
        ws.cell(row=row, column=5, value=w['doing'])
        ws.cell(row=row, column=6, value=w['none'])
        avg = (w['pg_sum'] / w['pg_cnt']) if w['pg_cnt'] > 0 else None
        c7 = ws.cell(row=row, column=7, value=(avg if avg is not None else '-'))
        if avg is not None: c7.number_format = '0.0%'
        col = 8
        for m in ordered_members:
            ws.cell(row=row, column=col, value=w['by_member'].get(m, 0)); col += 1
        for c in range(1, len(headers) + 1):
            ws.cell(row=row, column=c).border = BORDER_ALL
            if c > 2:
                ws.cell(row=row, column=c).alignment = CENTER
                ws.cell(row=row, column=c).font = NUM_FONT
        row += 1

    # 합계
    total_r = row
    ws.cell(row=total_r, column=1, value='합계').font = BOLD_FONT
    ws.cell(row=total_r, column=1).alignment = CENTER; ws.cell(row=total_r, column=1).fill = TOTAL_FILL
    ws.cell(row=total_r, column=2, value='').fill = TOTAL_FILL
    for col in range(3, len(headers) + 1):
        letter = get_column_letter(col)
        if col == 7:
            ws.cell(row=total_r, column=col,
                    value=f'=IFERROR(SUMPRODUCT(G4:G{row - 1},C4:C{row - 1})/SUM(C4:C{row - 1}),"-")')
            ws.cell(row=total_r, column=col).number_format = '0.0%'
        else:
            ws.cell(row=total_r, column=col, value=f'=SUM({letter}4:{letter}{row - 1})')
        ws.cell(row=total_r, column=col).font = BOLD_FONT
        ws.cell(row=total_r, column=col).alignment = CENTER
        ws.cell(row=total_r, column=col).fill = TOTAL_FILL
    for c in range(1, len(headers) + 1):
        ws.cell(row=total_r, column=c).border = BORDER_ALL

    ws.freeze_panes = 'C4'


def build_raw_sheet(wb, period_label, tasks):
    ws = wb.create_sheet('원 데이터')
    headers = ['주차', '팀원', '구분', '업무구분', '업무유형', '업무내용',
               '이번주 한일', '다음주 할일', '이슈', '시작', '완료', '진척', '상태']
    widths = [12, 10, 15, 10, 8, 40, 26, 26, 20, 12, 12, 8, 8]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    last_col = get_column_letter(len(headers))
    _header_block(ws, '원 데이터 (기간 내 전체 task rows)', period_label, last_col)
    _write_headers(ws, 3, headers)

    row = 4
    for t in tasks:
        wk = f"{t.get('year')}-W{t.get('week_no')}"
        vals = [
            wk,
            t.get('member_name', ''),
            t.get('category', ''),
            t.get('extension_type', ''),
            t.get('work_type', ''),
            t.get('task_content', ''),
            t.get('this_week_done', ''),
            t.get('next_week_plan', ''),
            t.get('issue_note', ''),
            t.get('start_date', ''),
            t.get('end_date', ''),
            _norm_progress(t.get('progress')),
            t.get('status', ''),
        ]
        for i, v in enumerate(vals, 1):
            cell = ws.cell(row=row, column=i, value=v)
            cell.font = BODY_FONT
            cell.border = BORDER_ALL
            cell.alignment = CENTER if i in (1, 2, 4, 5, 10, 11, 12, 13) else LEFT
        if isinstance(vals[11], float):
            ws.cell(row=row, column=12).number_format = '0.0%'
        ws.row_dimensions[row].height = 20
        row += 1

    ws.freeze_panes = 'A4'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--year', type=int, required=True)
    ap.add_argument('--period', choices=['month', 'quarter', 'year'], required=True)
    ap.add_argument('--value', type=int, default=0)
    ap.add_argument('--out', required=True)
    ap.add_argument('--groupby', choices=['member', 'worktype', 'all'], default='all')
    args = ap.parse_args()

    if not os.path.exists(args.data):
        print(f'ERROR: 데이터 파일 없음: {args.data}', file=sys.stderr); sys.exit(2)
    with open(args.data, encoding='utf-8') as f:
        tasks = json.load(f)
    if not isinstance(tasks, list):
        print('ERROR: JSON 배열 필요', file=sys.stderr); sys.exit(3)

    by_member, by_wt, ordered_members = aggregate(tasks)
    period_label = _period_label(args.year, args.period, args.value)

    wb = Workbook()
    wb.remove(wb.active)

    if args.groupby in ('member', 'all'):
        build_member_sheet(wb, period_label, by_member, ordered_members)
    if args.groupby in ('worktype', 'all'):
        build_worktype_sheet(wb, period_label, by_wt, ordered_members)
    if args.groupby == 'all':
        build_raw_sheet(wb, period_label, tasks)

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    wb.save(args.out)
    print(f'OK: {args.out}  |  tasks={len(tasks)}  |  {period_label}  |  groupby={args.groupby}')


if __name__ == '__main__':
    main()
