'use strict';

/**
 * Engagement Points & Quarterly Rewards
 *
 * - awardPoints: 룰 기반 포인트 적립. idempotency_key 로 중복 방지.
 * - currentQuarter / quarterRange: 분기 헬퍼
 * - getQuarterRanking / top3WithPrizes: 분기 랭킹 (team_leader 제외)
 * - finalizeQuarter: prize_history 에 멱등으로 기록
 *
 * 의존 테이블: engagement_points, point_rules, prize_rules, prize_history, users
 */

const crypto = require('crypto');

const DEFAULT_RULES = [
  { action_type: 'kpi_entry',        label: 'KPI 입력',          points: 10, description: 'work_tasks PATCH 시 KPI 필드 최초 채워졌을 때 (분기당 1회)' },
  { action_type: 'work_entry',       label: '개인업무 저장',     points: 5,  description: 'daily_work_entries POST 시 (member × 월 × task_label × task_category) 그룹당 1회 — 시간대 분할로 부풀리기 차단' },
  { action_type: 'issue_register',   label: '이슈 사례 등록',     points: 20, description: 'kb_issues POST 1건당' },
  { action_type: 'sop_create',       label: 'SOP 작성',          points: 30, description: 'kb_documents POST 1건당' },
  { action_type: 'settlement_check', label: '결산 체크리스트',   points: 3,  description: 'work_tasks PATCH 시 settlement_done 배열에 새 키 추가될 때 1키당 3pt (분기당 30건·90pt 캡). 체크 해제 시 해당 적립 회수.' },
];

const DEFAULT_PRIZES = [
  { rank: 1, prize_amount: 300000, label: '식사권 30만원' },
  { rank: 2, prize_amount: 100000, label: '식사권 10만원' },
  { rank: 3, prize_amount: 50000,  label: '식사권 5만원'  },
];

function now() { return Date.now(); }

function createId(prefix) {
  return `${prefix}_${crypto.randomBytes(8).toString('hex')}`;
}

/**
 * 'YYYY-Qn' (n in 1..4) — Date 객체 전달 안 하면 현재
 */
function currentQuarter(date) {
  const d = date || new Date();
  const y = d.getFullYear();
  const q = Math.floor(d.getMonth() / 3) + 1;
  return `${y}-Q${q}`;
}

/**
 * 'YYYY-Qn' → { from: 'YYYY-MM-DD', to: 'YYYY-MM-DD' }
 */
function quarterRange(quarter) {
  const m = /^(\d{4})-Q([1-4])$/.exec(String(quarter || ''));
  if (!m) return null;
  const y = parseInt(m[1], 10);
  const q = parseInt(m[2], 10);
  const startMonth = (q - 1) * 3;       // 0,3,6,9
  const endMonth = startMonth + 2;      // 2,5,8,11
  const lastDay = new Date(y, endMonth + 1, 0).getDate();
  const pad = n => String(n).padStart(2, '0');
  return {
    from: `${y}-${pad(startMonth + 1)}-01`,
    to:   `${y}-${pad(endMonth + 1)}-${pad(lastDay)}`,
  };
}

function seedPointsConfig(db) {
  const t = now();
  let changed = false;
  if (!Array.isArray(db.point_rules)) { db.point_rules = []; changed = true; }
  if (!Array.isArray(db.prize_rules)) { db.prize_rules = []; changed = true; }
  if (!Array.isArray(db.prize_history)) { db.prize_history = []; changed = true; }
  if (!Array.isArray(db.engagement_points)) { db.engagement_points = []; changed = true; }
  if (db.point_rules.length === 0) {
    db.point_rules = DEFAULT_RULES.map((r, i) => ({
      id: `pr_${r.action_type}`, ...r, is_active: true,
      created_at: t, updated_at: t, sort_order: i + 1,
    }));
    changed = true;
  }
  if (db.prize_rules.length === 0) {
    db.prize_rules = DEFAULT_PRIZES.map(p => ({
      id: `pz_rank${p.rank}`, ...p, is_active: true,
      created_at: t, updated_at: t,
    }));
    changed = true;
  }
  return changed;
}

function isTeamLeader(db, userId, memberName) {
  const users = db.users || [];
  if (userId) {
    const u = users.find(x => x.id === userId);
    if (u && u.role === 'team_leader') return true;
  }
  if (memberName) {
    const u = users.find(x => (x.full_name || x.username) === memberName);
    if (u && u.role === 'team_leader') return true;
  }
  return false;
}

/**
 * 포인트 적립 — 멱등성 (idempotency_key 기준)
 *
 * 적립 조건 (모두 충족해야 함):
 *  - actorId/actorName이 주어지면 → target(userId/memberName)과 동일해야 함 (대리 입력은 적립 X)
 *  - target이 팀장이 아닐 것 (팀장 본인 활동은 적립 X)
 *
 * @param {object} db
 * @param {string} userId       target user_id (적립 대상)
 * @param {string} memberName   target member_name
 * @param {string} actionType
 * @param {string} actionRef    보통 대상 record id
 * @param {object} actorOpts    { actorId, actorName } — 실제 액션을 수행한 사용자
 * @returns {object|null}  생성된 row 또는 null
 */
function awardPoints(db, userId, memberName, actionType, actionRef, actorOpts) {
  if (!actionType || !actionRef) return null;
  if (!memberName && !userId) return null;
  // 팀장은 적립 대상 아님 (본인이 입력해도 본인에게 안 쌓임)
  if (isTeamLeader(db, userId, memberName)) return null;
  // actor 검증: actor 정보가 있을 때만 검사 (없으면 자동 시드/마이그레이션 케이스로 허용)
  if (actorOpts && (actorOpts.actorId || actorOpts.actorName)) {
    const actorIsLeader = isTeamLeader(db, actorOpts.actorId, actorOpts.actorName);
    if (actorIsLeader) return null; // 팀장이 대리 입력 → 적립 X
    // 본인이 본인 입력인지 검사
    const sameUser = actorOpts.actorId && userId && actorOpts.actorId === userId;
    const sameName = actorOpts.actorName && memberName && actorOpts.actorName === memberName;
    if (!sameUser && !sameName) return null; // 다른 사람이 대리 입력 → 적립 X
  }
  const rules = db.point_rules || [];
  const rule = rules.find(r => r.action_type === actionType && r.is_active !== false);
  if (!rule) return null;
  const points = Number(rule.points) || 0;
  if (points <= 0) return null;
  const idempotency_key = `${actionType}:${actionRef}`;
  const list = db.engagement_points || [];
  if (list.some(p => p.idempotency_key === idempotency_key)) return null;
  const t = now();
  const row = {
    id: createId('ep'),
    user_id: userId || '',
    member_name: memberName || '',
    action_type: actionType,
    action_ref: String(actionRef),
    points,
    quarter: currentQuarter(),
    awarded_at: t,
    idempotency_key,
    actor_user_id: (actorOpts && actorOpts.actorId) || '',
    actor_name:    (actorOpts && actorOpts.actorName) || '',
    created_at: t,
    updated_at: t,
  };
  db.engagement_points = [...list, row];
  return row;
}

/**
 * 개인업무(work_entry) 그룹 멱등 적립.
 *
 * 같은 (member_name × YYYY-MM × task_label × task_category) 조합이 이미 해당 분기에
 * 적립되어 있으면 skip — 시간대 분할 입력으로 포인트를 부풀리는 행위 차단.
 * 멱등 키는 entry.id 를 그대로 사용(표준 awardPoints 경유), 단 skip 판단만 그룹 기준.
 *
 * @param {object}  db
 * @param {string}  entryId       newly created daily_work_entries.id
 * @param {string}  userId
 * @param {string}  memberName
 * @param {string}  ymPrefix      'YYYY-MM'
 * @param {string}  taskLabel     e.task_label
 * @param {string}  taskCategory  e.task_category
 * @param {object}  actorOpts
 */
function awardWorkEntryGrouped(db, entryId, userId, memberName, ymPrefix, taskLabel, taskCategory, actorOpts) {
  if (!entryId || !memberName) return null;
  if (isTeamLeader(db, userId, memberName)) return null;
  // 이미 동일 그룹 적립이 있는지 — engagement_points 의 action_type='work_entry' 를 스캔
  const list = db.engagement_points || [];
  const groupAlreadyAwarded = list.some(p => {
    if (p.action_type !== 'work_entry') return false;
    if (p.member_name !== memberName) return false;
    // action_ref 는 다른 entry.id 이지만, meta에 그룹 키를 박아뒀음
    return p.group_key === `${memberName}:${ymPrefix}:${taskLabel}:${taskCategory}`;
  });
  if (groupAlreadyAwarded) return null;
  // 표준 awardPoints 호출 — 멱등 키는 entry.id 기반
  const rules = db.point_rules || [];
  const rule = rules.find(r => r.action_type === 'work_entry' && r.is_active !== false);
  if (!rule) return null;
  const pointsVal = Number(rule.points) || 0;
  if (pointsVal <= 0) return null;
  const idempotency_key = `work_entry:${entryId}`;
  if (list.some(p => p.idempotency_key === idempotency_key)) return null;
  const t = now();
  const row = {
    id: createId('ep'),
    user_id: userId || '',
    member_name: memberName || '',
    action_type: 'work_entry',
    action_ref: String(entryId),
    points: pointsVal,
    quarter: currentQuarter(),
    awarded_at: t,
    idempotency_key,
    group_key: `${memberName}:${ymPrefix}:${taskLabel}:${taskCategory}`,
    actor_user_id: (actorOpts && actorOpts.actorId) || '',
    actor_name:    (actorOpts && actorOpts.actorName) || '',
    created_at: t,
    updated_at: t,
  };
  db.engagement_points = [...list, row];
  return row;
}

/**
 * 결산 체크리스트 체크/해제 처리.
 *
 * - 체크(newDone 에 있고 beforeDone 에 없는 키) → settlement_check:<wtId>:<key> 로 적립.
 * - 해제(beforeDone 에 있고 newDone 에 없는 키) → 해당 멱등 키의 engagement_points 삭제(회수).
 * - 분기당 30건(90pt) 캡: 현재 분기에 이미 30건 이상이면 추가 적립 스킵.
 *
 * @param {object}   db
 * @param {object}   updated   work_tasks PATCH 결과
 * @param {object}   before    work_tasks 이전 값
 * @param {object}   actorOpts { actorId, actorName }
 * @returns {{ awarded: string[], revoked: string[] }}
 */
function syncSettlementCheckPoints(db, updated, before, actorOpts) {
  const awarded = [];
  const revoked = [];
  if (!updated || !updated.id) return { awarded, revoked };

  const userId = updated.user_id || updated.member_id || '';
  const memberName = updated.member_name || updated.target_name || '';
  if (isTeamLeader(db, userId, memberName)) return { awarded, revoked };

  // actor 가드 — 본인 입력인지 확인 (팀장이 대리 체크 시 적립 X)
  if (actorOpts && (actorOpts.actorId || actorOpts.actorName)) {
    const actorIsLeader = isTeamLeader(db, actorOpts.actorId, actorOpts.actorName);
    if (actorIsLeader) return { awarded, revoked };
    const sameUser = actorOpts.actorId && userId && actorOpts.actorId === userId;
    const sameName = actorOpts.actorName && memberName && actorOpts.actorName === memberName;
    if (!sameUser && !sameName) return { awarded, revoked };
  }

  const beforeDone = new Set(Array.isArray(before.settlement_done) ? before.settlement_done : []);
  const newDone    = new Set(Array.isArray(updated.settlement_done) ? updated.settlement_done : []);

  // 분기당 캡 — 현재 분기 settlement_check 적립 건수 조회
  const QUARTER_CAP = 30; // 30건 × 3pt = 90pt
  const q = currentQuarter();
  const list = db.engagement_points || [];

  // 체크 해제된 키 → 회수
  for (const key of beforeDone) {
    if (!newDone.has(key)) {
      const ikey = `settlement_check:${updated.id}:${key}`;
      const before_len = list.length;
      db.engagement_points = db.engagement_points.filter(p => p.idempotency_key !== ikey);
      if (db.engagement_points.length < before_len) {
        revoked.push(key);
      }
    }
  }

  // 새로 체크된 키 → 적립
  const rules = db.point_rules || [];
  const rule = rules.find(r => r.action_type === 'settlement_check' && r.is_active !== false);
  if (!rule) return { awarded, revoked };
  const pointsVal = Number(rule.points) || 0;
  if (pointsVal <= 0) return { awarded, revoked };

  for (const key of newDone) {
    if (beforeDone.has(key)) continue; // 기존 체크 — skip
    const ikey = `settlement_check:${updated.id}:${key}`;
    const currentList = db.engagement_points || [];
    if (currentList.some(p => p.idempotency_key === ikey)) continue; // 이미 적립됨

    // 분기 캡 검사
    const quarterCount = currentList.filter(p =>
      p.action_type === 'settlement_check' &&
      p.quarter === q &&
      ((memberName && p.member_name === memberName) || (userId && p.user_id === userId))
    ).length;
    if (quarterCount >= QUARTER_CAP) continue; // 캡 초과 — skip

    const t = now();
    const row = {
      id: createId('ep'),
      user_id: userId || '',
      member_name: memberName || '',
      action_type: 'settlement_check',
      action_ref: `${updated.id}:${key}`,
      points: pointsVal,
      quarter: q,
      awarded_at: t,
      idempotency_key: ikey,
      actor_user_id: (actorOpts && actorOpts.actorId) || '',
      actor_name:    (actorOpts && actorOpts.actorName) || '',
      created_at: t,
      updated_at: t,
    };
    db.engagement_points = [...(db.engagement_points || []), row];
    awarded.push(key);
  }

  return { awarded, revoked };
}

/**
 * 분기당 1회만 적립 (action_type 단위) — 예: KPI 입력
 * actionRef 는 무시되고 quarter + actionType + memberName 기준으로 멱등
 */
function awardPointsOncePerQuarter(db, userId, memberName, actionType, hintRef, actorOpts) {
  if (!memberName && !userId) return null;
  if (isTeamLeader(db, userId, memberName)) return null;
  const q = currentQuarter();
  const list = db.engagement_points || [];
  const exists = list.some(p =>
    p.action_type === actionType &&
    p.quarter === q &&
    ((memberName && p.member_name === memberName) || (userId && p.user_id === userId))
  );
  if (exists) return null;
  const ref = `${q}:${memberName || userId}:${hintRef || 'once'}`;
  return awardPoints(db, userId, memberName, actionType, ref, actorOpts);
}

/**
 * 분기 랭킹 (팀장 제외, points 내림차순)
 */
function getQuarterRanking(db, quarter) {
  const q = quarter || currentQuarter();
  const list = (db.engagement_points || []).filter(p => p.quarter === q);
  const users = db.users || [];
  const tlNames = new Set(users.filter(u => u.role === 'team_leader')
    .map(u => u.full_name || u.username));
  const tlIds = new Set(users.filter(u => u.role === 'team_leader').map(u => u.id));
  const byKey = new Map();
  for (const p of list) {
    if (tlIds.has(p.user_id)) continue;
    if (tlNames.has(p.member_name)) continue;
    const key = p.member_name || p.user_id || 'unknown';
    if (!byKey.has(key)) {
      byKey.set(key, {
        member_name: p.member_name || '',
        user_id: p.user_id || '',
        points: 0,
        breakdown: {},
      });
    }
    const agg = byKey.get(key);
    agg.points += Number(p.points) || 0;
    agg.breakdown[p.action_type] = (agg.breakdown[p.action_type] || 0) + (Number(p.points) || 0);
  }
  return Array.from(byKey.values())
    .sort((a, b) => b.points - a.points || a.member_name.localeCompare(b.member_name));
}

function top3WithPrizes(db, quarter) {
  const q = quarter || currentQuarter();
  const rank = getQuarterRanking(db, q);
  const prizes = (db.prize_rules || []).filter(p => p.is_active !== false);
  const prizeByRank = {};
  prizes.forEach(p => { prizeByRank[p.rank] = p; });
  const top3 = rank.slice(0, 3).map((r, i) => {
    const rk = i + 1;
    const pz = prizeByRank[rk];
    return {
      rank: rk,
      member_name: r.member_name,
      user_id: r.user_id,
      points: r.points,
      breakdown: r.breakdown,
      prize_amount: pz ? pz.prize_amount : 0,
      prize_label: pz ? pz.label : '',
    };
  });
  return { quarter: q, top3, total_participants: rank.length };
}

/**
 * 분기 시상 확정 — prize_history 에 멱등 INSERT
 */
function finalizeQuarter(db, quarter) {
  const q = quarter || currentQuarter();
  const list = db.prize_history || [];
  const existed = list.filter(h => h.quarter === q);
  if (existed.length > 0) {
    return { quarter: q, already_finalized: true, entries: existed };
  }
  const { top3 } = top3WithPrizes(db, q);
  const t = now();
  const created = top3.map(w => ({
    id: createId('pzh'),
    quarter: q,
    rank: w.rank,
    user_id: w.user_id,
    member_name: w.member_name,
    points: w.points,
    prize_amount: w.prize_amount,
    prize_label: w.prize_label,
    awarded_at: t,
    created_at: t,
    updated_at: t,
  }));
  db.prize_history = [...list, ...created];
  return { quarter: q, already_finalized: false, entries: created };
}

module.exports = {
  DEFAULT_RULES,
  DEFAULT_PRIZES,
  seedPointsConfig,
  currentQuarter,
  quarterRange,
  awardPoints,
  awardPointsOncePerQuarter,
  awardWorkEntryGrouped,
  syncSettlementCheckPoints,
  getQuarterRanking,
  top3WithPrizes,
  finalizeQuarter,
};
