'use strict';

/**
 * Audit 자동 수정 (Self-Healing)
 *
 * runAudit 가 검출한 issue 중 **사람 판단 불필요** 한 항목만 자동 정정.
 * 사람 판단 필요한 케이스(비활성 사용자 데이터, 한도 초과, 중복 휴가 등)는 SKIP.
 *
 * 자동 fix 대상:
 *  - perf_orphan_quant       : performance_records 의 raw/score 잔존 → null
 *  - perf_orphan_deadline    : performance_records.score_deadline 잔존 → null
 *  - work_task_zombie        : settlement_* 에 settlement_done 에 없는 키 제거
 *  - vacation_quota_mismatch : vacation_quotas.used 재계산
 *  - vacation_no_status      : status 누락 → 'approved'
 *  - vacation_invalid_minutes: minutes/hours/days 를 time_entries 합으로 재계산
 *  - points_orphan           : 대상 사라진 engagement_points 행 제거
 *  - kb_version_orphan       : 부모 사라진 kb_document_versions 행 제거
 *
 * SKIP 대상 (사람 판단 필요):
 *  - perf_inactive / dwe_inactive / vacation_inactive (사용자 복원 가능성)
 *  - vacation_quota_excess  (한도 상향 vs 휴가 취소 결정)
 *  - vacation_overlap_self  (어느 휴가를 살릴지)
 *  - vacation_work_conflict (휴가/업무 중 어느 쪽을 손볼지)
 */

const AUTO_FIX_CATEGORIES = new Set([
  'perf_orphan_quant',
  'perf_orphan_deadline',
  'work_task_zombie',
  'vacation_quota_mismatch',
  'vacation_no_status',
  'vacation_invalid_minutes',
  'points_orphan',
  'kb_version_orphan',
  // Phase 9 자동 수정 가능
  'points_rule_stale',   // 비활성 룰 이후 적립 → 자동 삭제
  'points_self_sop_ref', // 오발급 first_bonus → 자동 삭제
  // 아래는 사람 판단 필요 (SKIP)
  // points_quarter_boundary: 정상일 수도 있음
  // points_duplicate_user: 어느 건을 남길지 판단 필요
  // points_inactive_user_ledger: 사용자 복원 의사 확인 필요
  // points_member_rename: 이름 통일 방향 확인 필요
]);

function asArray(v) {
  if (Array.isArray(v)) return v;
  if (typeof v === 'string') { try { const p = JSON.parse(v); return Array.isArray(p) ? p : []; } catch { return []; } }
  return [];
}
function asObject(v) {
  if (v == null) return null;
  if (typeof v === 'object') return v;
  if (typeof v === 'string') { try { return JSON.parse(v); } catch { return null; } }
  return null;
}

// ── 개별 fix 핸들러 ──

function fixPerfOrphanQuant(db, issue) {
  const { pr_id } = issue.details || {};
  const pr = (db.performance_records || []).find(r => r.id === pr_id);
  if (!pr) return false;
  const cleared = [];
  for (const [rawF, scoreF] of [
    ['raw_directive', 'score_directive'],
    ['raw_csm_amount', 'score_csm'],
    ['raw_meeting_count', 'score_meeting'],
  ]) {
    // issue.fix_hint 가 어떤 필드를 가리키는지 details 에 충분히 명시되어 있지 않으므로
    // 일관성을 위해 issue.message 의 rawF 키워드로 분기.
    if (issue.message && issue.message.includes(rawF)) {
      pr[rawF] = null;
      pr[scoreF] = null;
      cleared.push(rawF, scoreF);
    }
  }
  if (cleared.length === 0) return false;
  pr.updated_at = Date.now();
  return true;
}

function fixPerfOrphanDeadline(db, issue) {
  const { pr_id } = issue.details || {};
  const pr = (db.performance_records || []).find(r => r.id === pr_id);
  if (!pr) return false;
  pr.score_deadline = null;
  pr.updated_at = Date.now();
  return true;
}

function fixWorkTaskZombie(db, issue) {
  const { wt_id, field, orphan_keys } = issue.details || {};
  const wt = (db.work_tasks || []).find(t => t.id === wt_id);
  if (!wt || !field || !Array.isArray(orphan_keys)) return false;
  const obj = asObject(wt[field]) || {};
  let changed = false;
  for (const k of orphan_keys) {
    if (k in obj) { delete obj[k]; changed = true; }
  }
  if (!changed) return false;
  wt[field] = obj;
  wt.updated_at = Date.now();
  return true;
}

function fixVacationQuotaMismatch(db, issue) {
  const { quota_id, actual_used } = issue.details || {};
  const q = (db.vacation_quotas || []).find(x => x.id === quota_id);
  if (!q) return false;
  q.used = Math.round((Number(actual_used) || 0) * 100) / 100;
  q.remaining = Math.round(((q.annual_total || 0) - q.used) * 100) / 100;
  q.updated_at = Date.now();
  return true;
}

function fixVacationNoStatus(db, issue) {
  const { vac_id } = issue.details || {};
  const v = (db.vacations || []).find(x => x.id === vac_id);
  if (!v) return false;
  v.status = 'approved';
  v.updated_at = Date.now();
  return true;
}

function fixVacationInvalidMinutes(db, issue) {
  const { vac_id, computed } = issue.details || {};
  const v = (db.vacations || []).find(x => x.id === vac_id);
  if (!v) return false;
  const minutes = Number(computed) || 0;
  v.minutes = minutes;
  v.hours = Math.round((minutes / 60) * 10) / 10;
  v.days  = Math.round((minutes / (8 * 60)) * 100) / 100;
  v.updated_at = Date.now();
  return true;
}

function fixPointsOrphan(db, issue) {
  const { ep_id } = issue.details || {};
  if (!Array.isArray(db.engagement_points)) return false;
  const before = db.engagement_points.length;
  db.engagement_points = db.engagement_points.filter(p => p.id !== ep_id);
  return db.engagement_points.length < before;
}

function fixKbVersionOrphan(db, issue) {
  const { ver_id } = issue.details || {};
  if (!Array.isArray(db.kb_document_versions)) return false;
  const before = db.kb_document_versions.length;
  db.kb_document_versions = db.kb_document_versions.filter(v => v.id !== ver_id);
  return db.kb_document_versions.length < before;
}

// ── Phase 9 신규 fix 핸들러 ──

function fixPointsRuleStale(db, issue) {
  const { ep_id } = issue.details || {};
  if (!Array.isArray(db.engagement_points)) return false;
  const before = db.engagement_points.length;
  db.engagement_points = db.engagement_points.filter(p => p.id !== ep_id);
  return db.engagement_points.length < before;
}

function fixPointsSelfSopRef(db, issue) {
  const { ep_id } = issue.details || {};
  if (!Array.isArray(db.engagement_points)) return false;
  const before = db.engagement_points.length;
  db.engagement_points = db.engagement_points.filter(p => p.id !== ep_id);
  return db.engagement_points.length < before;
}

const FIX_HANDLERS = {
  perf_orphan_quant:        fixPerfOrphanQuant,
  perf_orphan_deadline:     fixPerfOrphanDeadline,
  work_task_zombie:         fixWorkTaskZombie,
  vacation_quota_mismatch:  fixVacationQuotaMismatch,
  vacation_no_status:       fixVacationNoStatus,
  vacation_invalid_minutes: fixVacationInvalidMinutes,
  points_orphan:            fixPointsOrphan,
  kb_version_orphan:        fixKbVersionOrphan,
  // Phase 9
  points_rule_stale:        fixPointsRuleStale,
  points_self_sop_ref:      fixPointsSelfSopRef,
};

/**
 * @param {object} db
 * @param {Array<object>} issues  runAudit 결과의 issues
 * @returns {object} { fixed: [...], skipped: [...] }
 */
function applyAutoFix(db, issues) {
  const fixed = [];
  const skipped = [];
  for (const issue of issues || []) {
    if (!AUTO_FIX_CATEGORIES.has(issue.category)) {
      skipped.push({ category: issue.category, message: issue.message, reason: 'manual_review_required' });
      continue;
    }
    const handler = FIX_HANDLERS[issue.category];
    if (!handler) {
      skipped.push({ category: issue.category, message: issue.message, reason: 'no_handler' });
      continue;
    }
    try {
      const ok = handler(db, issue);
      if (ok) {
        fixed.push({ category: issue.category, message: issue.message });
      } else {
        skipped.push({ category: issue.category, message: issue.message, reason: 'no_match' });
      }
    } catch (e) {
      skipped.push({ category: issue.category, message: issue.message, reason: 'error:' + e.message });
    }
  }
  return { fixed, skipped };
}

module.exports = { applyAutoFix, AUTO_FIX_CATEGORIES };
