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

# ══════════════════════════════════════════════════════════
# 표준분류(카테고리 정규화) — 통합 엑셀에서 유사 표기 통합 + 세부미지정 매칭
#   SSOT: reports/category_rules.json (없으면 아래 임베디드 기본값 사용)
#   IFRS17 과 IFRS4 는 다른 회계기준 → 절대 병합 금지 (규칙 순서로 각각 먼저 매칭)
# ══════════════════════════════════════════════════════════
DEFAULT_CATEGORY_RULES = {
    'fallback_label': '기타',
    'rules': [
        {'label': 'IFRS17 결산', 'any': ['ifrs17', 'ifrs 17', 'ifrs-17']},
        {'label': 'IFRS4 결산',  'any': ['ifrs4', 'ifrs 4', 'ifrs-4']},
        {'label': '결산 실무',   'any': ['tbasb', '준비금', '비금', '실효', '만기', '생존', '사고', '사차',
                                         '위보', '보험료 분해', '보험료분해', '계리계약', '최초인식', '후속측정',
                                         '보증준비금', '평균기준가', '잔존만기', '결산대상계약']},
        {'label': '차세대',      'any': ['차세대', '통합테스트', 'uat', '3차 통합']},
        {'label': '대내외 대응', 'any': ['대내외', '감독원', '금융감독원', '계리법인', '회계법인', '발송',
                                         '요청자료', '제출', 'cpc', '업무보고서', '질문 대응', '질문대응',
                                         '심의위원회', '적정성 검토', '적정성검토']},
        {'label': '모델·시스템 관리', 'any': ['모델', '시스템', '로직', '마이그레이션', 'output table', 'output',
                                              '고도화', '배포', '테이블 생성', 'logtable', 'irimb']},
        {'label': '결산 실무',   'any': ['결산', '구월보', '보종', '보종코드']},
        {'label': '관리회계·기타', 'any': ['관리회계', '사업계획', '시책', '프로모션', '제도 변경', '제도변경', '이관']},
    ],
}

# 통합 시트 그룹 표기 순서
CANONICAL_ORDER = ['IFRS17 결산', 'IFRS4 결산', '결산 실무', '차세대',
                   '모델·시스템 관리', '대내외 대응', '관리회계·기타', '기타']


def load_category_rules(path=None):
    """rules JSON 로드 (인자 → reports/category_rules.json → 임베디드 기본값)."""
    candidates = []
    if path:
        candidates.append(path)
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'category_rules.json'))
    for p in candidates:
        try:
            if p and os.path.exists(p):
                with open(p, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get('rules'):
                    return data
        except Exception as e:  # noqa: BLE001
            sys.stderr.write('[category_rules 로드 실패, 기본값 사용] %s\n' % e)
    return DEFAULT_CATEGORY_RULES


def _match_category_rules(text, rules):
    t = (text or '').lower()
    if not t.strip():
        return None
    for r in rules.get('rules', []):
        for kw in r.get('any', []):
            if kw and kw.lower() in t:
                return r.get('label')
    return None


# 미지정 성격의 구분값 — 업무내용으로 추론 (요구사항 #2: 세부미지정 매칭)
GENERIC_CATEGORIES = {'기타', '기타업무', '미분류', '미지정', '(미분류)', '(미지정)', '(세부 미지정)', 'etc', '-'}


def normalize_category(category, task_content, work_type_detail=None, rules=None):
    """구분/업무내용을 표준분류 라벨로 정규화.
    1) 구분(category)이 있고 '미지정 성격'이 아니면 → 구분 텍스트로 매칭 (없으면 원문 유지)
    2) 구분이 비었거나 '기타/미분류/미지정' 이면 → 세부구분+업무내용으로 추론
    3) 그래도 없으면 fallback('기타')
    """
    rules = rules or DEFAULT_CATEGORY_RULES
    cat = (category or '').strip()
    if cat and cat not in GENERIC_CATEGORIES:
        lbl = _match_category_rules(cat, rules)
        return lbl if lbl else cat
    # 구분이 비었거나 미지정 성격 → 세부구분 + 업무내용으로 추론
    text = ' '.join([str(work_type_detail or ''), str(task_content or '')])
    lbl = _match_category_rules(text, rules)
    if lbl:
        return lbl
    wtd = (work_type_detail or '').strip()
    if wtd and wtd not in GENERIC_CATEGORIES:
        return wtd
    return rules.get('fallback_label', '기타')

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
def build_person_sheet(wb, week_label, base_date, tasks, cat_rules=None):
    ws = wb.create_sheet('주간업무_인별')
    # 컬럼: 팀원 · 구분(원본) · 표준분류 · 업무구분 · 업무내용 · 이번주 · 다음주 · 이슈 · 시작 · 완료 · 진척율 · 상태 · KEY
    widths = {'A': 10, 'B': 16, 'C': 15, 'D': 10, 'E': 42, 'F': 32, 'G': 32, 'H': 22, 'I': 12, 'J': 12, 'K': 10, 'L': 10, 'M': 10}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.column_dimensions['M'].hidden = True

    last_col_letter = 'L'  # 병합 · 조건서식 등에서 사용 (KEY=M 제외)

    ws.merge_cells(f'A1:{last_col_letter}1')
    ws['A1'] = '계리결산팀 주간업무 현황'
    ws['A1'].font = TITLE_FONT; ws['A1'].fill = TITLE_FILL; ws['A1'].alignment = CENTER
    ws.row_dimensions[1].height = 28

    ws.merge_cells(f'A2:{last_col_letter}2')
    ws['A2'] = _full_week_label(week_label, base_date) + f"   |   기준일 : {base_date.strftime('%Y.%m.%d')}"
    ws['A2'].font = SUB_FONT; ws['A2'].fill = SUB_FILL; ws['A2'].alignment = CENTER
    ws.row_dimensions[2].height = 22

    headers = ['팀원', '구분', '표준분류', '업무구분', '업무내용',
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
                # C: 표준분류 · D: 업무구분(ext) · E: 업무내용 · F: 이번주 · G: 다음주 · H: 이슈
                std = normalize_category(t.get('category'), t.get('task_content'),
                                         t.get('work_type_detail'), cat_rules)
                ext = (t.get('extension_type') or '').strip()
                ws.cell(row=row, column=3, value=std)
                ws.cell(row=row, column=4, value=(ext or None))
                ws.cell(row=row, column=5, value=_prefix_task(t.get('task_content')))
                ws.cell(row=row, column=6, value=(t.get('this_week_done') or None))
                ws.cell(row=row, column=7, value=(t.get('next_week_plan') or None))
                ws.cell(row=row, column=8, value=(t.get('issue_note') or None))
                sd = _norm_date(t.get('start_date'))
                ed = _norm_date(t.get('end_date'))
                if sd is not None:
                    ws.cell(row=row, column=9, value=sd)
                if ed is not None:
                    ws.cell(row=row, column=10, value=ed)
                pg = _norm_progress(t.get('progress'))
                if pg is not None:
                    ws.cell(row=row, column=11, value=pg)
                st = (t.get('status') or '').strip()
                ws.cell(row=row, column=12, value=(st or None))
                ws.cell(row=row, column=13, value=name)
                # 스타일
                for col in range(1, 14):
                    c = ws.cell(row=row, column=col)
                    c.border = BORDER_ALL
                    c.font = BODY_FONT
                    c.alignment = CENTER if col in (3, 4, 9, 10, 11, 12) else LEFT
                if isinstance(sd, date):
                    ws.cell(row=row, column=9).number_format = 'yyyy-mm-dd'
                if isinstance(ed, date):
                    ws.cell(row=row, column=10).number_format = 'yyyy-mm-dd'
                if pg is not None:
                    ws.cell(row=row, column=11).number_format = '0.0%'
                # 업무구분 색상 강조
                if ext in EXT_COLORS:
                    bg, fg = EXT_COLORS[ext]
                    cc = ws.cell(row=row, column=4)
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

        dv_status.add(f'L{top}:L{row - 1}')
        dv_pct.add(f'K{top}:K{row - 1}')
        dv_ext.add(f'D{top}:D{row - 1}')

    last_data = row - 1
    if last_data >= 4:
        _apply_status_conditional(ws, f'L4:L{last_data}')

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)
    ws.cell(row=row, column=1, value=(
        '※ 업무구분 : 신규 / 연장 (전주 이월) / 종료 (금주 완료) / 상시 (매주 반복) / 보류 (대기)   |   '
        '표준분류 : 유사 업무 자동 통합 분류   |   상태 : 완료(100%) · 진행중(0~99%) · 미착수(0%)'
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

    # 인별 시트 컬럼 매핑 (표준분류 열 추가로 +1 시프트):
    #   E = 업무내용, K = 진척율, L = 상태, M = 팀원KEY
    key_range = f"주간업무_인별!$M$4:$M${person_last_row}"
    status_range = f"주간업무_인별!$L$4:$L${person_last_row}"
    pct_range = f"주간업무_인별!$K$4:$K${person_last_row}"
    task_range = f"주간업무_인별!$E$4:$E${person_last_row}"

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
def build_typegroup_sheet(wb, week_label, base_date, tasks, cat_rules=None):
    ws = wb.create_sheet('통합_표준분류별')
    # A: 구분(원본) · B: 업무구분(ext) · C: 업무내용 · D: 이번주 한일 · E: 다음주 할일
    # F: 담당 · G: 시작 · H: 완료 · I: 진척율 · J: 상태 · K: 이슈 · L: 표준분류(hidden)
    widths = {'A': 18, 'B': 10, 'C': 42, 'D': 32, 'E': 32, 'F': 10, 'G': 12, 'H': 12, 'I': 10, 'J': 10, 'K': 20, 'L': 6}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.column_dimensions['L'].hidden = True

    ws.merge_cells('A1:K1')
    ws['A1'] = '계리결산팀 주간업무 현황 (표준분류별 통합)'
    ws['A1'].font = TITLE_FONT; ws['A1'].fill = TITLE_FILL; ws['A1'].alignment = CENTER
    ws.row_dimensions[1].height = 28

    ws.merge_cells('A2:K2')
    ws['A2'] = _full_week_label(week_label, base_date) + f"   |   기준일 : {base_date.strftime('%Y.%m.%d')}"
    ws['A2'].font = SUB_FONT; ws['A2'].fill = SUB_FILL; ws['A2'].alignment = CENTER
    ws.row_dimensions[2].height = 22

    headers = ['구분(원본)', '업무구분', '업무내용',
               '이번주 한 일', '다음주 할 일',
               '담당', '시작일', '완료(예정)', '진척율', '상태', '이슈 · 비고', '표준분류']
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = HEAD_FONT; c.fill = HEAD_FILL; c.alignment = CENTER; c.border = BORDER_ALL
    ws.row_dimensions[3].height = 26

    # 표준분류 기준 그룹핑 (유사 업무 통합 · 세부미지정 매칭)
    by_std = OrderedDict()
    for t in tasks:
        std = normalize_category(t.get('category'), t.get('task_content'),
                                 t.get('work_type_detail'), cat_rules)
        by_std.setdefault(std, []).append(t)
    ordered_stds = [c for c in CANONICAL_ORDER if c in by_std] + \
                   [c for c in by_std.keys() if c not in CANONICAL_ORDER]

    dv_status = DataValidation(type='list', formula1='"미착수,진행중,완료"', allow_blank=True)
    dv_pct    = DataValidation(type='decimal', operator='between', formula1=0, formula2=1, allow_blank=True)
    dv_ext    = DataValidation(type='list', formula1=f'"{",".join(EXTENSION_TYPES)}"', allow_blank=True)
    ws.add_data_validation(dv_status)
    ws.add_data_validation(dv_pct)
    ws.add_data_validation(dv_ext)

    row = 4
    for std in ordered_stds:
        items = by_std[std]
        done = sum(1 for t in items if (_norm_progress(t.get('progress')) or 0) >= 1.0)
        pcs = [_norm_progress(t.get('progress')) for t in items if _norm_progress(t.get('progress')) is not None]
        avg = round(sum(pcs) / len(pcs) * 100) if pcs else 0
        # 표준분류 헤더 (A~E 라벨, F~K 통계)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        ws.cell(row=row, column=1, value=std).font = CAT_FONT
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

        grp_top = row
        # 그룹 내 정렬: 원본 구분 → 담당자 (유사 표기끼리 인접)
        for t in sorted(items, key=lambda x: ((x.get('category') or '').strip(),
                                              (x.get('member_name') or ''))):
            ext = (t.get('extension_type') or '').strip()
            ws.cell(row=row, column=1, value=((t.get('category') or '').strip() or '(미분류)'))
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
            ws.cell(row=row, column=12, value=std)
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

        dv_status.add(f'J{grp_top}:J{row - 1}')
        dv_pct.add(f'I{grp_top}:I{row - 1}')
        dv_ext.add(f'B{grp_top}:B{row - 1}')

    if row > 4:
        _apply_status_conditional(ws, f'J4:J{row - 1}')

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=11)
    ws.cell(row=row, column=1, value=(
        '※ 표준분류는 구분/업무내용을 기준으로 유사 업무를 자동 통합한 값입니다 '
        '(IFRS17·IFRS4는 분리). 원본 구분은 A열에 그대로 표기.'
    )).font = FOOT_FONT
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
    ap.add_argument('--category-rules', default=None,
                    help='표준분류 규칙 JSON 경로 (기본: reports/category_rules.json)')
    args = ap.parse_args()

    cat_rules = load_category_rules(args.category_rules)

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
        ordered_names, person_last = build_person_sheet(wb, args.week, base_date, tasks, cat_rules)
        build_summary_sheet(wb, args.week, base_date, ordered_names, person_last)
    if args.view in ('typegroup', 'all'):
        build_typegroup_sheet(wb, args.week, base_date, tasks, cat_rules)

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    wb.save(args.out)
    print(f'OK: {args.out}  |  tasks={len(tasks)}  |  view={args.view}')


if __name__ == '__main__':
    main()
