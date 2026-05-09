from __future__ import annotations

from typing import Iterable

from db import get_conn, get_metadata


class QueryEngineError(ValueError):
    pass


def _ensure_period(period: str) -> None:
    periods = get_loaded_periods()
    if period not in periods:
        raise QueryEngineError(
            f'[오류] 요청한 기준월 데이터가 아직 적재되지 않았습니다.\n'
            f'현재 적재 기준: {", ".join(periods) if periods else "없음"}\n'
            '명령어 예시: /periods'
        )


def get_loaded_periods() -> list[str]:
    value = get_metadata('loaded_periods', '')
    if not value:
        return []
    return [x for x in value.split(',') if x]


def get_balance_single(period: str, metric: str) -> float:
    _ensure_period(period)
    with get_conn() as conn:
        row = conn.execute(
            'SELECT amount FROM fact_balance WHERE period_yyyymm=? AND model=? AND metric=?',
            (period, 'TOTAL', metric),
        ).fetchone()
    if not row:
        raise QueryEngineError(f'[오류] {period} 기준 {metric} 데이터가 없습니다.')
    return float(row['amount'])


def get_balance_by_model(period: str, metrics: Iterable[str]) -> list[dict]:
    _ensure_period(period)
    metrics = list(metrics)
    placeholders = ','.join('?' for _ in metrics)
    with get_conn() as conn:
        rows = conn.execute(
            f'''
            SELECT model, metric, amount
            FROM fact_balance
            WHERE period_yyyymm=?
              AND metric IN ({placeholders})
            ORDER BY CASE model WHEN 'NP' THEN 1 WHEN 'IDP' THEN 2 WHEN 'VFA' THEN 3 WHEN 'TOTAL' THEN 4 ELSE 99 END,
                     metric
            ''',
            [period, *metrics],
        ).fetchall()
    result: dict[str, dict] = {}
    for row in rows:
        result.setdefault(row['model'], {'model': row['model']})[row['metric']] = float(row['amount'])
    ordered = [result[m] for m in ['NP', 'IDP', 'VFA', 'TOTAL'] if m in result]
    if not ordered:
        raise QueryEngineError(f'[오류] {period} 기준 회계모형별 데이터가 없습니다.')
    return ordered


def get_pl_summary(period: str) -> dict:
    _ensure_period(period)
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT scope, line_item, amount
            FROM fact_pl
            WHERE period_yyyymm=? AND model='TOTAL'
              AND line_item IN ('보험손익_차감전', '간접사업비', '보험손익_차감후')
            ''',
            (period,),
        ).fetchall()
    bucket: dict[str, dict[str, float]] = {'당월': {}, '누적': {}}
    for row in rows:
        bucket[row['scope']][row['line_item']] = float(row['amount'])
    if not bucket['당월'] and not bucket['누적']:
        raise QueryEngineError(f'[오류] {period} 기준 보험손익 데이터가 없습니다.')
    return bucket


def get_pl_by_model(period: str, scope: str) -> list[dict]:
    _ensure_period(period)
    if scope not in {'당월', '누적'}:
        raise QueryEngineError('[오류] 손익 조회 범위는 당월 또는 누적이어야 합니다.')
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT model, amount
            FROM fact_pl
            WHERE period_yyyymm=? AND scope=? AND line_item='보험손익_차감전'
            ORDER BY CASE model WHEN 'NP' THEN 1 WHEN 'IDP' THEN 2 WHEN 'VFA' THEN 3 WHEN 'TOTAL' THEN 4 ELSE 99 END
            ''',
            (period, scope),
        ).fetchall()
    return [{'model': row['model'], 'amount': float(row['amount'])} for row in rows]


def get_csm_movement(period: str, scope: str, model: str) -> list[dict]:
    _ensure_period(period)
    if scope not in {'당월', '누적'}:
        raise QueryEngineError('[오류] CSM 무브먼트 조회 범위는 당월 또는 누적이어야 합니다.')
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT start_yyyymm, end_yyyymm, movement_code, amount
            FROM fact_csm_movement
            WHERE end_yyyymm=? AND scope=? AND model=?
            ORDER BY display_order
            ''',
            (period, scope, model),
        ).fetchall()
    if not rows:
        raise QueryEngineError(f'[오류] {period} 기준 {model} CSM 무브먼트 데이터가 없습니다.')
    return [dict(row) for row in rows]


def get_csm_movement_compare(period: str, scope: str) -> list[dict]:
    _ensure_period(period)
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT model,
                   MAX(CASE WHEN movement_code='기시' THEN amount END) AS start_amount,
                   MAX(CASE WHEN movement_code='증감' THEN amount END) AS delta_amount,
                   MAX(CASE WHEN movement_code='기말' THEN amount END) AS end_amount,
                   MIN(start_yyyymm) AS start_yyyymm,
                   MAX(end_yyyymm) AS end_yyyymm
            FROM fact_csm_movement
            WHERE end_yyyymm=? AND scope=?
              AND model IN ('NP', 'IDP', 'VFA', 'TOTAL')
            GROUP BY model
            ORDER BY CASE model WHEN 'NP' THEN 1 WHEN 'IDP' THEN 2 WHEN 'VFA' THEN 3 WHEN 'TOTAL' THEN 4 ELSE 99 END
            ''',
            (period, scope),
        ).fetchall()
    if not rows:
        raise QueryEngineError(f'[오류] {period} 기준 3모형 CSM 비교 데이터가 없습니다.')
    return [dict(row) for row in rows]
