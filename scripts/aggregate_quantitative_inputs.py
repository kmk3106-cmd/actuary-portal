"""
월별 정량평가 원시값을 work_tasks에서 읽어 performance_records에 반영한다.
config/performance_rules.json의 룰을 참조한다.

사용법:
  python scripts/aggregate_quantitative_inputs.py --ym 202605 [--member 홍길동] [--dry-run]
"""
import argparse
import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

RULES_PATH = Path(__file__).parent.parent / 'config' / 'performance_rules.json'
API_BASE   = 'http://localhost:8888'


def load_rules():
    with open(RULES_PATH, encoding='utf-8') as f:
        return json.load(f)


def api_get(path):
    url = API_BASE + path
    with urllib.request.urlopen(url) as res:
        return json.loads(res.read().decode())


def api_put(path, body):
    data = json.dumps(body).encode('utf-8')
    req  = urllib.request.Request(API_BASE + path, data=data, method='PUT',
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode())


def api_post(path, body):
    data = json.dumps(body).encode('utf-8')
    req  = urllib.request.Request(API_BASE + path, data=data, method='POST',
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode())


# ── 점수 산출 함수 ─────────────────────────────────────────────────

def calc_directive(raw, rules):
    if raw is None:
        return None
    return 100 if raw == 1 else 0


def calc_csm(raw, rules):
    if raw is None:
        return None
    for rule in rules['csm']['rules']:
        if 'min' in rule and raw >= rule['min']:
            return rule['score']
    return 0


def calc_deadline(raw, rules):
    if raw is None:
        return None
    for rule in rules['deadline']['rules']:
        if 'min' in rule and raw >= rule['min']:
            return rule['score']
        if 'exact' in rule and raw == rule['exact']:
            return rule['score']
        if 'max' in rule and raw <= rule['max']:
            return rule['score']
    return 0


def calc_meeting(raw, rules):
    if raw is None:
        return None
    return 100 if raw >= 1 else 0


def calc_scores(work_rec, rules):
    q = rules['quantitative']
    s1 = calc_directive(work_rec.get('raw_directive'),    q)
    s2 = calc_csm(      work_rec.get('raw_csm_amount'),   q)
    s3 = calc_deadline( work_rec.get('raw_deadline_days'), q)
    s4 = calc_meeting(  work_rec.get('raw_meeting_count'), q)
    return s1, s2, s3, s4


def calc_basic_score(s1, s2, s3, s4, rules):
    q = rules['quantitative']
    parts = []
    if s1 is not None: parts.append(s1 * q['directive']['weight'])
    if s2 is not None: parts.append(s2 * q['csm']['weight'])
    if s3 is not None: parts.append(s3 * q['deadline']['weight'])
    if s4 is not None: parts.append(s4 * q['meeting']['weight'])
    return round(sum(parts) * 10) / 10 if parts else None


def assign_grade(score, rules):
    if score is None:
        return None
    for grade, cut in rules['grade_cutoffs'].items():
        lo = cut.get('min', float('-inf'))
        hi = cut.get('max', float('inf'))
        if lo <= score < hi:
            return grade
        if 'min' in cut and 'max' not in cut and score >= cut['min']:
            return grade
    return 'D'


# ── 의존성 체크 ────────────────────────────────────────────────────

def check_dependencies():
    missing = []
    if not RULES_PATH.exists():
        missing.append(f'config/performance_rules.json 없음')
    try:
        api_get('/tables/work_tasks?limit=1')
    except Exception:
        missing.append('work_tasks 테이블 접근 불가 (서버 미실행?)')
    try:
        api_get('/tables/performance_records?limit=1')
    except Exception:
        missing.append('performance_records 테이블 접근 불가')
    return missing


# ── 메인 ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='정량평가 원시값 집계 → performance_records 반영')
    parser.add_argument('--ym',      required=True, help='기준 연월 (YYYYMM)')
    parser.add_argument('--member',  default=None,  help='특정 팀원만 처리 (생략 시 전체)')
    parser.add_argument('--dry-run', action='store_true', help='DB 저장 없이 결과만 출력')
    args = parser.parse_args()

    year  = int(args.ym[:4])
    month = int(args.ym[4:])

    # 의존성 체크
    missing = check_dependencies()
    if missing:
        print('[의존성 오류] 다음 항목을 확인하세요:')
        for m in missing:
            print(f'  - {m}')
        return

    rules = load_rules()
    rule_version = rules.get('version', 'unknown')

    # work_tasks 로드
    wt_data  = api_get('/tables/work_tasks?limit=500')
    wt_rows  = wt_data.get('rows', wt_data.get('data', []))
    wt_month = [r for r in wt_rows
                if str(r.get('year')) == str(year) and str(r.get('month')) == str(month)]
    if args.member:
        wt_month = [r for r in wt_month if r.get('member_name') == args.member]

    if not wt_month:
        print(f'[{year}년 {month}월] work_tasks 데이터가 없습니다.')
        return

    # performance_records 로드 (매칭용)
    pr_data = api_get('/tables/performance_records?limit=500')
    pr_rows = pr_data.get('rows', pr_data.get('data', []))

    results = []
    for wt in wt_month:
        name = wt.get('member_name', '')
        if not name:
            continue

        # 정량 입력값 확인
        missing_fields = []
        for field in ['raw_directive', 'raw_csm_amount', 'raw_deadline_days', 'raw_meeting_count']:
            if wt.get(field) is None:
                missing_fields.append(field)

        if missing_fields:
            print(f'[누락] {name}: {", ".join(missing_fields)} 미입력 → 스킵')
            results.append({'name': name, 'status': 'skipped', 'reason': missing_fields})
            continue

        s1, s2, s3, s4 = calc_scores(wt, rules)
        basic = calc_basic_score(s1, s2, s3, s4, rules)

        print(f'[{name}] 지시={s1} CSM={s2} 기한={s3} 임원={s4} → 정량소계={basic}점')

        if args.dry_run:
            results.append({'name': name, 'status': 'dry-run', 'basic_score': basic})
            continue

        # performance_records 기존 레코드 확인
        match = next((r for r in pr_rows
                      if r.get('target_name') == name
                      and str(r.get('year')) == str(year)
                      and str(r.get('month')) == str(month)), None)

        body = {
            'year': year, 'month': month, 'target_name': name,
            'raw_directive':     wt.get('raw_directive'),
            'raw_csm_amount':    wt.get('raw_csm_amount'),
            'raw_deadline_days': wt.get('raw_deadline_days'),
            'raw_meeting_count': wt.get('raw_meeting_count'),
            'score_directive':   s1,
            'score_csm':         s2,
            'score_deadline':    s3,
            'score_meeting':     s4,
            'basic_score':       basic,
            'rule_version':      rule_version,
        }

        try:
            if match:
                api_put(f'/tables/performance_records/{match["id"]}', body)
                status = 'updated'
            else:
                api_post('/tables/performance_records', body)
                status = 'created'

            # audit_log 기록
            audit_body = {
                'action':       'aggregate_quantitative',
                'target_table': 'performance_records',
                'target_name':  name,
                'year':         year,
                'month':        month,
                'rule_version': rule_version,
                'raw_inputs': {
                    'directive':     wt.get('raw_directive'),
                    'csm_amount':    wt.get('raw_csm_amount'),
                    'deadline_days': wt.get('raw_deadline_days'),
                    'meeting_count': wt.get('raw_meeting_count'),
                },
                'scores': { 'directive': s1, 'csm': s2, 'deadline': s3, 'meeting': s4 },
                'basic_score': basic,
                'performed_at': datetime.now().isoformat(),
                'performed_by': 'aggregate_script',
            }
            try:
                api_post('/tables/audit_logs', audit_body)
            except Exception:
                pass  # audit 실패는 무시

            results.append({'name': name, 'status': status, 'basic_score': basic})
            print(f'  → {status}')
        except Exception as e:
            results.append({'name': name, 'status': 'error', 'error': str(e)})
            print(f'  → 오류: {e}')

    # 최종 요약
    print(f'\n[완료] {year}년 {month}월 | '
          f'처리={sum(1 for r in results if r["status"] in ("updated","created"))}명 / '
          f'스킵={sum(1 for r in results if r["status"]=="skipped")}명 / '
          f'오류={sum(1 for r in results if r["status"]=="error")}명')


if __name__ == '__main__':
    main()
