#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
국가법령정보센터 공개 API 로 규정 개정 이벤트를 보강한다 (인증키 = OC, 환경변수 LAW_API_KEY 또는 --oc).
  1) 법령(보험업법·시행령·시행규칙) 확정 공포본: target=eflaw 연혁에서 공포일·시행일을 받아 '공포' 이벤트를 만든다 (타법개정 제외)
  2) 행정규칙(보험업감독규정·보험업감독업무시행세칙): 현행 본문의 부칙 목록에서 발령일별 시행일을 읽어
     이미 수집된 확정 건(fsc_gosi·fss_info)에 시행일·부칙을 붙이고, 수집에 없는 발령은 '공포/시행' 이벤트로 만든다
  멱등: 같은 id 는 덮어쓰고, 사람이 넣은 값은 건드리지 않는다. 결과는 --data 파일에 다시 쓴다.

  python scripts/enrich_reg_history_law.py --data server/data/reg_history/reg_history.json --since 2023-01-01 [--oc <인증키>]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

LAW_API_BASE = os.environ.get('LAW_API_BASE', 'https://www.law.go.kr').rstrip('/')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36 ActuaryPortal-RegCollector'
DEFAULT_DELAY = 2.0
RETRIES = 4
TIMEOUT = 40
MATCH_WINDOW_DAYS = 12            # 부칙 공포일 ↔ 수집된 확정 건 게시일 허용 차이 (게시가 며칠 늦는다)
LAWS = {'보험업법': '법률', '보험업법 시행령': '시행령', '보험업법 시행규칙': '시행규칙'}
RULES = {'보험업감독규정': ('감독규정', '공포', '금융위원회'), '보험업감독업무시행세칙': ('시행세칙', '시행', '금융감독원')}
SKIP_KINDS = ('타법개정', '타법폐지')     # 다른 법령 개정에 끌려 바뀐 조문 정비는 팀 업무와 무관해 만들지 않는다
EFF_RE = re.compile(r'(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*부터\s*시행')
EFF_DAY_RE = re.compile(r'(?:고시|공포|발령|시행)한\s*날부터\s*시행')
SOURCE_LABEL = '국가법령정보센터'


def ymd(s):
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}' if s and len(s) == 8 else ''


def get_json(url, delay):
    last = None
    for i in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read().decode('utf-8', 'replace')
            time.sleep(delay)
            return json.loads(body)
        except Exception as e:  # noqa
            last = e
            time.sleep(delay * (i + 1))
    raise RuntimeError(f'{url[:90]}… 실패: {last}')


def as_list(v):
    return v if isinstance(v, list) else ([v] if v else [])


def law_events(oc, since, delay, existing_ids):
    """eflaw 연혁 → 공포 이벤트 (법령명 정확히 일치, 공포일 ≥ since, 타법개정 제외). 같은 공포본(MST)이 시행일별로 여러 줄이면 첫 시행일을 쓴다"""
    out = []
    for name, rtype in LAWS.items():
        url = f'{LAW_API_BASE}/DRF/lawSearch.do?OC={oc}&target=eflaw&type=JSON&query={urllib.parse.quote(name)}&display=100'
        rows = [r for r in as_list(get_json(url, delay).get('LawSearch', {}).get('law')) if r.get('법령명한글') == name]
        by_mst = {}
        for r in rows:
            if ymd(r.get('공포일자')) < since or r.get('제개정구분명') in SKIP_KINDS:
                continue
            m = by_mst.setdefault(r['법령일련번호'], {'row': r, 'effs': set()})
            m['effs'].add(ymd(r.get('시행일자')))
        for mst, m in by_mst.items():
            r = m['row']; effs = sorted(x for x in m['effs'] if x)
            ev_id = f'lawapi_law_{mst}'
            detail_url = f"{LAW_API_BASE}/법령/{urllib.parse.quote(name)}/({r.get('공포번호', '')},{r.get('공포일자', '')})"   # 공개 링크 (인증키 없이 열림)
            purpose, supplement = '', ''
            if ev_id not in existing_ids:
                try:
                    d = get_json(f'{LAW_API_BASE}/DRF/lawService.do?OC={oc}&target=law&MST={mst}&type=JSON', delay)
                    root = d[list(d.keys())[0]]
                    reason = root.get('제개정이유') or {}
                    purpose = ' '.join(' '.join(x) if isinstance(x, list) else str(x) for x in as_list(reason.get('제개정이유내용')))[:1500]
                    for u in as_list((root.get('부칙') or {}).get('부칙단위')):
                        if ymd(str(u.get('부칙공포일자', ''))) == ymd(r.get('공포일자')):
                            supplement = ' '.join(' '.join(x) if isinstance(x, list) else str(x) for x in as_list(u.get('부칙내용')))[:800]
                except Exception as e:  # noqa
                    print(f'  ! {ev_id} 상세 실패: {e}', file=sys.stderr)
            out.append({
                'id': ev_id, 'source': 'law_api', 'source_label': f'{SOURCE_LABEL} 법령 연혁', 'url': detail_url,
                'list_title': f"{name} {r.get('제개정구분명', '')} (공포 제{r.get('공포번호', '')}호)",
                'reg_name': name, 'reg_type': rtype, 'status': '공포', 'authority': r.get('소관부처명') or '금융위원회',
                'date': ymd(r.get('공포일자')), 'date_promulgated': ymd(r.get('공포일자')),
                'date_effective': effs[0] if effs else '', 'date_effective_source': f'{SOURCE_LABEL} 시행일자',
                'date_effective_notes': (f"일부 조항은 {', '.join(effs[1:])} 시행" if len(effs) > 1 else ''),
                'gazette_no': r.get('공포번호', ''), 'notice_kind': r.get('제개정구분명', ''),
                'purpose': purpose, 'content': purpose, 'supplement': supplement, 'attachments': [],   # 제개정이유의 '주요내용' 글머리가 제목 재료
            })
    return out


def parse_supplement_effective(text, promulgated):
    """부칙 본문에서 시행일: 'YYYY년 M월 D일부터 시행' → 그 날, '고시(공포)한 날부터 시행' → 공포일"""
    # 본칙('이 규정은 고시한 날부터 시행한다. 다만, 제9-4조의3은 2026년 1월 1일부터 시행') 에서 '다만' 앞까지만 시행일로 본다 — 예외 조문 날짜를 시행일로 잘못 읽지 않도록
    main = re.split(r'다만|단,', text or '', 1)[0]
    m = EFF_RE.search(main)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    if EFF_DAY_RE.search(main):
        return promulgated
    return ''


def rule_supplements(oc, delay):
    """행정규칙 현행 본문의 부칙 목록 → {규정명: [(공포일, 번호, 내용)]} + 현행 기본정보·첨부"""
    out = {}
    for name in RULES:
        url = f'{LAW_API_BASE}/DRF/lawSearch.do?OC={oc}&target=admrul&type=JSON&query={urllib.parse.quote(name)}&display=50'
        rows = [r for r in as_list(get_json(url, delay).get('AdmRulSearch', {}).get('admrul')) if r.get('행정규칙명') == name]
        if not rows:
            print(f'  - {name}: 목록 없음', file=sys.stderr); continue
        cur = rows[0]
        d = get_json(f'{LAW_API_BASE}/DRF/lawService.do?OC={oc}&target=admrul&ID={cur["행정규칙일련번호"]}&type=JSON', delay)
        root = d[list(d.keys())[0]]
        if not isinstance(root, dict):
            print(f'  - {name}: 상세 형식 이상', file=sys.stderr); continue
        bu = root.get('부칙') or {}
        dates, texts, nos = as_list(bu.get('부칙공포일자')), as_list(bu.get('부칙내용')), as_list(bu.get('부칙공포번호'))
        items = [(ymd(str(dd)), str(nn), str(tt)) for dd, tt, nn in zip(dates, texts, nos)]
        info = root.get('행정규칙기본정보') or {}
        att = root.get('첨부파일') or {}
        out[name] = {'items': items, 'current': info, 'serial': cur['행정규칙일련번호'],
                     'attachments': [{'name': n, 'url': u} for n, u in zip(as_list(att.get('첨부파일명')), as_list(att.get('첨부파일링크')))]}
    return out


def enrich_rules(events, sup, since):
    """부칙 → 기존 확정 건 보강 / 없으면 신규 이벤트"""
    def day(d):
        return dt.date.fromisoformat(d).toordinal() if d else 0
    added = enriched = 0
    for name, (rtype, status, authority) in RULES.items():
        info = sup.get(name)
        if not info:
            continue
        decided = [e for e in events if e['status'] in ('공포', '시행') and e.get('date') and name in (e.get('reg_name') or '') and e.get('source') != 'law_api']
        for pdate, no, text in info['items']:
            if not pdate or pdate < since:
                continue
            eff = parse_supplement_effective(text, pdate)
            exc = re.search(r'(?:다만|단,)\s*([^.]{0,120}?시행한다)', text or '')
            exc_note = ('다만 ' + exc.group(1).strip(' ,，')) if exc else ''
            is_current = ymd(str(info['current'].get('발령일자', ''))) == pdate
            if not eff and is_current and info['current'].get('시행일자'):      # 현행 본문이면 기본정보의 시행일자가 있다
                eff = ymd(str(info['current']['시행일자']))
            cands = [e for e in decided if abs(day(e['date']) - day(pdate)) <= MATCH_WINDOW_DAYS]
            if cands:
                e = min(cands, key=lambda e: abs(day(e['date']) - day(pdate)))
                if eff:
                    e['date_effective'] = eff
                    e['date_effective_source'] = f'{SOURCE_LABEL} 부칙'
                    if exc_note:
                        e['date_effective_notes'] = exc_note
                e['supplement'] = text[:800]
                e['law_api_promulgated'] = pdate
                if no and no != '9999' and not e.get('gazette_no'):
                    e['gazette_no'] = no
                enriched += 1
            else:
                ev_id = f'lawapi_admrul_{rtype}_{pdate.replace("-", "")}'
                prev = next((x for x in events if x['id'] == ev_id), None)
                if prev:
                    if eff and not prev.get('date_effective'):
                        prev['date_effective'] = eff; prev['date_effective_source'] = f'{SOURCE_LABEL} 부칙'
                    continue
                events.append({
                    'id': ev_id, 'source': 'law_api', 'source_label': f'{SOURCE_LABEL} 행정규칙 부칙',
                    'url': f"{LAW_API_BASE}/행정규칙/{urllib.parse.quote(name)}/({no or '9999'},{pdate.replace('-', '')})",   # 공개 링크 — 발령번호·발령일자까지 붙여 건마다 고유(적재 source_key)
                    'list_title': f"{name} 개정 (발령 {pdate.replace('-', '.')})", 'reg_name': name, 'reg_type': rtype, 'status': status,
                    'authority': authority, 'date': pdate, 'date_promulgated': pdate, 'date_effective': eff,
                    'date_effective_source': f'{SOURCE_LABEL} 부칙' if eff else '', 'date_effective_notes': exc_note if eff else '', 'gazette_no': '' if no == '9999' else no,
                    'purpose': '', 'content': '', 'supplement': text[:800],
                    'attachments': info['attachments'] if is_current else [],
                })
                added += 1
    return added, enriched


def main():
    ap = argparse.ArgumentParser(description='국가법령정보 API 로 규정 개정 이벤트 보강')
    ap.add_argument('--data', required=True, help='collect_reg_history.py 산출 JSON (제자리 갱신)')
    ap.add_argument('--since', required=True, help='YYYY-MM-DD')
    ap.add_argument('--oc', default=os.environ.get('LAW_API_KEY', ''), help='법령정보센터 인증키(OC). 기본 환경변수 LAW_API_KEY')
    ap.add_argument('--delay', type=float, default=DEFAULT_DELAY)
    ap.add_argument('--no-laws', action='store_true', help='법령(eflaw) 이벤트 생성 생략')
    a = ap.parse_args()
    if not a.oc:
        print('LAW_API_KEY 없음 — 보강 생략', file=sys.stderr); return
    events = json.load(open(a.data, encoding='utf-8'))
    ids = {e['id'] for e in events}
    by_id = {e['id']: e for e in events}
    added_law = 0
    if not a.no_laws:
        for ev in law_events(a.oc, a.since, a.delay, ids):
            if ev['id'] in by_id:
                old = by_id[ev['id']]
                for k in ('date_effective', 'date_effective_source', 'date_effective_notes', 'gazette_no', 'notice_kind'):
                    old[k] = ev[k]
                if not old.get('purpose') and ev.get('purpose'):
                    old['purpose'] = ev['purpose']
                if not old.get('supplement') and ev.get('supplement'):
                    old['supplement'] = ev['supplement']
            else:
                events.append(ev); by_id[ev['id']] = ev; added_law += 1
    sup = rule_supplements(a.oc, a.delay)
    added_rule, enriched = enrich_rules(events, sup, a.since)
    events.sort(key=lambda e: e.get('date', ''), reverse=True)
    json.dump(events, open(a.data, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'완료: 법령 이벤트 추가 {added_law} · 행정규칙 이벤트 추가 {added_rule} · 확정 건 시행일·부칙 보강 {enriched} → {a.data}', file=sys.stderr)


if __name__ == '__main__':
    main()
