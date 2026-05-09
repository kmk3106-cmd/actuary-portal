"""
공시이율 엑셀 → SQLite 자동 입력
Usage: python public_rate_entry.py --file <xlsx> --db <sqlite_path> [--ym YYYYMM]

Expected Excel columns (Korean/English both accepted):
  기준월 / ym / year_month  : YYYYMM or YYYY-MM or YYYY/MM
  상품유형 / product_type / 유형 / 분류
  이율 / rate / 공시이율 / interest_rate  : numeric (%, e.g. 3.5 means 3.5%)
  비고 / note / remarks  (optional)
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
    'ym':           ['기준월','ym','year_month','기준연월','연월','기준년월'],
    'product_type': ['상품유형','유형','분류','product_type','상품종류','종류'],
    'rate':         ['이율','공시이율','rate','interest_rate','금리','이자율'],
    'note':         ['비고','note','remarks','메모'],
}

def detect_columns(headers):
    """Return mapping: field -> col_index, or raise if required field missing."""
    lower_headers = [str(h).strip().lower() if h else '' for h in headers]
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            try:
                idx = lower_headers.index(alias.lower())
                mapping[field] = idx
                break
            except ValueError:
                continue
    missing = [f for f in ['ym','product_type','rate'] if f not in mapping]
    if missing:
        found = [str(h) for h in headers if h]
        raise ValueError(f"필수 컬럼 없음: {missing}. 발견된 컬럼: {found}")
    return mapping

def normalize_ym(val):
    """Convert various date formats to YYYYMM string."""
    s = str(val).strip().replace('-','').replace('/','').replace('.','')
    s = re.sub(r'[^\d]', '', s)
    if len(s) >= 6:
        return s[:6]
    raise ValueError(f"기준월 형식 오류: {val}")

def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS public_interest_rate (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ym TEXT NOT NULL,
            product_type TEXT NOT NULL,
            rate REAL NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(ym, product_type)
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
            if args.ym and ym != args.ym:
                ym = args.ym  # override with provided ym
            product_type = str(row[mapping['product_type']]).strip()
            rate = float(str(row[mapping['rate']]).replace('%','').strip())
            note = str(row[mapping.get('note', -1)]).strip() if mapping.get('note') is not None else ''

            # Upsert
            existing = conn.execute(
                "SELECT id FROM public_interest_rate WHERE ym=? AND product_type=?", (ym, product_type)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE public_interest_rate SET rate=?, note=? WHERE ym=? AND product_type=?",
                    (rate, note, ym, product_type)
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO public_interest_rate (ym, product_type, rate, note) VALUES (?,?,?,?)",
                    (ym, product_type, rate, note)
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
