from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from settings import DEFAULT_PERIOD


@dataclass
class ParsedQuery:
    intent: str
    period: str
    scope: Optional[str] = None
    metric: Optional[str] = None
    model: Optional[str] = None
    by_model: bool = False
    raw: str = ''


class QueryParseError(ValueError):
    pass


BALANCE_METRICS = {'BEL', 'RA', 'CSM', 'LOSS', '잔여보장부채', '발생사고부채'}


def _normalize_text(text: str) -> str:
    text = text.strip()
    text = text.replace('벨', 'bel')
    text = text.replace('씨에스엠', 'csm')
    text = text.replace('로스', 'loss')
    text = text.replace('위험조정', 'ra')
    text = text.replace('논파', 'np')
    text = text.replace('당기누적', '누적')
    text = re.sub(r'\s+', ' ', text)
    return text.lower()


def _extract_period(text: str) -> str:
    candidates = [
        re.search(r'(20\d{2})[-./ ]?(0[1-9]|1[0-2])', text),
        re.search(r'(\d{2})년\s*(1[0-2]|0?[1-9])월', text),
    ]
    for m in candidates:
        if not m:
            continue
        if len(m.groups()) == 2:
            year = m.group(1)
            month = m.group(2).zfill(2)
            if len(year) == 2:
                year = '20' + year
            return f'{year}{month}'
    return DEFAULT_PERIOD


def _extract_scope(text: str, metric: str | None) -> Optional[str]:
    if '누적' in text or '누계' in text or 'ytd' in text:
        return '누적'
    if '당월' in text:
        return '당월'
    if '월말' in text or '기말' in text or (metric and metric in BALANCE_METRICS and '무브먼트' not in text and '변동' not in text):
        return '월말'
    if '무브먼트' in text or '변동' in text:
        return '당월'
    if metric == '보험손익':
        return None
    return '월말'


def _extract_model(text: str) -> Optional[str]:
    if re.search(r'\bnp\b', text):
        return 'NP'
    if re.search(r'\bidp\b', text):
        return 'IDP'
    if re.search(r'\bvfa\b', text):
        return 'VFA'
    return None


def _extract_metric(text: str) -> Optional[str]:
    # 잔여보장부채·발생사고부채는 먼저 체크 (더 구체적인 표현)
    if '잔여보장부채' in text or 'lrc' in text:
        return '잔여보장부채'
    if '발생사고부채' in text or '발생사고' in text or 'lic' in text:
        return '발생사고부채'
    if '보험손익' in text or ('손익' in text and '금융손익' not in text):
        return '보험손익'
    if 'loss' in text or '손실요소' in text:
        return 'LOSS'
    if 'csm' in text or '계약마진' in text:
        return 'CSM'
    if re.search(r'\bra\b', text):
        return 'RA'
    if 'bel' in text:
        return 'BEL'
    return None


def parse_query(raw_text: str) -> ParsedQuery:
    text = _normalize_text(raw_text)
    period = _extract_period(text)
    model = _extract_model(text)
    by_model = '회계모형별' in text or 'np idp vfa' in text or '3모형' in text
    bundle_bel_ra_csm = all(token in text for token in ['bel', 'ra', 'csm'])
    metric = _extract_metric(text)
    scope = _extract_scope(text, metric)

    if '무브먼트' in text or '변동' in text:
        if metric != 'CSM':
            raise QueryParseError(
                '[오류] 무브먼트 조회는 현재 CSM 중심으로 지원합니다.\n'
                '예시:\n- /조회 202603 np csm 무브먼트 당월\n- /조회 202603 vfa csm 무브먼트 누적'
            )
        if by_model:
            return ParsedQuery(
                intent='csm_movement_compare',
                period=period,
                scope='누적' if '누적' in text else '당월',
                metric='CSM',
                by_model=True,
                raw=raw_text,
            )
        if not model:
            raise QueryParseError(
                '[오류] 무브먼트 조회에는 회계모형이 필요합니다.\n'
                '예시:\n- /조회 202603 np csm 무브먼트 당월\n- /조회 202603 vfa csm 무브먼트 누적'
            )
        return ParsedQuery(
            intent='csm_movement_model',
            period=period,
            scope='누적' if '누적' in text else '당월',
            metric='CSM',
            model=model,
            raw=raw_text,
        )

    if by_model and bundle_bel_ra_csm:
        return ParsedQuery(
            intent='balance_bundle_by_model',
            period=period,
            scope='월말',
            metric='BEL_RA_CSM',
            by_model=True,
            raw=raw_text,
        )

    if metric in BALANCE_METRICS:
        if by_model or '회계모형별' in text:
            return ParsedQuery(
                intent='balance_by_model',
                period=period,
                scope='월말',
                metric=metric,
                by_model=True,
                raw=raw_text,
            )
        return ParsedQuery(
            intent='balance_single',
            period=period,
            scope='월말',
            metric=metric,
            raw=raw_text,
        )

    if metric == '보험손익':
        if by_model:
            return ParsedQuery(
                intent='pl_by_model',
                period=period,
                scope=scope,
                metric=metric,
                by_model=True,
                raw=raw_text,
            )
        return ParsedQuery(
            intent='pl_summary',
            period=period,
            scope=scope,
            metric=metric,
            raw=raw_text,
        )

    raise QueryParseError(
        '[오류] 조회 지표를 이해하지 못했습니다.\n'
        '지원 예: 보험손익, BEL, RA, CSM, LOSS, 잔여보장부채, 발생사고부채\n'
        '예시: /조회 202603 월말 잔여보장부채'
    )
