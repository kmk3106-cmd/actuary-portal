from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from settings import DB_PATH


SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_balance (
    period_yyyymm TEXT NOT NULL,
    model TEXT NOT NULL,
    metric TEXT NOT NULL,
    amount REAL NOT NULL,
    PRIMARY KEY (period_yyyymm, model, metric)
);

CREATE TABLE IF NOT EXISTS fact_pl (
    period_yyyymm TEXT NOT NULL,
    scope TEXT NOT NULL,
    model TEXT NOT NULL,
    line_item TEXT NOT NULL,
    amount REAL NOT NULL,
    PRIMARY KEY (period_yyyymm, scope, model, line_item)
);

CREATE TABLE IF NOT EXISTS fact_csm_movement (
    start_yyyymm TEXT NOT NULL,
    end_yyyymm TEXT NOT NULL,
    scope TEXT NOT NULL,
    model TEXT NOT NULL,
    movement_code TEXT NOT NULL,
    amount REAL NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (start_yyyymm, end_yyyymm, scope, model, movement_code)
);

CREATE TABLE IF NOT EXISTS bot_query_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at_utc TEXT NOT NULL,
    telegram_user_id TEXT,
    username TEXT,
    chat_id TEXT,
    raw_query TEXT NOT NULL,
    parsed_intent TEXT,
    parsed_period TEXT,
    parsed_scope TEXT,
    parsed_metric TEXT,
    parsed_model TEXT,
    status TEXT NOT NULL,
    error_message TEXT
);
'''


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def set_metadata(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO metadata(key, value) VALUES(?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (key, value),
        )


def get_metadata(key: str, default: str = '') -> str:
    with get_conn() as conn:
        row = conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default


def log_query(
    telegram_user_id: str | None,
    username: str | None,
    chat_id: str | None,
    raw_query: str,
    parsed_intent: str | None,
    parsed_period: str | None,
    parsed_scope: str | None,
    parsed_metric: str | None,
    parsed_model: str | None,
    status: str,
    error_message: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO bot_query_logs (
                logged_at_utc, telegram_user_id, username, chat_id, raw_query,
                parsed_intent, parsed_period, parsed_scope, parsed_metric,
                parsed_model, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                datetime.now(timezone.utc).isoformat(timespec='seconds'),
                telegram_user_id,
                username,
                chat_id,
                raw_query,
                parsed_intent,
                parsed_period,
                parsed_scope,
                parsed_metric,
                parsed_model,
                status,
                error_message,
            ),
        )
