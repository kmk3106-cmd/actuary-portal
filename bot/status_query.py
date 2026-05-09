"""
봇 쿼리 로그 조회 — server.js에서 child_process로 호출
Usage: python status_query.py --db <path> [--limit <n>]
Output: JSON (마지막 줄)
"""
import argparse, sqlite3, json, sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--limit', type=int, default=50)
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(json.dumps({'logs': [], 'total': 0, 'last_query_at': None,
                          'status': 'no_db'}, ensure_ascii=False))
        return

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bot_query_logs'"
        ).fetchone()
        if not tbl:
            conn.close()
            print(json.dumps({'logs': [], 'total': 0, 'last_query_at': None,
                              'status': 'no_table'}, ensure_ascii=False))
            return

        total = conn.execute('SELECT COUNT(*) FROM bot_query_logs').fetchone()[0]
        today_count = conn.execute(
            "SELECT COUNT(*) FROM bot_query_logs WHERE date(logged_at_utc) = date('now')"
        ).fetchone()[0]
        last_at = conn.execute(
            'SELECT MAX(logged_at_utc) FROM bot_query_logs'
        ).fetchone()[0]
        rows = conn.execute(
            '''SELECT id, logged_at_utc, username, raw_query,
                      parsed_intent, parsed_period, parsed_metric,
                      status, error_message
               FROM bot_query_logs
               ORDER BY id DESC LIMIT ?''',
            (args.limit,)
        ).fetchall()
        conn.close()

        print(json.dumps({
            'logs': [dict(r) for r in rows],
            'total': total,
            'today': today_count,
            'last_query_at': last_at,
            'status': 'ok',
        }, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'logs': [], 'total': 0, 'today': 0,
                          'last_query_at': None, 'status': 'error',
                          'error': str(exc)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
