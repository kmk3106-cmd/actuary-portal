"""
계리결산팀 주간업무 리포트 생성기 (데이터 주입).

- 입력: --data <JSON 파일 경로> (weekly_tasks 배열)
- 출력: --out <xlsx 경로>
- 뷰:   --view person     ← 주간업무_인별 시트 + 요약 시트
        --view typegroup  ← 통합_업무유형별 시트 (Ⅰ~Ⅵ 카테고리별 그룹핑)
        --view all        ← 3 시트 모두 (기본값)
- 주차: --week "'26년 9월 2주차"  --base-date 2026-09-07

# 데이터 스키마 (JSON)
[
  {
    "user_id": "u_...", "member_name": "한인석",
    "category": "통합계리 모델관리",       ← 인별 시트 '구분' 열
    "task_content": "통합계리모델 배포('26.08)",
    "issue_note": "...",
    "start_date": "2026-09-07" 또는 "계속"/"상시"/"수시" 등,
    "end_date": "2026-09-07" 또는 텍스트,
    "progress": 0.5,                     ← 0~1 또는 null
    "status": "진행중",                    ← 미착수/진행중/완료 또는 '-' 또는 null
    "work_type": "Ⅳ",                    ← 통합 시트용 로마숫자 (Ⅰ~Ⅵ), 팀장이 지정
    "work_type_detail": "통합계리모델 운영·개선"  ← 통합 시트 세부구분
  }, ...
]

# 팀장 예시 사용
python reports/make_weekly_report.py \
  --data /tmp/weekly.json --view all \
  --week "'26년 9월 2주차" --base-date 2026-09-07 \
  --out C:/Users/USER/Downloads/report.xlsx
"""
import argparse
import json
import os
import sys
from collections import OrderedDict
from datetime import date, datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import CellIsRule


# ── 팀원 정렬 순서 (원본 xlsx 순서 유지) ─────────────────────
MEMBER_ORDER = [
    '한인석', '고인수', '마혜원', '이상현', '이동민', '예대호',
    '김예은', '강세진', '오정택', '이용우', '김채린', '이성원',
]

# ── 업무유형 (통합 시트 Ⅰ~Ⅵ) ────────────────────────────────
WORK_TYPES = [
    ('Ⅰ', 'Ⅰ. IFRS17 결산'),
    ('Ⅱ', 'Ⅱ. 결산 실무(준비금·비금·계약)'),
    ('Ⅲ', 'Ⅲ. 차세대 시스템 구축'),
    ('Ⅳ', 'Ⅳ. 모델·시스템 관리'),
    ('Ⅴ', 'Ⅴ. 대내외 대응'),
    ('Ⅵ', 'Ⅵ. 관리회계 및 기타'),
]
WORK_TYPE_KEYS = [k for k, _ in WORK_TYPES]

# ── 업무연장구분 값 (드롭다운) ─────────────────────────────
# 신규: 이번 주 새로 시작 · 연장: 지난 주에서 이월 진행중 · 종료: 이번 주 완료
# 상시: 매주 반복 (상시·수시) · 보류: 대기 상태
EXTENSION_TYPES = ['신규', '연장', '종료', '상시', '보류']
EXT_COLORS = {
    '신규': ('E0F2FE', '0369A1'),   # 하늘색
    '연장': ('FEF3C7', '92400E'),   # 노랑
    '종료': ('D1FAE5', '065F46'),   # 녹색
    '상시': ('F1F5F9', '475569'),   # 회색
    '보류': ('FEE2E2', '991B1B'),   # 빨강
}

# ── 스타일 상수 ────────────────────────────────────────────
TITLE_FONT = Font(name='맑은 고딕', size=15, bold=True, color='FFFFFF')
SUB_FONT   = Font(name='맑은 고딕', size=11, bold=True, color='FFFFFF')
HEAD_FONT  = Font(name='맑은 고딕', size=10, bold=True, color='FFFFFF')
BODY_FONT  = Font(name='맑은 고딕', size=10)
BOLD_FONT  = Font(name='맑은 고딕', size=11, bold=True, color='0F172A')
CAT_FONT   = Font(name='맑은 고딕', size=11, bold=True, color='1E40AF')
SUMFONT    = Font(name='맑은 고딕', size=10, italic=True, color='6B7280')
FOOT_FONT  = Font(name='맑은 고딕', size=9, italic=True, color='6B7280')

TITLE_FILL = PatternFill('solid', fgColor='1E3A5F')
SUB_FILL   = PatternFill('solid', fgColor='334155')
HEAD_FILL  = PatternFill('solid', fgColor='475569')
NAME_FILL  = PatternFill('solid', fgColor='EFF6FF')
CAT_FILL   = PatternFill('solid', fgColor='DBEAFE')
FOOT_FILL  = PatternFill('solid', fgColor='F9FAFB')

THIN = Side(border_style='thin', color='CBD5E1')
BORDER_ALL = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
LEFT   = Alignment(horizontal='left',   vertical='center', wrap_text=True)


def _norm_date(v):
    """DB 값(YYYY-MM-DD 또는 문자열)을 xlsx 저장 형태로."""
    if v is None or v == '':
        return None
    s = str(v).strip()
    # ISO 형태면 date 로 변환, 아니면 문자열 유지 (계속/상시/수시)
    try:
        return datetime.fromisoformat(s[:10]).date()
    except Exception:
        return s


def _norm_progress(v):
    if v is None or v == '':
        return None
    try:
        f = float(v)
        return max(0.0, min(1.0, f))
    except Exception:
        return None


def _prefix_task(text):
    t = (text or '').strip()
    if not t:
        return ''
    return t if t.startswith('▶') else '▶ ' + t


def _sort_members(names):
    ordered = [n for n in MEMBER_ORDER if n in names]
    extras = sorted([n for n in names if n not in ordered], key=lambda x: (x or ''))
    return ordered + extras


def _week_range(base_date):
    """base_date 를 포함하는 월~일(월요일 시작) 범위."""
    from datetime import timedelta
    dow = base_date.weekday()   # 월=0
    mon = base_date - timedelta(days=dow)
    sun = mon + timedelta(days=6)
    return mon, sun


def _full_week_label(week_label, base_date):
    mon, sun = _week_range(base_date)
    return f"{week_label}  ({mon.strftime('%Y.%m.%d')} ~ {sun.strftime('%Y.%m.%d')})"


def _apply_status_conditional(ws, data_range):
    ws.conditional_formatting.add(
        data_range,
        CellIsRule(operator='equal', formula=['"완료"'],
                   fill=PatternFill('solid', fgColor='D1FAE5'),
                   font=Font(name='맑은 고딕', size=10, bold=True, color='065F46')))
    ws.conditional_formatting.add(
        data_range,
        CellIsRule(operator='equal', formula=['"진행중"'],
                   fill=PatternFill('solid', fgColor='DBEAFE'),
                   font=Font(name='맑은 고딕', size=10, bold=True, color='1E40AF')))
    ws.conditional_formatting.add(
        data_range,
        CellIsRule(operator='equal', formula=['"미착수"'],
                   fill=PatternFill('solid', fgColor='F1F5F9'),
                   font=Font(name='맑은 고딕', size=10, color='64748B')))


# ══════════════════════════════════════════════════════════
# 인별 시트 (주간업무_인별) — 데이터 채움
# ══════════════════════════════════════════════════════════
def build_person_sheet(wb, week_label, base_date, tasks):
    ws = wb.create_sheet('주간업무_인별')
    # 컬럼 순서: 팀원 · 구분 · 업무구분 · 업무내용 · 이번주 한일 · 다음주 할일 · 이슈 · 시작일 · 완료 · 진척율 · 상태 · KEY
    widths = {'A': 10, 'B': 16, 'C': 10, 'D': 42, 'E': 32, 'F': 32, 'G': 22, 'H': 12, 'I': 12, 'J': 10, 'K': 10, 'L': 10}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.column_dimensions['L'].hidden = True

    last_col_letter = 'K'  # 병합 · 조건서식 등에서 사용

    ws.merge_cells(f'A1:{last_col_letter}1')
    ws['A1'] = '계리결산팀 주간업무 현황'
    ws['A1'].font = TITLE_FONT; ws['A1'].fill = TITLE_FILL; ws['A1'].alignment = CENTER
    ws.row_dimensions[1].height = 28

    ws.merge_cells(f'A2:{last_col_letter}2')
    ws['A2'] = _full_week_label(week_label, base_date) + f"   |   기준일 : {base_date.strftime('%Y.%m.%d')}"
    ws['A2'].font = SUB_FONT; ws['A2'].fill = SUB_FILL; ws['A2'].alignment = CENTER
    ws.row_dimensions[2].height = 22

    headers = ['팀원', '구분', '업무구분', '업무내용',
               '이번주 한 일', '다음주 할 일', '이슈 · 비고',
               '시작일', '완료(예정)', '진척율', '상태', '팀원KEY']
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = HEAD_FONT; c.fill = HEAD_FILL; c.alignment = CENTER; c.border = BORDER_ALL
    ws.row_dimensions[3].height = 26

    # 팀원별 그룹핑
    by_member = OrderedDict()
    for t in tasks:
        name = (t.get('member_name') or '').strip()
        if not name:
            continue
        by_member.setdefault(name, []).append(t)
    ordered_names = _sort_members(list(by_member.keys()))

    # 데이터 유효성
    dv_status = DataValidation(type='list', formula1='"미착수,진행중,완료"', allow_blank=True)
    dv_pct    = DataValidation(type='decimal', operator='between', formula1=0, formula2=1, allow_blank=True)
    dv_ext    = DataValidation(type='list', formula1=f'"{",".join(EXTENSION_TYPES)}"', allow_blank=True)
    ws.add_data_validation(dv_status)
    ws.add_data_validation(dv_pct)
    ws.add_data_validation(dv_ext)

    row = 4
    for name in ordered_names:
        member_tasks = by_member[name]
        by_cat = OrderedDict()
        for t in member_tasks:
            cat = (t.get('category') or '(미분류)').strip()
            by_cat.setdefault(cat, []).append(t)
        top = row
        for cat, items in by_cat.items():
            cat_top = row
            for t in items:
                # C: 업무구분(extension_type) · D: 업무내용 · E: 이번주 한일 · F: 다음주 할일 · G: 이슈
                ext = (t.get('extension_type') or '').strip()
                ws.cell(row=row, column=3, value=(ext or None))
                ws.cell(row=row, column=4, value=_prefix_task(t.get('task_content')))
                ws.cell(row=row, column=5, value=(t.get('this_week_done') or None))
                ws.cell(row=row, column=6, value=(t.get('next_week_plan') or None))
                ws.cell(row=row, column=7, value=(t.get('issue_note') or None))
                sd = _norm_date(t.get('start_date'))
                ed = _norm_date(t.get('end_date'))
                if sd is not None:
                    ws.cell(row=row, column=8, value=sd)
                if ed is not None:
                    ws.cell(row=row, column=9, value=ed)
                pg = _norm_progress(t.get('progress'))
                if pg is not None:
                    ws.cell(row=row, column=10, value=pg)
                st = (t.get('status') or '').strip()
                ws.cell(row=row, column=11, value=(st or None))
                ws.cell(row=row, column=12, value=name)
                # 스타일
                for col in range(1, 13):
                    c = ws.cell(row=row, column=col)
                    c.border = BORDER_ALL
                    c.font = BODY_FONT
                    c.alignment = CENTER if col in (3, 8, 9, 10, 11) else LEFT
                if isinstance(sd, date):
                    ws.cell(row=row, column=8).number_format = 'yyyy-mm-dd'
                if isinstance(ed, date):
                    ws.cell(row=row, column=9).number_format = 'yyyy-mm-dd'
                if pg is not None:
                    ws.cell(row=row, column=10).number_format = '0.0%'
                # 업무구분 색상 강조
                if ext in EXT_COLORS:
                    bg, fg = EXT_COLORS[ext]
                    cc = ws.cell(row=row, column=3)
                    cc.fill = PatternFill('solid', fgColor=bg)
                    cc.font = Font(name='맑은 고딕', size=10, bold=True, color=fg)
                ws.row_dimensions[row].height = 26
                row += 1
            if row - 1 > cat_top:
                ws.merge_cells(start_row=cat_top, start_column=2, end_row=row - 1, end_column=2)
            b = ws.cell(row=cat_top, column=2, value=cat)
            b.alignment = CENTER; b.font = BOLD_FONT
            b.fill = PatternFill('solid', fgColor='F1F5F9')

        if row - 1 > top:
            ws.merge_cells(start_row=top, start_column=1, end_row=row - 1, end_column=1)
        a = ws.cell(row=top, column=1, value=name)
        a.font = BOLD_FONT; a.fill = NAME_FILL; a.alignment = CENTER

        dv_status.add(f'K{top}:K{row - 1}')
        dv_pct.add(f'J{top}:J{row - 1}')
        dv_ext.add(f'C{top}:C{row - 1}')

    last_data = row - 1
    if last_data >= 4:
        _apply_status_conditional(ws, f'K4:K{last_data}')

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=11)
    ws.cell(row=row, column=1, value=(
        '※ 업무구분 : 신규 / 연장 (전주 이월) / 종료 (금주 완료) / 상시 (매주 반복) / 보류 (대기)   |   '
        '상태 : 완료(100%) · 진행중(0~99%) · 미착수(0%)'
    ))
    ws.cell(row=row, column=1).font = FOOT_FONT
    ws.cell(row=row, column=1).fill = FOOT_FILL
    ws.cell(row=row, column=1).alignment = LEFT

    ws.freeze_panes = 'A4'
    return ordered_names, last_data


# ══════════════════════════════════════════════════════════
# 요약 시트 — 인별 시트 참조
# ══════════════════════════════════════════════════════════
def build_summary_sheet(wb, week_label, base_date, ordered_names, person_last_row):
    ws = wb.create_sheet('요약')
    widths = {'A': 4, 'B': 12, 'C': 11, 'D': 10, 'E': 10, 'F': 10, 'G': 13}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    ws.merge_cells('B1:G1')
    ws['B1'] = '인별 과제현황 요약'
    ws['B1'].font = TITLE_FONT; ws['B1'].fill = TITLE_FILL; ws['B1'].alignment = CENTER
    ws.row_dimensions[1].height = 28

    ws.merge_cells('B2:G2')
    ws['B2'] = _full_week_label(week_label, base_date) + f"   |   기준일 : {base_date.strftime('%Y.%m.%d')}"
    ws['B2'].font = SUB_FONT; ws['B2'].fill = SUB_FILL; ws['B2'].alignment = CENTER
    ws.row_dimensions[2].height = 22

    for i, h in enumerate(['팀원', '과제 건수', '완료', '진행중', '미착수', '평균 진척율'], 2):
        c = ws.cell(row=4, column=i, value=h)
        c.font = HEAD_FONT; c.fill = HEAD_FILL; c.alignment = CENTER; c.border = BORDER_ALL
    ws.row_dimensions[4].height = 24

    # 인별 시트 컬럼 매핑 (확장 후):
    #   D = 업무내용, J = 진척율, K = 상태, L = 팀원KEY
    key_range = f"주간업무_인별!$L$4:$L${person_last_row}"
    status_range = f"주간업무_인별!$K$4:$K${person_last_row}"
    pct_range = f"주간업무_인별!$J$4:$J${person_last_row}"
    task_range = f"주간업무_인별!$D$4:$D${person_last_row}"

    r = 5
    for name in ordered_names:
        ws.cell(row=r, column=2, value=name).alignment = CENTER
        ws.cell(row=r, column=3, value=f'=COUNTIFS({key_range},B{r},{task_range},"<>")')
        ws.cell(row=r, column=4, value=f'=COUNTIFS({key_range},B{r},{task_range},"<>",{status_range},"완료")')
        ws.cell(row=r, column=5, value=f'=COUNTIFS({key_range},B{r},{task_range},"<>",{status_range},"진행중")')
        ws.cell(row=r, column=6, value=f'=COUNTIFS({key_range},B{r},{task_range},"<>",{status_range},"미착수")')
        ws.cell(row=r, column=7, value=f'=IFERROR(AVERAGEIFS({pct_range},{key_range},B{r},{pct_range},">=0"),"-")')
        for col in range(2, 8):
            c = ws.cell(row=r, column=col)
            c.border = BORDER_ALL; c.font = BODY_FONT
            if col > 2:
                c.alignment = CENTER
        ws.cell(row=r, column=7).number_format = '0.0%'
        ws.row_dimensions[r].height = 22
        r += 1

    total_r = r
    ws.cell(row=total_r, column=2, value='합계').font = Font(name='맑은 고딕', size=10, bold=True)
    ws.cell(row=total_r, column=2).alignment = CENTER
    ws.cell(row=total_r, column=2).fill = PatternFill('solid', fgColor='F1F5F9')
    for col in range(3, 7):
        letter = get_column_letter(col)
        cell = ws.cell(row=total_r, column=col, value=f'=SUM({letter}5:{letter}{r - 1})')
        cell.font = Font(name='맑은 고딕', size=10, bold=True)
        cell.alignment = CENTER
        cell.fill = PatternFill('solid', fgColor='F1F5F9')
    tc = ws.cell(row=total_r, column=7, value=f'=IFERROR(AVERAGEIFS({pct_range},{pct_range},">=0"),"-")')
    tc.number_format = '0.0%'; tc.font = Font(name='맑은 고딕', size=10, bold=True)
    tc.alignment = CENTER; tc.fill = PatternFill('solid', fgColor='F1F5F9')
    for col in range(2, 8):
        ws.cell(row=total_r, column=col).border = BORDER_ALL

    for offset, msg in enumerate([
        '※ 상태 구분 : 완료(진척율 100%) / 진행중(0% 초과 ~ 100% 미만) / 미착수(0%)',
        '※ 평균 진척율은 진척율 기재 과제만 대상',
    ], start=2):
        r2 = total_r + offset
        ws.merge_cells(start_row=r2, start_column=2, end_row=r2, end_column=7)
        ws.cell(row=r2, column=2, value=msg).font = FOOT_FONT
        ws.cell(row=r2, column=2).fill = FOOT_FILL
        ws.cell(row=r2, column=2).alignment = LEFT


# ══════════════════════════════════════════════════════════
# 통합 시트 (업무유형별) — 데이터 채움
# ══════════════════════════════════════════════════════════
def build_typegroup_sheet(wb, week_label, base_date, tasks):
    ws = wb.create_sheet('통합_업무유형별')
    # A: 세부구분 · B: 업무구분(ext) · C: 업무내용 · D: 이번주 한일 · E: 다음주 할일
    # F: 담당 · G: 시작 · H: 완료 · I: 진척율 · J: 상태 · K: 이슈 · L: TYPE
    widths = {'A': 22, 'B': 10, 'C': 42, 'D': 32, 'E': 32, 'F': 10, 'G': 12, 'H': 12, 'I': 10, 'J': 10, 'K': 20, 'L': 6}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.column_dimensions['L'].hidden = True

    ws.merge_cells('A1:K1')
    ws['A1'] = '계리결산팀 주간업무 현황 (업무유형별 통합)'
    ws['A1'].font = TITLE_FONT; ws['A1'].fill = TITLE_FILL; ws['A1'].alignment = CENTER
    ws.row_dimensions[1].height = 28

    ws.merge_cells('A2:K2')
    ws['A2'] = _full_week_label(week_label, base_date) + f"   |   기준일 : {base_date.strftime('%Y.%m.%d')}"
    ws['A2'].font = SUB_FONT; ws['A2'].fill = SUB_FILL; ws['A2'].alignment = CENTER
    ws.row_dimensions[2].height = 22

    headers = ['세부 구분', '업무구분', '업무내용',
               '이번주 한 일', '다음주 할 일',
               '담당', '시작일', '완료(예정)', '진척율', '상태', '이슈 · 비고', 'TYPE']
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = HEAD_FONT; c.fill = HEAD_FILL; c.alignment = CENTER; c.border = BORDER_ALL
    ws.row_dimensions[3].height = 26

    # 업무유형(Ⅰ~Ⅵ) 별 그룹핑
    by_type = OrderedDict((k, []) for k, _ in WORK_TYPES)
    for t in tasks:
        wt = (t.get('work_type') or '').strip()
        if wt not in by_type:
            wt = 'Ⅵ'   # 미지정은 기타로
        by_type[wt].append(t)

    dv_status = DataValidation(type='list', formula1='"미착수,진행중,완료"', allow_blank=True)
    dv_pct    = DataValidation(type='decimal', operator='between', formula1=0, formula2=1, allow_blank=True)
    dv_ext    = DataValidation(type='list', formula1=f'"{",".join(EXTENSION_TYPES)}"', allow_blank=True)
    ws.add_data_validation(dv_status)
    ws.add_data_validation(dv_pct)
    ws.add_data_validation(dv_ext)

    row = 4
    for k, label in WORK_TYPES:
        items = by_type[k]
        done = sum(1 for t in items if (_norm_progress(t.get('progress')) or 0) >= 1.0)
        pcs = [_norm_progress(t.get('progress')) for t in items if _norm_progress(t.get('progress')) is not None]
        avg = round(sum(pcs) / len(pcs) * 100) if pcs else 0
        # 카테고리 헤더 (A~E 라벨, F~K 통계)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        ws.cell(row=row, column=1, value=label).font = CAT_FONT
        ws.cell(row=row, column=1).fill = CAT_FILL
        ws.cell(row=row, column=1).alignment = LEFT
        ws.cell(row=row, column=1).border = BORDER_ALL
        ws.merge_cells(start_row=row, start_column=6, end_row=row, end_column=11)
        ws.cell(row=row, column=6, value=f"총 {len(items)}건   |   완료 {done}건   |   평균 진척율 {avg}%").font = SUMFONT
        ws.cell(row=row, column=6).fill = CAT_FILL
        ws.cell(row=row, column=6).alignment = CENTER
        ws.cell(row=row, column=6).border = BORDER_ALL
        ws.row_dimensions[row].height = 24
        row += 1

        by_detail = OrderedDict()
        for t in items:
            d = (t.get('work_type_detail') or '').strip() or '(세부 미지정)'
            by_detail.setdefault(d, []).append(t)
        for detail, group in by_detail.items():
            det_top = row
            for t in group:
                ext = (t.get('extension_type') or '').strip()
                ws.cell(row=row, column=2, value=(ext or None))
                ws.cell(row=row, column=3, value=(t.get('task_content') or '').strip())
                ws.cell(row=row, column=4, value=(t.get('this_week_done') or None))
                ws.cell(row=row, column=5, value=(t.get('next_week_plan') or None))
                ws.cell(row=row, column=6, value=(t.get('member_name') or ''))
                sd = _norm_date(t.get('start_date'))
                ed = _norm_date(t.get('end_date'))
                if sd is not None:
                    ws.cell(row=row, column=7, value=sd)
                if ed is not None:
                    ws.cell(row=row, column=8, value=ed)
                pg = _norm_progress(t.get('progress'))
                if pg is not None:
                    ws.cell(row=row, column=9, value=pg)
                st = (t.get('status') or '').strip()
                ws.cell(row=row, column=10, value=(st or None))
                ws.cell(row=row, column=11, value=(t.get('issue_note') or None))
                ws.cell(row=row, column=12, value=k)
                for col in range(1, 13):
                    c = ws.cell(row=row, column=col)
                    c.border = BORDER_ALL
                    c.font = BODY_FONT
                    c.alignment = CENTER if col in (2, 6, 7, 8, 9, 10) else LEFT
                if isinstance(sd, date):
                    ws.cell(row=row, column=7).number_format = 'yyyy-mm-dd'
                if isinstance(ed, date):
                    ws.cell(row=row, column=8).number_format = 'yyyy-mm-dd'
                if pg is not None:
                    ws.cell(row=row, column=9).number_format = '0.0%'
                if ext in EXT_COLORS:
                    bg, fg = EXT_COLORS[ext]
                    cc = ws.cell(row=row, column=2)
                    cc.fill = PatternFill('solid', fgColor=bg)
                    cc.font = Font(name='맑은 고딕', size=10, bold=True, color=fg)
                ws.row_dimensions[row].height = 26
                row += 1
            if row - 1 > det_top:
                ws.merge_cells(start_row=det_top, start_column=1, end_row=row - 1, end_column=1)
            ws.cell(row=det_top, column=1, value=detail).font = BOLD_FONT
            ws.cell(row=det_top, column=1).alignment = LEFT
            ws.cell(row=det_top, column=1).fill = PatternFill('solid', fgColor='F1F5F9')

            dv_status.add(f'J{det_top}:J{row - 1}')
            dv_pct.add(f'I{det_top}:I{row - 1}')
            dv_ext.add(f'B{det_top}:B{row - 1}')

    if row > 4:
        _apply_status_conditional(ws, f'J4:J{row - 1}')

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=11)
    ws.cell(row=row, column=1, value='※ 업무유형은 팀장이 재분류한 것으로, 인별 시트의 구분과 상이할 수 있음').font = FOOT_FONT
    ws.cell(row=row, column=1).fill = FOOT_FILL
    ws.cell(row=row, column=1).alignment = LEFT
    ws.freeze_panes = 'A4'


def main():
    ap = argparse.ArgumentParser(description='주간업무 리포트 생성 (데이터 주입)')
    ap.add_argument('--data', required=True, help='JSON 파일 경로 (weekly_tasks 배열)')
    ap.add_argument('--week', required=True, help="주차 라벨 (예: '26년 9월 2주차)")
    ap.add_argument('--base-date', required=True, help='기준일 YYYY-MM-DD')
    ap.add_argument('--out', required=True, help='출력 xlsx 경로')
    ap.add_argument('--view', choices=['person', 'typegroup', 'all'], default='all')
    args = ap.parse_args()

    if not os.path.exists(args.data):
        print(f'ERROR: 데이터 파일 없음: {args.data}', file=sys.stderr)
        sys.exit(2)

    with open(args.data, encoding='utf-8') as f:
        tasks = json.load(f)
    if not isinstance(tasks, list):
        print('ERROR: 데이터는 JSON 배열이어야 합니다.', file=sys.stderr)
        sys.exit(3)

    base_date = date.fromisoformat(args.base_date)

    wb = Workbook()
    # 기본 시트 제거 (new_sheet 방식 사용)
    wb.remove(wb.active)

    ordered_names, person_last = [], 3
    if args.view in ('person', 'all'):
        ordered_names, person_last = build_person_sheet(wb, args.week, base_date, tasks)
        build_summary_sheet(wb, args.week, base_date, ordered_names, person_last)
    if args.view in ('typegroup', 'all'):
        build_typegroup_sheet(wb, args.week, base_date, tasks)

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    wb.save(args.out)
    print(f'OK: {args.out}  |  tasks={len(tasks)}  |  view={args.view}')


if __name__ == '__main__':
    main()
