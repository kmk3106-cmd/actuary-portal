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
