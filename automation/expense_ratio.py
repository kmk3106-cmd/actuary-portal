"""
예정사업비율 엑셀 → SQLite 자동 처리
Usage: python expense_ratio.py --file <xlsx> --db <sqlite_path> [--ym YYYYMM]

Expected Excel columns:
  기준월 / ym           : YYYYMM
  상품군 / product_group / 상품 / 분류
  예정사업비율 / expense_ratio / ratio / 비율  : numeric (e.g. 12.5 means 12.5%)
  비고 / note            (optional)
"""
import argparse, sqlite3, json, sys, re
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("오류: openpyxl 미설치. 'pip install openpyxl' 실행 후 다시 시도하세요.")
    print(json.dumps({"status":"error","message":"openpyxl not installed","rows_inserted":0,"rows_updated":0,"rows_failed":0}))
    sys.exit(1)

COLUMN_ALIASES = {
    'ym':            ['기준월','ym','year_month','기준연월','연월'],
    'product_group': ['상품군','상품','분류','product_group','group','상품분류','상품그룹'],
    'ratio':         ['예정사업비율','비율','ratio','expense_ratio','사업비율','예정비율'],
    'note':          ['비고','note','remarks','메모'],
}

def detect_columns(headers):
    lower_headers = [str(h).strip().lower() if h else '' for h in headers]
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            try:
                mapping[field] = lower_headers.index(alias.lower())
                break
            except ValueError:
                continue
    missing = [f for f in ['ym','product_group','ratio'] if f not in mapping]
    if missing:
        found = [str(h) for h in headers if h]
        raise ValueError(f"필수 컬럼 없음: {missing}. 발견된 컬럼: {found}")
    return mapping

def normalize_ym(val):
    s = re.sub(r'[^\d]', '', str(val).strip())
    if len(s) >= 6:
        return s[:6]
    raise ValueError(f"기준월 형식 오류: {val}")

def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expense_ratio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ym TEXT NOT NULL,
            product_group TEXT NOT NULL,
            ratio REAL NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(ym, product_group)
        )
    """)
    conn.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--db', required=True)
    ap.add_argument('--ym', default='')
    args = ap.parse_args()

    print(f"처리중: 파일 열기 → {Path(args.file).name}")
    wb = openpyxl.load_workbook(args.file, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("엑셀 파일이 비어 있습니다.")

    headers = rows[0]
    print(f"처리중: 헤더 감지 중... ({len(headers)}개 컬럼)")
    mapping = detect_columns(headers)
    print(f"처리중: 컬럼 매핑 완료 → {mapping}")

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    ensure_table(conn)

    inserted = updated = failed = 0
    data_rows = rows[1:]
    print(f"처리중: {len(data_rows)}개 행 처리 시작")

    for i, row in enumerate(data_rows, 1):
        try:
            if all(v is None or str(v).strip() == '' for v in row):
                continue
            ym_raw = row[mapping['ym']]
            if ym_raw is None or str(ym_raw).strip() == '':
                continue
            ym = normalize_ym(ym_raw)
            if args.ym:
                ym = args.ym
            product_group = str(row[mapping['product_group']]).strip()
            ratio_raw = str(row[mapping['ratio']]).replace('%','').strip()
            ratio = float(ratio_raw)
            note = str(row[mapping['note']]).strip() if mapping.get('note') is not None else ''

            existing = conn.execute(
                "SELECT id FROM expense_ratio WHERE ym=? AND product_group=?",
                (ym, product_group)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE expense_ratio SET ratio=?, note=? WHERE ym=? AND product_group=?",
                    (ratio, note, ym, product_group)
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO expense_ratio (ym, product_group, ratio, note) VALUES (?,?,?,?)",
                    (ym, product_group, ratio, note)
                )
                inserted += 1
            if i % 10 == 0:
                print(f"처리중: {i}/{len(data_rows)} 행 완료")
        except Exception as e:
            failed += 1
            print(f"경고: 행 {i} 처리 실패 — {e}")

    conn.commit()
    conn.close()

    total = inserted + updated
    msg = f"처리 완료: 총 {total}건 (신규 {inserted}건, 업데이트 {updated}건, 실패 {failed}건)"
    print(msg)
    print(json.dumps({
        "status": "success" if failed == 0 or total > 0 else "error",
        "message": msg,
        "rows_inserted": inserted,
        "rows_updated": updated,
        "rows_failed": failed
    }, ensure_ascii=False))

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"오류: {e}")
        print(json.dumps({"status":"error","message":str(e),"rows_inserted":0,"rows_updated":0,"rows_failed":0}, ensure_ascii=False))
        sys.exit(1)
