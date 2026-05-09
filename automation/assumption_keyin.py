"""
가정 키인 엑셀 → SQLite 자동 처리
Usage: python assumption_keyin.py --file <xlsx> --db <sqlite_path> [--ym YYYYMM]

Expected Excel columns:
  기준월 / ym          : YYYYMM
  모형구분 / model_type : NP / IDP / VFA
  가정항목 / assumption_item / 항목 / item
  가정값 / value / 값  : numeric
  단위 / unit          : % 또는 명/천명 등 (optional)
  비고 / note          (optional)
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
    'ym':              ['기준월','ym','year_month','기준연월','연월'],
    'model_type':      ['모형구분','모형','model_type','model','구분'],
    'assumption_item': ['가정항목','항목','assumption_item','item','가정명'],
    'value':           ['가정값','값','value','val','수치'],
    'unit':            ['단위','unit','units'],
    'note':            ['비고','note','remarks','메모'],
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
    missing = [f for f in ['ym','model_type','assumption_item','value'] if f not in mapping]
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
        CREATE TABLE IF NOT EXISTS model_assumptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ym TEXT NOT NULL,
            model_type TEXT NOT NULL,
            assumption_item TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(ym, model_type, assumption_item)
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
            model_type = str(row[mapping['model_type']]).strip().upper()
            assumption_item = str(row[mapping['assumption_item']]).strip()
            val_raw = str(row[mapping['value']]).replace('%','').strip()
            value = float(val_raw)
            unit = str(row[mapping['unit']]).strip() if mapping.get('unit') is not None else ''
            note = str(row[mapping['note']]).strip() if mapping.get('note') is not None else ''

            existing = conn.execute(
                "SELECT id FROM model_assumptions WHERE ym=? AND model_type=? AND assumption_item=?",
                (ym, model_type, assumption_item)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE model_assumptions SET value=?, unit=?, note=? WHERE ym=? AND model_type=? AND assumption_item=?",
                    (value, unit, note, ym, model_type, assumption_item)
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO model_assumptions (ym, model_type, assumption_item, value, unit, note) VALUES (?,?,?,?,?,?)",
                    (ym, model_type, assumption_item, value, unit, note)
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
