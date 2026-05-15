'use strict';

/**
 * Engagement Points & Quarterly Rewards
 *
 * - awardPoints: 룰 기반 포인트 적립. idempotency_key 로 중복 방지.
 * - currentQuarter / quarterRange: 분기 헬퍼
 * - getQuarterRanking / top3WithPrizes: 분기 랭킹 (team_leader 제외)
 * - finalizeQuarter: prize_history 에 멱등으로 기록
 *
 * ── Phase 9 신규 게임 요소 ──
 * - streak_bonus: 영업일 연속 work_entry 입력 시 streak×0.5pt 가산 (하루 최대 +10pt)
 * - quarterly_mission: 분기당 KPI×1 + SOP×1 + 이슈×3 달성 시 +30pt 배지 보너스
 *
 * ── Phase 9 신규 보상 체계 ──
 * - getParticipationAward: 분기 50pt 이상 전원 참여상 (비금전)
 * - getGrowthAward: 직전 분기 대비 증가율 TOP3 별도 시상
 * - getCategoryMvp: SOP MVP / 이슈 MVP / 결산 MVP 부문별 시상
 *
 * 의존 테이블: engagement_points, point_rules, prize_rules, prize_history, users
 */

const crypto = require('crypto');

const DEFAULT_RULES = [
  { action_type: 'kpi_entry',        label: 'KPI 입력',          points: 10, description: 'work_tasks PATCH 시 KPI 필드 최초 채워졌을 때 (분기당 1회)' },
  { action_type: 'work_entry',       label: '개인업무 저장',     points: 5,  description: 'daily_work_entries POST 시 (member × 월 × task_label × task_category) 그룹당 1회 — 시간대 분할로 부풀리기 차단' },
  { action_type: 'issue_register',   label: '이슈 사례 등록',    points: 20, description: 'kb_issues POST 1건당' },
  { action_type: 'sop_create',       label: '절차서 작성',        points: 30, description: '계리업무절차서(kb_documents) 작성 1건당' },
  { action_type: 'settlement_check', label: '결산 체크리스트',   points: 3,  description: 'work_tasks PATCH 시 settlement_done 배열에 새 키 추가될 때 1키당 3pt (분기당 30건·90pt 캡). 체크 해제 시 해당 적립 회수.' },
  // ── Phase 9: 게임 요소 ──
  { action_type: 'streak_bonus',     label: '연속 입력 보너스',  points: 0,  description: '영업일 연속 work_entry 입력 시 streak_day×0.5pt 추가 (일 최대 10pt). points 필드는 동적이므로 0으로 표시.' },
  { action_type: 'quarterly_mission',label: '분기 미션 달성',    points: 30, description: '한 분기 내 KPI×1 + SOP×1 + 이슈×3 달성 시 +30pt 일회성 보너스. is_active 로 토글 가능.' },
  { action_type: 'first_sop',        label: '첫 절차서 보너스',   points: 0,  description: '분기 첫 계리업무절차서 등록 시 +20pt (별도 적립). quarterly_mission 과 독립.' },
  { action_type: 'first_issue',      label: '첫 이슈 보너스',    points: 0,  description: '분기 첫 이슈 등록 시 +10pt (별도 적립). quarterly_mission 과 독립.' },
];

// first_sop / first_issue 는 points 필드를 0으로 두고 코드에서 고정값 사용 (동적 보너스 구조)
const FIRST_SOP_BONUS = 20;
const FIRST_ISSUE_BONUS = 10;
const STREAK_MAX_PER_DAY = 10; // streak 보너스 1회 최대

const DEFAULT_PRIZES = [
  { rank: 1, prize_amount: 300000, label: '본부장 식사권 30만원' },
  { rank: 2, prize_amount: 100000, label: '팀장 식사권 10만원' },
  { rank: 3, prize_amount: 50000,  label: '팀장 식사권 5만원'  },
];

// Phase 9: 추가 보상 기본 설정 — prize_rules 확장 시드로 저장
const DEFAULT_EXTRA_PRIZES = [
  { id: 'pz_participation', type: 'participation', min_points: 50, prize_amount: 0,   label: '참여상 (커피·간식 쿠폰)', description: '분기 50pt 이상 달성 시 전원 수여. 커피 쿠폰·간식 등 팀장 재량 선물 (금액 미지급).', is_active: true },
  { id: 'pz_growth_1',     type: 'growth',    rank: 1, prize_amount: 50000,  label: '성장상 1위 식사권 5만원', description: '직전 분기 대비 점수 증가율 TOP1', is_active: true },
  { id: 'pz_growth_2',     type: 'growth',    rank: 2, prize_amount: 30000,  label: '성장상 2위 식사권 3만원', description: '직전 분기 대비 점수 증가율 TOP2', is_active: true },
  { id: 'pz_growth_3',     type: 'growth',    rank: 3, prize_amount: 0,      label: '성장상 3위 (격려 선물)',      description: '직전 분기 대비 점수 증가율 TOP3. 격려 선물 (금액 미지급).', is_active: true },
  { id: 'pz_mvp_sop',      type: 'category_mvp', category: 'sop_create',       label: '절차서 작성 MVP (감사패)', description: '분기 계리업무절차서 작성 점수 1위. 감사패 또는 격려 선물.', is_active: true },
  { id: 'pz_mvp_issue',    type: 'category_mvp', category: 'issue_register',    label: '이슈 등록 MVP (감사패)', description: '분기 이슈 등록 점수 1위. 감사패 또는 격려 선물.', is_active: true },
  { id: 'pz_mvp_settlement',type:'category_mvp', category: 'settlement_check',  label: '결산 정확도 MVP (감사패)', description: '분기 결산 체크 점수 1위. 감사패 또는 격려 선물.', is_active: true },
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

/**
 * 이전 분기 계산. 'YYYY-Q1' → 전년도 'YYYY-1-Q4'
 */
function previousQuarter(quarter) {
  const m = /^(\d{4})-Q([1-4])$/.exec(String(quarter || ''));
  if (!m) return null;
  let y = parseInt(m[1], 10);
  let q = parseInt(m[2], 10);
  q -= 1;
  if (q < 1) { q = 4; y -= 1; }
  return `${y}-Q${q}`;
}

function seedPointsConfig(db) {
  const t = now();
  let changed = false;
  if (!Array.isArray(db.point_rules)) { db.point_rules = []; changed = true; }
  if (!Array.isArray(db.prize_rules)) { db.prize_rules = []; changed = true; }
  if (!Array.isArray(db.prize_history)) { db.prize_history = []; changed = true; }
  if (!Array.isArray(db.engagement_points)) { db.engagement_points = []; changed = true; }

  // point_rules: 기존 없으면 DEFAULT_RULES 전체 시드
  if (db.point_rules.length === 0) {
    db.point_rules = DEFAULT_RULES.map((r, i) => ({
      id: `pr_${r.action_type}`, ...r, is_active: true,
      created_at: t, updated_at: t, sort_order: i + 1,
    }));
    changed = true;
  } else {
    // 신규 룰(streak_bonus, quarterly_mission, first_sop, first_issue) 이 없으면 추가
    const existingTypes = new Set(db.point_rules.map(r => r.action_type));
    const newRules = DEFAULT_RULES.filter(r => !existingTypes.has(r.action_type));
    if (newRules.length > 0) {
      const maxOrder = Math.max(...db.point_rules.map(r => r.sort_order || 0), 0);
      newRules.forEach((r, i) => {
        db.point_rules.push({
          id: `pr_${r.action_type}`, ...r, is_active: true,
          created_at: t, updated_at: t, sort_order: maxOrder + i + 1,
        });
      });
      changed = true;
    }
  }

  // prize_rules: 기존 없으면 DEFAULT_PRIZES 시드
  if (db.prize_rules.length === 0) {
    db.prize_rules = DEFAULT_PRIZES.map(p => ({
      id: `pz_rank${p.rank}`, ...p, type: 'rank', is_active: true,
      created_at: t, updated_at: t,
    }));
    changed = true;
  }

  // extra prize_rules (Phase 9): id 기준으로 없으면 추가
  const existingPrizeIds = new Set(db.prize_rules.map(p => p.id));
  for (const ep of DEFAULT_EXTRA_PRIZES) {
    if (!existingPrizeIds.has(ep.id)) {
      db.prize_rules.push({ ...ep, created_at: t, updated_at: t });
      changed = true;
    }
  }

  // Phase 9-1 마이그레이션 (point_rules): 운영자 호칭 변경 — SOP → 계리업무절차서
  const POINT_RULE_MIGRATIONS = {
    'pr_sop_create':    { label: '절차서 작성', description: '계리업무절차서(kb_documents) 작성 1건당' },
    'pr_first_sop':     { label: '선착순 보너스 (절차서)',
                          description: '분기 내 모든 직원 중 가장 먼저 계리업무절차서 등록 시 +20pt. 해당 record 삭제 시 보너스 회수, 수정은 영향 없음.' },
    'pr_first_issue':   { label: '선착순 보너스 (이슈)',
                          description: '분기 내 모든 직원 중 가장 먼저 이슈 등록 시 +10pt. 해당 record 삭제 시 보너스 회수, 수정은 영향 없음.' },
  };
  for (const row of db.point_rules) {
    const mig = POINT_RULE_MIGRATIONS[row.id];
    if (!mig) continue;
    if (row.label !== mig.label || row.description !== mig.description) {
      row.label = mig.label;
      row.description = mig.description;
      row.updated_at = t;
      changed = true;
    }
  }

  // Phase 9-1 마이그레이션: 옛 "비금전" 라벨 → 친화 표현
  //  운영자 피드백: "비금전이 뭔뜻이야?" → 라벨 자체에서 의미 명확화
  const LABEL_MIGRATIONS = {
    'pz_rank1':          { label: '본부장 식사권 30만원',
                           description: '분기 누적 1위 시상. 본부장 명의 식사권.' },
    'pz_rank2':          { label: '팀장 식사권 10만원',
                           description: '분기 누적 2위 시상. 팀장 명의 식사권.' },
    'pz_rank3':          { label: '팀장 식사권 5만원',
                           description: '분기 누적 3위 시상. 팀장 명의 식사권.' },
    'pz_participation':  { label: '참여상 (커피·간식 쿠폰)',
                           description: '분기 50pt 이상 달성 시 전원 수여. 커피 쿠폰·간식 등 팀장 재량 선물 (금액 미지급).' },
    'pz_growth_3':       { label: '성장상 3위 (격려 선물)',
                           description: '직전 분기 대비 점수 증가율 TOP3. 격려 선물 (금액 미지급).' },
    'pz_mvp_sop':        { label: '절차서 작성 MVP (감사패)',
                           description: '분기 계리업무절차서 작성 점수 1위. 감사패 또는 격려 선물.' },
    'pz_mvp_issue':      { label: '이슈 등록 MVP (감사패)',
                           description: '분기 이슈 등록 점수 1위. 감사패 또는 격려 선물.' },
    'pz_mvp_settlement': { label: '결산 정확도 MVP (감사패)',
                           description: '분기 결산 체크 점수 1위. 감사패 또는 격려 선물.' },
  };
  for (const row of db.prize_rules) {
    const mig = LABEL_MIGRATIONS[row.id];
    if (!mig) continue;
    if (row.label !== mig.label || row.description !== mig.description) {
      row.label = mig.label;
      row.description = mig.description;
      row.updated_at = t;
      changed = true;
    }
  }

  // Phase 9-2 마이그레이션: 참여상/성장상/카테고리 MVP 운용 중단 (운영자 결정 2026-05-15)
  //  → is_active=false 로 비활성화. 1·2·3등 식사권만 운용.
  //  추후 다시 운용하고 싶으면 settings 등에서 활성화 가능.
  const DEPRECATED_PRIZE_IDS = new Set([
    'pz_participation',
    'pz_growth_1', 'pz_growth_2', 'pz_growth_3',
    'pz_mvp_sop', 'pz_mvp_issue', 'pz_mvp_settlement',
  ]);
  for (const row of db.prize_rules) {
    if (DEPRECATED_PRIZE_IDS.has(row.id) && row.is_active !== false) {
      row.is_active = false;
      row.updated_at = t;
      changed = true;
    }
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
 * @param {number} [overridePoints] — streak_bonus 등 동적 포인트 오버라이드
 * @returns {object|null}  생성된 row 또는 null
 */
function awardPoints(db, userId, memberName, actionType, actionRef, actorOpts, overridePoints) {
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
  const points = overridePoints !== undefined ? Number(overridePoints) : (Number(rule.points) || 0);
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
 * Phase 9: work_entry 적립 후 streak_bonus / quarterly_mission 추가 체크 호출.
 *
 * @param {object}  db
 * @param {string}  entryId       newly created daily_work_entries.id
 * @param {string}  userId
 * @param {string}  memberName
 * @param {string}  ymPrefix      'YYYY-MM'
 * @param {string}  taskLabel     e.task_label
 * @param {string}  taskCategory  e.task_category
 * @param {object}  actorOpts
 * @param {string}  [entryDate]   'YYYY-MM-DD' — streak 계산용
 */
function awardWorkEntryGrouped(db, entryId, userId, memberName, ymPrefix, taskLabel, taskCategory, actorOpts, entryDate) {
  if (!entryId || !memberName) return null;
  if (isTeamLeader(db, userId, memberName)) return null;
  // 이미 동일 그룹 적립이 있는지 — engagement_points 의 action_type='work_entry' 를 스캔
  const list = db.engagement_points || [];
  const groupAlreadyAwarded = list.some(p => {
    if (p.action_type !== 'work_entry') return false;
    if (p.member_name !== memberName) return false;
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

  // ── Phase 9: streak_bonus 계산 (work_entry 적립 직후) ──
  if (entryDate) {
    tryAwardStreakBonus(db, userId, memberName, entryDate, actorOpts);
  }

  // ── Phase 9: quarterly_mission 달성 체크 (work_entry 적립 직후) ──
  tryAwardQuarterlyMission(db, userId, memberName, actorOpts);

  return row;
}

// ────────────────────────────────────────────────────────────────────
// Phase 9: 연속 입력 보너스 (streak_bonus)
// ────────────────────────────────────────────────────────────────────

/**
 * 영업일 기준 연속 streak 계산 후 streak_bonus 적립.
 * streak 카운트 = 오늘 포함해 이전 N 영업일 연속 work_entry 존재.
 * 보너스 = streak × 0.5 (소수 올림), 최대 STREAK_MAX_PER_DAY pt.
 *
 * idempotency_key: streak_bonus:<memberName>:<entryDate>
 */
function tryAwardStreakBonus(db, userId, memberName, entryDate, actorOpts) {
  if (!memberName || !entryDate) return;
  if (isTeamLeader(db, userId, memberName)) return;

  // streak_bonus 룰이 비활성이면 스킵
  const rule = (db.point_rules || []).find(r => r.action_type === 'streak_bonus' && r.is_active !== false);
  if (!rule) return;

  // 중복 체크
  const ikey = `streak_bonus:${memberName}:${entryDate}`;
  if ((db.engagement_points || []).some(p => p.idempotency_key === ikey)) return;

  // work_entry 가 있는 날짜 집합 (해당 member)
  const workDates = new Set(
    (db.daily_work_entries || [])
      .filter(e => e.member_name === memberName)
      .flatMap(e => {
        try {
          const te = typeof e.time_entries === 'string' ? JSON.parse(e.time_entries) : e.time_entries;
          if (Array.isArray(te) && te.length > 0) return te.map(t => t.date).filter(Boolean);
        } catch (_) {}
        if (e.start_date) return [e.start_date];
        return [];
      })
  );

  // ── 휴가 시간 맵 (날짜별 휴가 시간(h) 합산) ──
  // 정책 (2026-05-15 운영자 결정):
  //  - 전일 휴가일: streak 끊김 방지 + 가중치 0 (연속만 유지)
  //  - 부분 휴가일에 업무 입력 시: 가중치 = (1 - 휴가분/8)
  //  - 표준 근무 8h 기준, time_entries 우선 / 없으면 start_date~end_date 를 8h씩 카운트
  const vacByDate = {};
  for (const v of (db.vacations || [])) {
    if (v.member_name !== memberName) continue;
    if (v.status === 'cancelled') continue;
    let te = v.time_entries;
    try { if (typeof te === 'string') te = JSON.parse(te); } catch (_) { te = null; }
    if (Array.isArray(te) && te.length > 0) {
      for (const t of te) {
        if (!t || !t.date) continue;
        vacByDate[t.date] = (vacByDate[t.date] || 0) + ((Number(t.minutes) || 0) / 60);
      }
    } else if (v.start_date && v.end_date) {
      // 전일 휴가 (시간대 없음) — 각 일자에 8h 누적
      const s = new Date(v.start_date + 'T00:00:00');
      const e = new Date(v.end_date + 'T00:00:00');
      while (s <= e) {
        const ds = s.toISOString().slice(0, 10);
        vacByDate[ds] = (vacByDate[ds] || 0) + 8;
        s.setDate(s.getDate() + 1);
      }
    }
  }
  const FULL_DAY_H = 8;
  const FULL_VAC_THRESHOLD = 7.5; // ≥7.5h 면 사실상 전일 휴가로 간주

  const toMs = s => new Date(s + 'T00:00:00').getTime();
  const today = toMs(entryDate);
  const DAY_MS = 86400000;

  // streak 는 가중치 누적 float (예: 풀근무 4일 + 반차 1일 = 4 + 0.5 = 4.5)
  let streak = 0;
  let check = today;
  for (let i = 0; i < 60; i++) {
    const ds = new Date(check).toISOString().slice(0, 10);
    const dow = new Date(check).getDay();
    if (dow === 0 || dow === 6) {
      check -= DAY_MS;
      continue; // 주말 skip
    }
    const vacH = vacByDate[ds] || 0;
    const isFullVac = vacH >= FULL_VAC_THRESHOLD;
    const hasWork = workDates.has(ds);

    if (isFullVac) {
      // 전일 휴가 → 연속 끊김 방지, streak 가산 없음
      check -= DAY_MS;
      continue;
    }
    if (hasWork) {
      // 업무 입력 있음 — 부분휴가시 가중치 (1 - 휴가분/8)
      const weight = Math.max(0, 1 - (vacH / FULL_DAY_H));
      streak += weight;
      check -= DAY_MS;
      continue;
    }
    if (i === 0) {
      // 오늘은 아직 work_entry 반영 전일 수 있음 → 부분휴가 가중치 적용
      streak = Math.max(0, 1 - (vacH / FULL_DAY_H));
      check -= DAY_MS;
      continue;
    }
    // 평일 + 업무 없음 + 휴가 없음 → 단절
    break;
  }

  // 정수 1일 미만이면 단순 그 날만 입력한 것 → 보너스 없음
  if (streak < 2) return;

  const bonusPts = Math.min(Math.ceil(streak * 0.5), STREAK_MAX_PER_DAY);
  if (bonusPts <= 0) return;

  const t = now();
  const row = {
    id: createId('ep'),
    user_id: userId || '',
    member_name: memberName || '',
    action_type: 'streak_bonus',
    action_ref: `${memberName}:${entryDate}`,
    points: bonusPts,
    quarter: currentQuarter(),
    awarded_at: t,
    idempotency_key: ikey,
    streak_days: Math.round(streak * 10) / 10,  // 가중치 누적이라 소수1자리
    actor_user_id: (actorOpts && actorOpts.actorId) || '',
    actor_name:    (actorOpts && actorOpts.actorName) || '',
    created_at: t,
    updated_at: t,
  };
  db.engagement_points = [...(db.engagement_points || []), row];
}

// ────────────────────────────────────────────────────────────────────
// Phase 9: 분기 미션 보너스 (quarterly_mission)
// 조건: 한 분기 내 KPI×1 + SOP×1 + 이슈×3 달성
// ────────────────────────────────────────────────────────────────────

function tryAwardQuarterlyMission(db, userId, memberName, actorOpts) {
  if (!memberName && !userId) return;
  if (isTeamLeader(db, userId, memberName)) return;

  const rule = (db.point_rules || []).find(r => r.action_type === 'quarterly_mission' && r.is_active !== false);
  if (!rule) return;

  const q = currentQuarter();
  const ikey = `quarterly_mission:${q}:${memberName || userId}`;
  if ((db.engagement_points || []).some(p => p.idempotency_key === ikey)) return; // 이미 달성

  const qList = (db.engagement_points || []).filter(p =>
    p.quarter === q &&
    ((memberName && p.member_name === memberName) || (userId && p.user_id === userId))
  );

  const kpiCount = qList.filter(p => p.action_type === 'kpi_entry').length;
  const sopCount = qList.filter(p => p.action_type === 'sop_create').length;
  const issueCount = qList.filter(p => p.action_type === 'issue_register').length;

  if (kpiCount >= 1 && sopCount >= 1 && issueCount >= 3) {
    const missionPts = Number(rule.points) || 30;
    const t = now();
    const row = {
      id: createId('ep'),
      user_id: userId || '',
      member_name: memberName || '',
      action_type: 'quarterly_mission',
      action_ref: ikey,
      points: missionPts,
      quarter: q,
      awarded_at: t,
      idempotency_key: ikey,
      actor_user_id: (actorOpts && actorOpts.actorId) || '',
      actor_name:    (actorOpts && actorOpts.actorName) || '',
      created_at: t,
      updated_at: t,
    };
    db.engagement_points = [...(db.engagement_points || []), row];
  }
}

// ────────────────────────────────────────────────────────────────────
// Phase 9: 첫 SOP / 첫 이슈 보너스
// ────────────────────────────────────────────────────────────────────

/**
 * 분기 선착순 보너스 — 모든 직원 중 가장 먼저 SOP/이슈 등록한 1명만 수여.
 *
 * 정책 (2026-05-15 운영자 결정):
 *  - "분기 전체"에서 첫 입력자만 받음 (예전: 본인 분기 첫 입력 → 변경)
 *  - 해당 record 삭제 시 보너스 회수 (cascade) — action_ref 에 record.id 저장
 *  - 수정(PATCH)은 영향 없음 (id 동일하므로 idempotency 유지)
 *
 * @param {string} recordId  방금 만들어진 kb_documents 또는 kb_issues id (cascade 키)
 */
function tryAwardFirstBonus(db, userId, memberName, actionType, actorOpts, recordId) {
  if (!memberName && !userId) return;
  if (isTeamLeader(db, userId, memberName)) return;

  const bonusType = actionType === 'sop_create' ? 'first_sop' : (actionType === 'issue_register' ? 'first_issue' : null);
  if (!bonusType) return;

  const rule = (db.point_rules || []).find(r => r.action_type === bonusType && r.is_active !== false);
  if (!rule) return;

  const q = currentQuarter();

  // 분기 전체에서 이 보너스가 이미 누군가에게 지급됐는지 확인 (전체 단 1명만)
  const alreadyAwarded = (db.engagement_points || []).some(p =>
    p.action_type === bonusType && p.quarter === q
  );
  if (alreadyAwarded) return;

  // 이 사람이 방금 추가한 적립까지 포함해 분기 전체 action_type 적립이 정확히 1건이어야 "전체 첫 입력"
  const totalThisQ = (db.engagement_points || []).filter(p =>
    p.action_type === actionType && p.quarter === q
  ).length;
  if (totalThisQ !== 1) return; // 다른 사람이 이미 등록한 적 있음 → 선착순 아님

  const bonusPts = bonusType === 'first_sop' ? FIRST_SOP_BONUS : FIRST_ISSUE_BONUS;
  const t = now();
  // action_ref 에 record.id 저장 — cascadeDeleteRelated 가 record 삭제 시 회수
  const ref = recordId || `${q}:${memberName || userId}`;
  const ikey = `${bonusType}:${q}:${ref}`;
  const row = {
    id: createId('ep'),
    user_id: userId || '',
    member_name: memberName || '',
    action_type: bonusType,
    action_ref: ref,
    points: bonusPts,
    quarter: q,
    awarded_at: t,
    idempotency_key: ikey,
    actor_user_id: (actorOpts && actorOpts.actorId) || '',
    actor_name:    (actorOpts && actorOpts.actorName) || '',
    created_at: t,
    updated_at: t,
  };
  db.engagement_points = [...(db.engagement_points || []), row];
}

/**
 * 결산 체크리스트 체크/해제 처리.
 *
 * - 체크(newDone 에 있고 beforeDone 에 없는 키) → settlement_check:<wtId>:<key> 로 적립.
 * - 해제(beforeDone 에 있고 newDone 에 없는 키) → 해당 멱등 키의 engagement_points 삭제(회수).
 * - 분기당 30건(90pt) 캡: 현재 분기에 이미 30건 이상이면 추가 적립 스킵.
 *
 * Phase 9: 체크 후 quarterly_mission 달성 여부 체크.
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

  // Phase 9: quarterly_mission 체크 (체크 추가 시)
  if (awarded.length > 0) {
    tryAwardQuarterlyMission(db, userId, memberName, actorOpts);
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
  const result = awardPoints(db, userId, memberName, actionType, ref, actorOpts);

  // Phase 9: quarterly_mission 체크 (KPI 입력 후)
  if (result) {
    tryAwardQuarterlyMission(db, userId, memberName, actorOpts);
  }
  return result;
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
  const prizes = (db.prize_rules || []).filter(p => p.is_active !== false && (!p.type || p.type === 'rank'));
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

// ────────────────────────────────────────────────────────────────────
// Phase 9: 추가 보상 — 참여상 / 성장상 / 카테고리 MVP
// ────────────────────────────────────────────────────────────────────

/**
 * 참여상: 분기 합산 포인트가 min_points 이상인 전원
 * @returns {Array<{member_name, user_id, points, prize_label}>}
 */
function getParticipationAward(db, quarter) {
  const q = quarter || currentQuarter();
  const rule = (db.prize_rules || []).find(p => p.id === 'pz_participation' && p.is_active !== false);
  if (!rule) return [];
  const minPts = Number(rule.min_points) || 50;
  const ranking = getQuarterRanking(db, q);
  return ranking
    .filter(r => r.points >= minPts)
    .map(r => ({
      member_name: r.member_name,
      user_id: r.user_id,
      points: r.points,
      prize_label: rule.label,
    }));
}

/**
 * 성장상: 직전 분기 대비 점수 증가율 TOP3
 * 직전 분기 점수가 0이면 증가율 = 현재 점수 × 100% (첫 참여 보정)
 * @returns {Array<{rank, member_name, user_id, current_points, prev_points, growth_rate, prize_label, prize_amount}>}
 */
function getGrowthAward(db, quarter) {
  const q = quarter || currentQuarter();
  const prevQ = previousQuarter(q);
  const rules = (db.prize_rules || []).filter(p => p.type === 'growth' && p.is_active !== false);
  if (rules.length === 0) return [];

  const curRanking = getQuarterRanking(db, q);
  const prevRanking = prevQ ? getQuarterRanking(db, prevQ) : [];
  const prevByName = {};
  for (const r of prevRanking) prevByName[r.member_name] = r.points;

  const withGrowth = curRanking.map(r => {
    const prev = prevByName[r.member_name] || 0;
    const growthRate = prev === 0 ? (r.points > 0 ? 100 : 0) : Math.round(((r.points - prev) / prev) * 100);
    return { ...r, prev_points: prev, growth_rate: growthRate };
  })
  .filter(r => r.growth_rate > 0)
  .sort((a, b) => b.growth_rate - a.growth_rate || b.points - a.points);

  const prizeByRank = {};
  for (const r of rules) prizeByRank[r.rank] = r;

  return withGrowth.slice(0, 3).map((r, i) => {
    const rk = i + 1;
    const pz = prizeByRank[rk];
    return {
      rank: rk,
      member_name: r.member_name,
      user_id: r.user_id,
      current_points: r.points,
      prev_points: r.prev_points,
      growth_rate: r.growth_rate,
      prize_label: pz ? pz.label : `성장상 ${rk}위`,
      prize_amount: pz ? (pz.prize_amount || 0) : 0,
    };
  });
}

/**
 * 카테고리 MVP: SOP / 이슈 / 결산 별 해당 action_type 점수 1위
 * @returns {Array<{category, member_name, user_id, points, prize_label}>}
 */
function getCategoryMvp(db, quarter) {
  const q = quarter || currentQuarter();
  const mvpRules = (db.prize_rules || []).filter(p => p.type === 'category_mvp' && p.is_active !== false);
  if (mvpRules.length === 0) return [];

  const users = db.users || [];
  const tlNames = new Set(users.filter(u => u.role === 'team_leader').map(u => u.full_name || u.username));
  const tlIds = new Set(users.filter(u => u.role === 'team_leader').map(u => u.id));

  const qList = (db.engagement_points || []).filter(p => {
    if (p.quarter !== q) return false;
    if (tlIds.has(p.user_id)) return false;
    if (tlNames.has(p.member_name)) return false;
    return true;
  });

  return mvpRules.map(rule => {
    const catPoints = {};
    for (const p of qList.filter(p => p.action_type === rule.category)) {
      const key = p.member_name || p.user_id || 'unknown';
      if (!catPoints[key]) catPoints[key] = { member_name: p.member_name || '', user_id: p.user_id || '', points: 0 };
      catPoints[key].points += Number(p.points) || 0;
    }
    const sorted = Object.values(catPoints).sort((a, b) => b.points - a.points);
    if (sorted.length === 0) return null;
    const winner = sorted[0];
    return {
      category: rule.category,
      prize_rule_id: rule.id,
      prize_label: rule.label,
      member_name: winner.member_name,
      user_id: winner.user_id,
      points: winner.points,
    };
  }).filter(Boolean);
}

/**
 * 분기 시상 확정 — prize_history 에 멱등 INSERT
 * Phase 9: 기본 top3 + 참여상 + 성장상 + MVP 도 함께 기록
 */
function finalizeQuarter(db, quarter) {
  const q = quarter || currentQuarter();
  const list = db.prize_history || [];
  const existed = list.filter(h => h.quarter === q);
  if (existed.length > 0) {
    return { quarter: q, already_finalized: true, entries: existed };
  }
  const { top3 } = top3WithPrizes(db, q);
  const participation = getParticipationAward(db, q);
  const growth = getGrowthAward(db, q);
  const mvp = getCategoryMvp(db, q);
  const t = now();

  const created = [];
  // 기본 랭킹 1~3
  for (const w of top3) {
    created.push({
      id: createId('pzh'),
      quarter: q,
      award_type: 'rank',
      rank: w.rank,
      user_id: w.user_id,
      member_name: w.member_name,
      points: w.points,
      prize_amount: w.prize_amount,
      prize_label: w.prize_label,
      awarded_at: t,
      created_at: t,
      updated_at: t,
    });
  }
  // 참여상
  for (const w of participation) {
    created.push({
      id: createId('pzh'),
      quarter: q,
      award_type: 'participation',
      rank: null,
      user_id: w.user_id,
      member_name: w.member_name,
      points: w.points,
      prize_amount: 0,
      prize_label: w.prize_label,
      awarded_at: t,
      created_at: t,
      updated_at: t,
    });
  }
  // 성장상
  for (const w of growth) {
    created.push({
      id: createId('pzh'),
      quarter: q,
      award_type: 'growth',
      rank: w.rank,
      user_id: w.user_id,
      member_name: w.member_name,
      points: w.current_points,
      prev_points: w.prev_points,
      growth_rate: w.growth_rate,
      prize_amount: w.prize_amount,
      prize_label: w.prize_label,
      awarded_at: t,
      created_at: t,
      updated_at: t,
    });
  }
  // 카테고리 MVP
  for (const w of mvp) {
    created.push({
      id: createId('pzh'),
      quarter: q,
      award_type: 'category_mvp',
      rank: null,
      category: w.category,
      user_id: w.user_id,
      member_name: w.member_name,
      points: w.points,
      prize_amount: 0,
      prize_label: w.prize_label,
      awarded_at: t,
      created_at: t,
      updated_at: t,
    });
  }

  db.prize_history = [...list, ...created];
  return { quarter: q, already_finalized: false, entries: created };
}

/**
 * 전체 보상 현황 (top3 + 참여상 + 성장상 + MVP) 조회
 */
function getAllAwards(db, quarter) {
  const q = quarter || currentQuarter();
  return {
    quarter: q,
    top3: top3WithPrizes(db, q),
    participation: getParticipationAward(db, q),
    growth: getGrowthAward(db, q),
    category_mvp: getCategoryMvp(db, q),
    total_participants: getQuarterRanking(db, q).length,
  };
}

module.exports = {
  DEFAULT_RULES,
  DEFAULT_PRIZES,
  DEFAULT_EXTRA_PRIZES,
  FIRST_SOP_BONUS,
  FIRST_ISSUE_BONUS,
  STREAK_MAX_PER_DAY,
  seedPointsConfig,
  currentQuarter,
  previousQuarter,
  quarterRange,
  awardPoints,
  awardPointsOncePerQuarter,
  awardWorkEntryGrouped,
  syncSettlementCheckPoints,
  tryAwardFirstBonus,
  tryAwardStreakBonus,
  tryAwardQuarterlyMission,
  getQuarterRanking,
  top3WithPrizes,
  getParticipationAward,
  getGrowthAward,
  getCategoryMvp,
  getAllAwards,
  finalizeQuarter,
};
