from __future__ import annotations


def fmt_amount(value: float | int | None) -> str:
    if value is None:
        return '-'
    return f'{value:,.2f}'


def range_label(period: str, scope: str) -> str:
    if scope == '월말':
        return f'기말({period})'
    if scope == '당월':
        y = int(period[:4])
        m = int(period[4:6])
        if m == 1:
            prev = f'{y-1}12'
        else:
            prev = f'{y}{m-1:02d}'
        return f'기시({prev}) → 기말({period})'
    if scope == '누적':
        return f'기시({int(period[:4])-1}12) → 기말({period})'
    return period


def format_balance_single(period: str, metric: str, amount: float) -> str:
    return (
        '[조회결과]\n'
        f'지표: {metric} 잔액\n'
        f'기준: {range_label(period, "월말")}\n'
        '단위: 억원\n\n'
        f'{fmt_amount(amount)}'
    )


def format_balance_by_model(period: str, rows: list[dict], metrics: list[str]) -> str:
    lines = [
        '[조회결과] 회계모형별 잔액',
        f'기준: {range_label(period, "월말")}',
        '단위: 억원',
        '',
    ]
    for row in rows:
        label = '합계' if row['model'] == 'TOTAL' else row['model']
        parts = [f'{label:<4}']
        for metric in metrics:
            parts.append(f'{metric} {fmt_amount(row.get(metric))}')
        lines.append(' | '.join(parts))
    return '\n'.join(lines)


def format_pl_summary(period: str, data: dict) -> str:
    monthly = data.get('당월', {})
    ytd = data.get('누적', {})
    return (
        '[조회결과]\n'
        '지표: 보험손익(간접사업비 차감후)\n'
        f'당월 기준: {range_label(period, "당월")}\n'
        f'누적 기준: {range_label(period, "누적")}\n'
        '단위: 억원\n\n'
        f'당월: {fmt_amount(monthly.get("보험손익_차감후"))}\n'
        f'누적: {fmt_amount(ytd.get("보험손익_차감후"))}\n\n'
        '참고\n'
        f'- 당월 차감전: {fmt_amount(monthly.get("보험손익_차감전"))}\n'
        f'- 당월 간접사업비: {fmt_amount(monthly.get("간접사업비"))}\n'
        f'- 누적 차감전: {fmt_amount(ytd.get("보험손익_차감전"))}\n'
        f'- 누적 간접사업비: {fmt_amount(ytd.get("간접사업비"))}'
    )


def format_pl_by_model(period: str, scope: str, rows: list[dict]) -> str:
    lines = [
        '[조회결과] 회계모형별 보험손익',
        f'기준: {range_label(period, scope)}',
        '단위: 억원, 간접사업비 차감전',
        '',
    ]
    for row in rows:
        label = '합계' if row['model'] == 'TOTAL' else row['model']
        lines.append(f'{label.ljust(4)} {fmt_amount(row["amount"])}')
    return '\n'.join(lines)


def format_csm_movement(period: str, scope: str, model: str, rows: list[dict]) -> str:
    lines = [
        f'[조회결과] {model} CSM 무브먼트',
        f'기준: {range_label(period, scope)}',
        '단위: 억원',
        '',
    ]
    for row in rows:
        code = row['movement_code']
        amount = row['amount']
        if code in {'기시', '기말', '증감'}:
            continue
        if abs(amount) < 1e-12:
            continue
        sign = '+' if amount > 0 else ''
        lines.append(f'{code:<18} {sign}{fmt_amount(amount)}')
    summary_map = {r['movement_code']: r['amount'] for r in rows}
    lines.extend([
        '',
        f'증감합계            {fmt_amount(summary_map.get("증감"))}',
        f'기말 CSM         {fmt_amount(summary_map.get("기말"))}',
    ])
    return '\n'.join(lines)


def format_csm_movement_compare(period: str, scope: str, rows: list[dict]) -> str:
    lines = [
        f'[조회결과] 3모형 {scope} CSM 변동 비교',
        f'기준: {range_label(period, scope)}',
        '단위: 억원',
        '',
    ]
    for row in rows:
        label = '합계' if row['model'] == 'TOTAL' else row['model']
        delta = row['delta_amount']
        sign = '+' if delta and delta > 0 else ''
        lines.append(
            f'{label:<4}: {fmt_amount(row["start_amount"])} → {fmt_amount(row["end_amount"])} '
            f'(증감 {sign}{fmt_amount(delta)})'
        )
    return '\n'.join(lines)
