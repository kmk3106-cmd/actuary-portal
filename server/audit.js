/**
 * 포탈 자동 무결성 점검 (Audit)
 *
 * server.js 가 매일 새벽 4시에 runAudit(db) 를 호출하면
 * 전체 데이터 일관성을 일괄 검사하고 결과를 db.audit_reports 에 누적 기록.
 *
 * 검사 카테고리:
 *  - perf_orphan: work_tasks/performance_records 잔존 (DATA_SYNC_RULES §3 버그 F 패턴)
 *  - perf_inactive: 비활성/삭제된 사용자의 성과 record
 *  - dwe_orphan: 비활성 사용자의 daily_work_entries
 *  - work_task_zombie: settlement_done 비어있는데 deadline_days 잔존 (DATA_SYNC_RULES §3 버그 A)
 *  - vacation_inactive: 비활성 사용자의 휴가 record
 *  - vacation_quota_mismatch: vacation_quotas.used 와 실제 vacations 합계 불일치
 *  - vacation_quota_excess: used > annual_total (음수 잔액)
 *  - vacation_overlap_self: 동일 직원·동일 일자에 휴가가 시간대로 겹침
 *  - vacation_work_conflict: 전일 휴가 일자에 daily_work_entries 잔존 (휴가인데 업무 입력)
 *
 * 결과 구조:
 *   { id, run_at, duration_ms, status, summary, issues: [...] }
 */

const fs = require('fs');
const path = require('path');

// 점검할 카테고리 정의 — 새 카테고리 추가는 여기에
const CATEGORIES = {
  perf_orphan_quant: { label: '정량 점수 잔존', severity: 'high' },
  perf_orphan_deadline: { label: '마감일 점수 잔존', severity: 'high' },
  perf_inactive: { label: '비활성 사용자 성과 record', severity: 'medium' },
  dwe_inactive: { label: '비활성 사용자 daily_work_entries', severity: 'medium' },
  work_task_zombie: { label: 'work_tasks deadline_days 잔존', severity: 'medium' },
  vacation_inactive: { label: '비활성 사용자 휴가 record', severity: 'medium' },
  vacation_quota_mismatch: { label: '휴가 한도 사용량 불일치', severity: 'high' },
  vacation_quota_excess: { label: '휴가 한도 초과 (음수 잔액)', severity: 'high' },
  vacation_overlap_self: { label: '동일 일자 휴가 중복', severity: 'medium' },
  vacation_work_conflict: { label: '전일 휴가 일자 업무 입력 잔존', severity: 'medium' },
  vacation_no_status: { label: '휴가 record status 누락', severity: 'medium' },
  vacation_invalid_minutes: { label: '휴가 minutes 와 time_entries 불일치', severity: 'medium' },
  points_orphan: { label: '적립 포인트 — 대상 record 사라짐', severity: 'medium' },
  kb_version_orphan: { label: 'kb_document_versions — 부모 문서 사라짐', severity: 'medium' },
  // ── Phase 9: 신규 검사 카테고리 ──
  points_rule_stale: { label: '비활성 룰 적립 잔존 (룰 비활성 이후 포인트 남아있음)', severity: 'high' },
  points_quarter_boundary: { label: '분기 경계 집중 적립 (마지막·첫날 의심 패턴)', severity: 'medium' },
  points_duplicate_user: { label: '동일 액션 다중 사용자 적립 (가짜 적립 의심)', severity: 'high' },
  points_inactive_user_ledger: { label: '비활성 사용자 포인트 잔존 (재활성화 합산 위험)', severity: 'medium' },
  points_member_rename: { label: '멤버명 변경으로 리더보드 단절 의심', severity: 'medium' },
  points_self_sop_ref: { label: '자기 SOP 자가 참조 (공유 보너스 자가 적립 방지)', severity: 'medium' },
};

function createId() {
  return 'aud_' + Math.random().toString(16).slice(2, 14) + Date.now().toString(36);
}

function asObject(v) {
  if (v == null) return null;
  if (typeof v === 'object') return v;
  if (typeof v === 'string') {
    try { return JSON.parse(v); } catch { return null; }
  }
  return null;
}

function asArray(v) {
  if (Array.isArray(v)) return v;
  if (typeof v === 'string') {
    try { const p = JSON.parse(v); return Array.isArray(p) ? p : []; } catch { return []; }
  }
  return [];
}

/**
 * 검사 1: work_tasks 와 performance_records 의 정량 raw/score 일관성
 * 잔존 패턴 — work_task.raw_directive=null 인데 pr.raw_directive 또는 score_directive 잔존
 */
function checkPerfOrphanQuant(db) {
  const issues = [];
  const wtByKey = {};
  for (const t of db.work_tasks || []) {
    const k = `${t.member_name || t.target_name}|${t.year}|${t.month}`;
    wtByKey[k] = t;
  }
  const quantPairs = [
    ['raw_directive', 'score_directive'],
    ['raw_csm_amount', 'score_csm'],
    ['raw_meeting_count', 'score_meeting'],
  ];
  for (const r of db.performance_records || []) {
    const k = `${r.target_name}|${r.year}|${r.month}`;
    const wt = wtByKey[k];
    for (const [rawF, scoreF] of quantPairs) {
      const prRaw = r[rawF];
      const prScore = r[scoreF];
      const wtRaw = wt ? wt[rawF] : null;
      const prHas = prRaw != null && prRaw !== '' && prRaw !== 0
                 || prScore != null && prScore !== '' && prScore !== 0;
      const wtHas = wtRaw != null && wtRaw !== '' && wtRaw !== 0;
      if (prHas && !wtHas) {
        issues.push({
          category: 'perf_orphan_quant',
          severity: 'high',
          message: `${r.target_name} ${r.year}-${r.month} ${rawF} 잔존 (work_task에 raw 없음)`,
          details: { pr_id: r.id, pr_raw: prRaw, pr_score: prScore, wt_exists: !!wt },
          fix_hint: `performance_records[${r.id}].${rawF} 와 ${scoreF} 를 null로 PATCH`,
        });
      }
    }
  }
  return issues;
}

/**
 * 검사 2: work_task.settlement_done 비어있는데 pr.score_deadline 잔존
 */
function checkPerfOrphanDeadline(db) {
  const issues = [];
  const wtByKey = {};
  for (const t of db.work_tasks || []) {
    const k = `${t.member_name || t.target_name}|${t.year}|${t.month}`;
    wtByKey[k] = t;
  }
  for (const r of db.performance_records || []) {
    if (r.score_deadline == null || r.score_deadline === 0 || r.score_deadline === '') continue;
    const k = `${r.target_name}|${r.year}|${r.month}`;
    const wt = wtByKey[k];
    const done = wt ? asArray(wt.settlement_done) : [];
    if (done.length === 0) {
      issues.push({
        category: 'perf_orphan_deadline',
        severity: 'high',
        message: `${r.target_name} ${r.year}-${r.month} score_deadline=${r.score_deadline} 잔존 (settlement_done 비어있음)`,
        details: { pr_id: r.id, score_deadline: r.score_deadline, wt_exists: !!wt },
        fix_hint: `performance_records[${r.id}].score_deadline 을 null로 PATCH`,
      });
    }
  }
  return issues;
}

/**
 * 검사 3: 비활성/삭제된 사용자의 성과 record
 */
function checkPerfInactive(db) {
  const issues = [];
  const activeNames = new Set(
    (db.users || []).filter(u => u.is_active !== false).map(u => u.full_name)
  );
  const allNames = new Set((db.users || []).map(u => u.full_name));
  for (const r of db.performance_records || []) {
    if (!r.target_name) continue;
    if (!activeNames.has(r.target_name)) {
      issues.push({
        category: 'perf_inactive',
        severity: 'medium',
        message: `${r.target_name} ${r.year}-${r.month ?? 'Q' + (r.quarter ?? '?')} — 비활성/삭제된 사용자의 성과 record`,
        details: { pr_id: r.id, in_users_table: allNames.has(r.target_name) },
        fix_hint: `사용자 상태 확인 후 record 삭제 또는 사용자 복원`,
      });
    }
  }
  return issues;
}

/**
 * 검사 4: 비활성 사용자의 daily_work_entries
 */
function checkDweInactive(db) {
  const issues = [];
  const activeNames = new Set(
    (db.users || []).filter(u => u.is_active !== false).map(u => u.full_name)
  );
  for (const e of db.daily_work_entries || []) {
    if (!e.member_name) continue;
    if (!activeNames.has(e.member_name)) {
      issues.push({
        category: 'dwe_inactive',
        severity: 'medium',
        message: `${e.member_name} ${e.end_date || e.work_date} (${e.source}) — 비활성 사용자의 daily 행`,
        details: { dwe_id: e.id, source: e.source },
        fix_hint: `해당 daily_work_entries 삭제 검토`,
      });
    }
  }
  return issues;
}

/**
 * 검사 5: work_task 의 settlement_done 에 없는데 deadline_days/dates/times 잔존
 * (DATA_SYNC_RULES §3 버그 A 패턴)
 */
function checkWorkTaskZombie(db) {
  const issues = [];
  for (const t of db.work_tasks || []) {
    const done = new Set(asArray(t.settlement_done));
    const fields = ['settlement_dates', 'settlement_times', 'settlement_deadline_days',
                    'settlement_start_dates', 'settlement_start_times', 'settlement_end_times'];
    for (const f of fields) {
      const obj = asObject(t[f]) || {};
      const orphans = Object.keys(obj).filter(k => !done.has(k));
      if (orphans.length > 0) {
        issues.push({
          category: 'work_task_zombie',
          severity: 'medium',
          message: `${t.member_name || t.target_name} ${t.year}-${t.month} ${f} 잔존: [${orphans.join(', ')}]`,
          details: { wt_id: t.id, field: f, orphan_keys: orphans },
          fix_hint: `${f}에서 settlement_done에 없는 키 제거 (sanitize)`,
        });
      }
    }
  }
  return issues;
}

/**
 * 검사 6: 비활성 사용자의 휴가 record
 */
function checkVacationInactive(db) {
  const issues = [];
  const activeNames = new Set(
    (db.users || []).filter(u => u.is_active !== false).map(u => u.full_name)
  );
  for (const v of db.vacations || []) {
    if (!v.member_name) continue;
    if (v.status === 'cancelled') continue;
    if (!activeNames.has(v.member_name)) {
      issues.push({
        category: 'vacation_inactive',
        severity: 'medium',
        message: `${v.member_name} ${v.start_date}~${v.end_date} (${v.vacation_type}) — 비활성 사용자의 휴가 record`,
        details: { vac_id: v.id, type: v.vacation_type, status: v.status },
        fix_hint: `해당 vacation 삭제 검토 또는 사용자 복원`,
      });
    }
  }
  return issues;
}

/**
 * 검사 7: vacation_quotas.used 가 실제 vacations 합계와 일치하는가
 * (status='approved' 만 합산. cancelled 는 제외.)
 */
function checkVacationQuotaMismatch(db) {
  const issues = [];
  const quotas = db.vacation_quotas || [];
  const vacs = db.vacations || [];
  for (const q of quotas) {
    // year + member 동일한 approved 휴가 days 합계
    const actualUsed = vacs
      .filter(v => v.status !== 'cancelled')
      .filter(v => v.member_name === q.member_name)
      .filter(v => v.start_date && v.start_date.slice(0, 4) === String(q.year))
      .reduce((s, v) => s + (Number(v.days) || 0), 0);
    const recorded = Number(q.used) || 0;
    if (Math.abs(actualUsed - recorded) > 0.001) {
      issues.push({
        category: 'vacation_quota_mismatch',
        severity: 'high',
        message: `${q.member_name} ${q.year}년 quota.used=${recorded} ≠ 실제 합계 ${actualUsed.toFixed(2)}일`,
        details: { quota_id: q.id, recorded_used: recorded, actual_used: actualUsed },
        fix_hint: `recomputeQuotaForYear(${q.year}, ${q.member_name}) 호출로 재계산`,
      });
    }
  }
  return issues;
}

/**
 * 검사 8: vacation_quotas.used > annual_total (음수 잔액)
 */
function checkVacationQuotaExcess(db) {
  const issues = [];
  for (const q of db.vacation_quotas || []) {
    const used = Number(q.used) || 0;
    const total = Number(q.annual_total) || 0;
    if (used > total + 0.001) {
      issues.push({
        category: 'vacation_quota_excess',
        severity: 'high',
        message: `${q.member_name} ${q.year}년 ${used}/${total}일 사용 — 한도 초과 (잔여 ${(total - used).toFixed(2)})`,
        details: { quota_id: q.id, used, annual_total: total },
        fix_hint: `한도 상향 조정 또는 일부 휴가 취소/조정`,
      });
    }
  }
  return issues;
}

/**
 * 검사 9: 동일 직원·동일 일자에 휴가가 시간대로 겹침
 * (status='approved' 만 검사. time_entries 기준)
 */
function checkVacationOverlapSelf(db) {
  const issues = [];
  const vacs = (db.vacations || []).filter(v => v.status !== 'cancelled');

  // member_name + date → [{vac_id, start, end}]
  const byKey = {};
  for (const v of vacs) {
    const entries = asArray(v.time_entries);
    if (entries.length > 0) {
      for (const e of entries) {
        if (!e.date || !e.start || !e.end) continue;
        const k = `${v.member_name}|${e.date}`;
        if (!byKey[k]) byKey[k] = [];
        byKey[k].push({ vac_id: v.id, start: e.start, end: e.end });
      }
    } else if (v.start_date && v.end_date) {
      // 시간대 없으면 전일 휴가로 간주
      const s = new Date(v.start_date + 'T00:00:00');
      const e = new Date(v.end_date + 'T00:00:00');
      while (s <= e) {
        const ds = s.toISOString().slice(0, 10);
        const k = `${v.member_name}|${ds}`;
        if (!byKey[k]) byKey[k] = [];
        byKey[k].push({ vac_id: v.id, start: v.start_time || '00:00', end: v.end_time || '23:59' });
        s.setDate(s.getDate() + 1);
      }
    }
  }

  const seenPairs = new Set();
  for (const [k, arr] of Object.entries(byKey)) {
    if (arr.length < 2) continue;
    const [member, date] = k.split('|');
    const toMin = t => { const [h, m] = t.split(':').map(Number); return h * 60 + m; };
    for (let i = 0; i < arr.length; i++) {
      for (let j = i + 1; j < arr.length; j++) {
        if (arr[i].vac_id === arr[j].vac_id) continue;
        const iS = toMin(arr[i].start), iE = toMin(arr[i].end);
        const jS = toMin(arr[j].start), jE = toMin(arr[j].end);
        if (iS < jE && jS < iE) {
          const pairKey = [arr[i].vac_id, arr[j].vac_id].sort().join('::') + '|' + date;
          if (seenPairs.has(pairKey)) continue;
          seenPairs.add(pairKey);
          issues.push({
            category: 'vacation_overlap_self',
            severity: 'medium',
            message: `${member} ${date} 휴가 시간대 중복: ${arr[i].start}~${arr[i].end} ⇄ ${arr[j].start}~${arr[j].end}`,
            details: { member, date, vac_ids: [arr[i].vac_id, arr[j].vac_id] },
            fix_hint: `중복된 휴가 중 하나를 취소 또는 시간 수정`,
          });
        }
      }
    }
  }
  return issues;
}

/**
 * 검사 10: 전일 휴가 일자(09:00~18:00 또는 시간대 없음)에 daily_work_entries 잔존
 */
function checkVacationWorkConflict(db) {
  const issues = [];
  const vacs = (db.vacations || []).filter(v => v.status !== 'cancelled');
  // member + date → fullDayVacation 여부
  const fullDay = {};
  for (const v of vacs) {
    const entries = asArray(v.time_entries);
    if (entries.length > 0) {
      for (const e of entries) {
        if (!e.date) continue;
        const minutes = Number(e.minutes) || 0;
        // 480분(8시간) 이상이면 전일 휴가로 간주
        if (minutes >= 420) {
          fullDay[`${v.member_name}|${e.date}`] = v.id;
        }
      }
    } else if (v.start_date && v.end_date) {
      const s = new Date(v.start_date + 'T00:00:00');
      const e = new Date(v.end_date + 'T00:00:00');
      while (s <= e) {
        const ds = s.toISOString().slice(0, 10);
        fullDay[`${v.member_name}|${ds}`] = v.id;
        s.setDate(s.getDate() + 1);
      }
    }
  }
  for (const dwe of db.daily_work_entries || []) {
    if (!dwe.member_name) continue;
    const entries = asArray(dwe.time_entries);
    if (entries.length === 0) continue;
    for (const e of entries) {
      if (!e.date) continue;
      const k = `${dwe.member_name}|${e.date}`;
      if (fullDay[k]) {
        issues.push({
          category: 'vacation_work_conflict',
          severity: 'medium',
          message: `${dwe.member_name} ${e.date} 전일 휴가인데 업무 입력 잔존 (${dwe.task_label || dwe.source})`,
          details: { dwe_id: dwe.id, vac_id: fullDay[k], date: e.date, source: dwe.source },
          fix_hint: `해당 daily_work_entries 삭제 또는 휴가 시간대 축소`,
        });
        break; // 한 dwe당 1건만 리포트
      }
    }
  }
  return issues;
}

/**
 * 검사 11: 휴가 status 누락 — /tables/vacations 직접 POST 우회 검출
 */
function checkVacationNoStatus(db) {
  const issues = [];
  for (const v of db.vacations || []) {
    if (!v.status) {
      issues.push({
        category: 'vacation_no_status',
        severity: 'medium',
        message: `${v.member_name || '?'} ${v.start_date || '?'} (${v.vacation_type || '?'}) — status 누락`,
        details: { vac_id: v.id },
        fix_hint: `status='approved' 또는 'cancelled' 로 PATCH`,
      });
    }
  }
  return issues;
}

/**
 * 검사 12: 휴가 minutes / time_entries 합 불일치 (클라가 수동으로 채운 잔존값 검출)
 */
function checkVacationInvalidMinutes(db) {
  const issues = [];
  for (const v of db.vacations || []) {
    if (v.status === 'cancelled') continue;
    const entries = asArray(v.time_entries);
    if (entries.length === 0) continue;
    const sum = entries.reduce((s, e) => s + (Number(e.minutes) || 0), 0);
    if (Math.abs(sum - (Number(v.minutes) || 0)) > 0.5) {
      issues.push({
        category: 'vacation_invalid_minutes',
        severity: 'medium',
        message: `${v.member_name} ${v.start_date} — vacations.minutes=${v.minutes} ≠ time_entries 합 ${sum}`,
        details: { vac_id: v.id, recorded: v.minutes, computed: sum },
        fix_hint: `/api/vacations/update 로 재계산 또는 직접 minutes 보정`,
      });
    }
  }
  return issues;
}

/**
 * 검사 13: engagement_points 의 action_ref 대상 record 가 사라짐
 *   (DELETE cascade 누락 검출 — 정상 흐름이면 0 이어야 함)
 */
function checkPointsOrphan(db) {
  const issues = [];
  const tableByAction = {
    work_entry: 'daily_work_entries',
    issue_register: 'kb_issues',
    sop_create: 'kb_documents',
    kpi_entry: 'work_tasks',
    settlement_check: 'work_tasks',
  };
  // O(1) lookup 용
  const idSet = {};
  for (const [, tbl] of Object.entries(tableByAction)) {
    idSet[tbl] = new Set((db[tbl] || []).map(r => r.id));
  }
  for (const p of db.engagement_points || []) {
    const tbl = tableByAction[p.action_type];
    if (!tbl) continue;                      // KPI/settlement 등은 ref 매칭 대상 아님
    if (!p.action_ref) continue;
    if (!idSet[tbl].has(p.action_ref)) {
      issues.push({
        category: 'points_orphan',
        severity: 'medium',
        message: `${p.member_name || p.user_id} ${p.action_type} ${p.points}pt — 대상 ${tbl}[${p.action_ref}] 사라짐`,
        details: { ep_id: p.id, action_type: p.action_type, action_ref: p.action_ref, points: p.points },
        fix_hint: `engagement_points[${p.id}] 삭제 또는 대상 복원`,
      });
    }
  }
  return issues;
}

// ──────────────────────────────────────────────────────────────────────
// Phase 9: 신규 검사 함수 (포인트 무결성 강화)
// ──────────────────────────────────────────────────────────────────────

/**
 * 검사 15: 비활성화된 point_rule 이후에 해당 action_type 포인트 적립 잔존.
 * 룰 비활성화(updated_at 이후) 에 생성된 행을 검출.
 */
function checkPointsRuleStale(db) {
  const issues = [];
  const rules = db.point_rules || [];
  // 비활성 룰의 비활성화 시점(updated_at) 수집
  const inactiveRuleTimes = {};
  for (const r of rules) {
    if (r.is_active === false) {
      inactiveRuleTimes[r.action_type] = Number(r.updated_at) || 0;
    }
  }
  if (Object.keys(inactiveRuleTimes).length === 0) return issues;

  for (const p of db.engagement_points || []) {
    const deactivatedAt = inactiveRuleTimes[p.action_type];
    if (deactivatedAt === undefined) continue; // 활성 룰 → 무시
    const awardedAt = Number(p.awarded_at) || Number(p.created_at) || 0;
    if (awardedAt > deactivatedAt) {
      issues.push({
        category: 'points_rule_stale',
        severity: 'high',
        message: `${p.member_name || p.user_id} ${p.action_type} ${p.points}pt — 룰 비활성(${new Date(deactivatedAt).toISOString().slice(0,10)}) 이후 적립됨`,
        details: { ep_id: p.id, action_type: p.action_type, awarded_at: awardedAt, rule_deactivated_at: deactivatedAt },
        fix_hint: `engagement_points[${p.id}] 삭제 또는 룰 재활성화`,
      });
    }
  }
  return issues;
}

/**
 * 검사 16: 분기 경계 집중 적립 — 분기 마지막·첫날(±3일)에 한 사용자가 5건 이상 적립.
 * 실제 조작은 아닐 수 있으나 패턴 검출 목적.
 */
function checkPointsQuarterBoundary(db) {
  const issues = [];
  // 분기 경계일 목록 생성 (포인트 레코드가 존재하는 분기 기준)
  const quarters = new Set((db.engagement_points || []).map(p => p.quarter).filter(Boolean));
  const boundaryDates = new Set();
  for (const q of quarters) {
    const m = /^(\d{4})-Q([1-4])$/.exec(String(q));
    if (!m) continue;
    const y = parseInt(m[1], 10);
    const qn = parseInt(m[2], 10);
    const sm = (qn - 1) * 3; // 0-indexed start month
    const em = sm + 2;
    const startDate = new Date(y, sm, 1);
    const endDate = new Date(y, em + 1, 0);
    // 경계 ±3일
    for (let i = -3; i <= 3; i++) {
      const d1 = new Date(startDate); d1.setDate(d1.getDate() + i);
      const d2 = new Date(endDate); d2.setDate(d2.getDate() + i);
      boundaryDates.add(d1.toISOString().slice(0, 10));
      boundaryDates.add(d2.toISOString().slice(0, 10));
    }
  }

  // 경계일에 awarded_at이 있는 포인트 집계 (사용자 × 날짜)
  const byUserDate = {};
  for (const p of db.engagement_points || []) {
    if (!p.awarded_at) continue;
    const dateStr = new Date(Number(p.awarded_at)).toISOString().slice(0, 10);
    if (!boundaryDates.has(dateStr)) continue;
    const key = `${p.member_name || p.user_id}|${dateStr}`;
    if (!byUserDate[key]) byUserDate[key] = { count: 0, pts: 0, member: p.member_name || p.user_id, date: dateStr, ids: [] };
    byUserDate[key].count += 1;
    byUserDate[key].pts += Number(p.points) || 0;
    byUserDate[key].ids.push(p.id);
  }
  for (const [, v] of Object.entries(byUserDate)) {
    if (v.count >= 5) {
      issues.push({
        category: 'points_quarter_boundary',
        severity: 'medium',
        message: `${v.member} ${v.date} 분기 경계 집중 적립 ${v.count}건 (${v.pts}pt)`,
        details: { member: v.member, date: v.date, count: v.count, pts: v.pts, ep_ids: v.ids },
        fix_hint: `해당 날짜 적립 내역 직접 검토 — 정상이면 무시 가능`,
      });
    }
  }
  return issues;
}

/**
 * 검사 17: 동일 action_ref 에 복수 user_id 로 포인트 적립 (가짜 적립 의심).
 * 한 record 가 두 명 이상에게 적립되면 비정상.
 */
function checkPointsDuplicateUser(db) {
  const issues = [];
  // action_ref → [user/member 목록]
  const byRef = {};
  for (const p of db.engagement_points || []) {
    if (!p.action_ref) continue;
    const refKey = `${p.action_type}:${p.action_ref}`;
    if (!byRef[refKey]) byRef[refKey] = [];
    byRef[refKey].push({ user_id: p.user_id, member_name: p.member_name, ep_id: p.id });
  }
  for (const [refKey, entries] of Object.entries(byRef)) {
    // 중복 포인트 가능한 케이스: first_sop / first_issue / quarterly_mission 은 사람별 고유하므로 OK
    const [actionType] = refKey.split(':');
    const skipTypes = new Set(['first_sop', 'first_issue', 'quarterly_mission', 'streak_bonus', 'kpi_entry', 'settlement_check']);
    if (skipTypes.has(actionType)) continue;
    const uniqueUsers = new Set(entries.map(e => e.user_id || e.member_name));
    if (uniqueUsers.size > 1) {
      issues.push({
        category: 'points_duplicate_user',
        severity: 'high',
        message: `action_ref "${refKey}" 에 ${uniqueUsers.size}명 적립: [${[...uniqueUsers].join(', ')}]`,
        details: { ref_key: refKey, entries: entries.map(e => ({ ep_id: e.ep_id, user: e.user_id || e.member_name })) },
        fix_hint: `대리 입력 차단 로직 확인 — 정당한 적립 1건 제외하고 나머지 삭제`,
      });
    }
  }
  return issues;
}

/**
 * 검사 18: 비활성 사용자의 engagement_points 잔존.
 * (재활성화 후 옛 포인트가 리더보드에 합산되는 위험)
 */
function checkPointsInactiveUser(db) {
  const issues = [];
  const activeNames = new Set(
    (db.users || []).filter(u => u.is_active !== false).map(u => u.full_name || u.username)
  );
  const activeIds = new Set(
    (db.users || []).filter(u => u.is_active !== false).map(u => u.id)
  );
  const seen = new Set();
  for (const p of db.engagement_points || []) {
    const key = p.member_name || p.user_id;
    if (seen.has(key)) continue;
    const isActive = (p.user_id && activeIds.has(p.user_id)) || (p.member_name && activeNames.has(p.member_name));
    if (!isActive) {
      seen.add(key);
      const total = (db.engagement_points || [])
        .filter(x => (x.user_id === p.user_id && p.user_id) || (x.member_name === p.member_name && p.member_name))
        .reduce((s, x) => s + (Number(x.points) || 0), 0);
      issues.push({
        category: 'points_inactive_user_ledger',
        severity: 'medium',
        message: `${key} 비활성/삭제 사용자의 포인트 ${total}pt 잔존 — 재활성화 시 리더보드 합산 위험`,
        details: { member: key, total_points: total },
        fix_hint: `사용자 복원 의사 없으면 해당 engagement_points 일괄 삭제 검토`,
      });
    }
  }
  return issues;
}

/**
 * 검사 19: 멤버명 변경으로 인한 리더보드 단절 의심.
 * 동일 user_id 에 두 가지 이상의 member_name 이 섞여있는 경우.
 */
function checkPointsMemberRename(db) {
  const issues = [];
  const byUserId = {};
  for (const p of db.engagement_points || []) {
    if (!p.user_id || !p.member_name) continue;
    if (!byUserId[p.user_id]) byUserId[p.user_id] = new Set();
    byUserId[p.user_id].add(p.member_name);
  }
  for (const [uid, names] of Object.entries(byUserId)) {
    if (names.size > 1) {
      const nameArr = [...names];
      const totalPts = (db.engagement_points || [])
        .filter(p => p.user_id === uid)
        .reduce((s, p) => s + (Number(p.points) || 0), 0);
      issues.push({
        category: 'points_member_rename',
        severity: 'medium',
        message: `user_id=${uid} 에 멤버명 ${names.size}개 혼재: [${nameArr.join(', ')}] — 리더보드 집계 분리 위험 (합산 ${totalPts}pt)`,
        details: { user_id: uid, member_names: nameArr, total_points: totalPts },
        fix_hint: `engagement_points 의 member_name 을 현재 users.full_name 으로 통일`,
      });
    }
  }
  return issues;
}

/**
 * 검사 20: first_sop / first_issue 보너스가 실제로 분기 첫 건이 맞는지 검증.
 * (분기 내 해당 action_type 이 first_* 보너스 이전에 이미 있었다면 자가 적립 오류)
 * 또한 future: sop_share 보너스에서 자기 SOP 를 자기가 참조하면 → 가짜 공유 보너스 탐지.
 */
function checkPointsSelfSopRef(db) {
  const issues = [];
  // first_sop 검증 — 분기에 sop_create 보너스가 있는데 그 이전 분기에 이미 sop_create 건 있는 경우 → OK
  // 분기 내 first_* 보너스가 있는데 해당 분기 같은 action의 건이 2건 이상인 경우 (순서 확인 안 되므로 경고)
  const quarterFirstMap = {};
  for (const p of db.engagement_points || []) {
    if (p.action_type !== 'first_sop' && p.action_type !== 'first_issue') continue;
    const key = `${p.action_type}:${p.quarter}:${p.member_name || p.user_id}`;
    quarterFirstMap[key] = p;
  }

  for (const [key, firstRow] of Object.entries(quarterFirstMap)) {
    const [bonusType, quarter, member] = key.split(':').reduce((acc, v, i) => {
      if (i < 2) acc.push(v);
      else acc[2] = (acc[2] || '') + (acc.length > 2 ? ':' : '') + v;
      return acc;
    }, []);
    const mainType = bonusType === 'first_sop' ? 'sop_create' : 'issue_register';
    const countInQ = (db.engagement_points || []).filter(p =>
      p.action_type === mainType &&
      p.quarter === firstRow.quarter &&
      (p.member_name === (firstRow.member_name) || p.user_id === firstRow.user_id)
    ).length;
    if (countInQ === 0) {
      issues.push({
        category: 'points_self_sop_ref',
        severity: 'medium',
        message: `${firstRow.member_name || firstRow.user_id} ${firstRow.quarter} ${bonusType} 보너스 존재하지만 분기 내 ${mainType} 적립 0건 — 첫 보너스 오발급 의심`,
        details: { ep_id: firstRow.id, bonus_type: bonusType, quarter: firstRow.quarter },
        fix_hint: `engagement_points[${firstRow.id}] 삭제 검토`,
      });
    }
  }
  return issues;
}

/**
 * 검사 14: kb_document_versions 의 부모 문서가 사라짐
 */
function checkKbVersionOrphan(db) {
  const issues = [];
  const docIds = new Set((db.kb_documents || []).map(d => d.id));
  for (const v of db.kb_document_versions || []) {
    if (v.document_id && !docIds.has(v.document_id)) {
      issues.push({
        category: 'kb_version_orphan',
        severity: 'medium',
        message: `kb_document_versions[${v.id}] v${v.version} — 부모 문서 ${v.document_id} 사라짐`,
        details: { ver_id: v.id, document_id: v.document_id, version: v.version },
        fix_hint: `kb_document_versions[${v.id}] 삭제`,
      });
    }
  }
  return issues;
}

/**
 * 메인 entry point. server.js가 호출.
 * @param {object} db - 현재 DB (server.js의 readDb 결과)
 * @returns {object} report - audit_reports에 push할 객체
 */
function runAudit(db) {
  const startedAt = Date.now();
  const checks = [
    ['perf_orphan_quant', checkPerfOrphanQuant],
    ['perf_orphan_deadline', checkPerfOrphanDeadline],
    ['perf_inactive', checkPerfInactive],
    ['dwe_inactive', checkDweInactive],
    ['work_task_zombie', checkWorkTaskZombie],
    ['vacation_inactive', checkVacationInactive],
    ['vacation_quota_mismatch', checkVacationQuotaMismatch],
    ['vacation_quota_excess', checkVacationQuotaExcess],
    ['vacation_overlap_self', checkVacationOverlapSelf],
    ['vacation_work_conflict', checkVacationWorkConflict],
    ['vacation_no_status', checkVacationNoStatus],
    ['vacation_invalid_minutes', checkVacationInvalidMinutes],
    ['points_orphan', checkPointsOrphan],
    ['kb_version_orphan', checkKbVersionOrphan],
    // Phase 9: 신규 검사
    ['points_rule_stale', checkPointsRuleStale],
    ['points_quarter_boundary', checkPointsQuarterBoundary],
    ['points_duplicate_user', checkPointsDuplicateUser],
    ['points_inactive_user_ledger', checkPointsInactiveUser],
    ['points_member_rename', checkPointsMemberRename],
    ['points_self_sop_ref', checkPointsSelfSopRef],
  ];
  const allIssues = [];
  const errors = [];
  const byCategory = {};
  for (const [name, fn] of checks) {
    try {
      const issues = fn(db) || [];
      byCategory[name] = issues.length;
      for (const it of issues) allIssues.push(it);
    } catch (e) {
      errors.push({ check: name, message: e && e.message || String(e) });
      byCategory[name] = -1;
    }
  }
  const finishedAt = Date.now();
  return {
    id: createId(),
    run_at: finishedAt,
    duration_ms: finishedAt - startedAt,
    status: errors.length === 0 ? (allIssues.length === 0 ? 'clean' : 'issues') : 'partial',
    summary: {
      total_issues: allIssues.length,
      by_category: byCategory,
      by_severity: {
        high: allIssues.filter(i => i.severity === 'high').length,
        medium: allIssues.filter(i => i.severity === 'medium').length,
        low: allIssues.filter(i => i.severity === 'low').length,
      },
    },
    issues: allIssues,
    errors,
  };
}

module.exports = { runAudit, CATEGORIES };
