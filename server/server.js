'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFile } = require('child_process');
const bizday = require('./lib/bizday');
const workload = require('./lib/workload');
const timeentry = require('./lib/timeentry');
const points = require('./lib/points');
const { runAudit } = require('./audit');
const { applyAutoFix } = require('./audit-autofix');

// .env 로드 (dotenv 없이 직접 파싱)
function loadEnv() {
  const envPath = path.join(__dirname, '.env');
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, 'utf8').split('\n');
  for (const line of lines) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;
    const idx = t.indexOf('=');
    if (idx === -1) continue;
    const key = t.slice(0, idx).trim();
    const val = t.slice(idx + 1).trim().replace(/^["']|["']$/g, '');
    if (key && process.env[key] === undefined) process.env[key] = val;
  }
}
loadEnv();

const PORT = parseInt(process.env.PORT || '8888', 10);
const HOST = process.env.HOST || '0.0.0.0';
const ROOT = path.resolve(__dirname, '..');
const DATA_PATH = path.join(__dirname, 'data', 'portal-db.json');

const PASSWORD_SHA256 = crypto.createHash('sha256').update('password').digest('hex');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'text/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.ico':  'image/x-icon',
  '.png':  'image/png',
  '.jpg':  'image/jpeg',
  '.svg':  'image/svg+xml',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.woff2':'font/woff2'
};

function now() { return Date.now(); }

function isoOf(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

function createId(table) {
  return `${table.slice(0, 3)}_${crypto.randomBytes(8).toString('hex')}`;
}

function createInitialDatabase() {
  const t = now();
  return {
    users: [
      {
        id: 'u_teamleader1',
        username: 'teamleader1',
        password_hash: PASSWORD_SHA256,
        full_name: '김팀장',
        role: 'team_leader',
        department: '계리결산팀',
        is_active: true,
        created_at: t,
        updated_at: t
      },
      {
        id: 'u_sectionchief1',
        username: 'sectionchief1',
        password_hash: PASSWORD_SHA256,
        full_name: '이실장',
        role: 'section_chief',
        department: '계리결산실',
        is_active: true,
        created_at: t,
        updated_at: t
      }
    ],
    sessions: [],
    team_identity: [
      {
        id: 'default',
        mission: '계리결산팀은 정확하고 안정적인 결산 수행을 기반으로, 재무수치 분석과 AI 활용 역량을 강화하여 회사의 재무건전성 관리, 리스크 조기 식별, 경영진 의사결정 지원에 기여한다.',
        vision: '',
        updated_at: t,
        updated_by: 'u_teamleader1'
      }
    ],
    core_values: [
      {
        id: 'cv_1',
        title: '책임 있게 완수한다',
        description: '맡은 업무를 기한 내 완수하고 문제가 발생하면 즉시 공유하며 끝까지 해결한다.',
        order: 1,
        icon: 'fa-shield-alt',
        color: 'blue',
        created_at: t,
        updated_at: t
      },
      {
        id: 'cv_2',
        title: '정확하게 검증한다',
        description: '숫자의 차이를 그냥 넘기지 않고 원인을 확인하여 설명 가능한 재무수치를 만든다.',
        order: 2,
        icon: 'fa-search',
        color: 'green',
        created_at: t,
        updated_at: t
      },
      {
        id: 'cv_3',
        title: '배우고 적용한다',
        description: '새로운 기준, 제도, AI 기술을 배우고 모르는 것은 질문하며 업무에 적용한다.',
        order: 3,
        icon: 'fa-graduation-cap',
        color: 'yellow',
        created_at: t,
        updated_at: t
      },
      {
        id: 'cv_4',
        title: '더 나은 방식을 만든다',
        description: '반복되는 수작업과 오류 가능성을 줄이기 위해 업무를 표준화하고 자동화한다.',
        order: 4,
        icon: 'fa-cogs',
        color: 'purple',
        created_at: t,
        updated_at: t
      },
      {
        id: 'cv_5',
        title: '솔직하게 소통한다',
        description: '어려운 대화를 피하지 않고 사실과 근거를 바탕으로 솔직하게 협의한다.',
        order: 5,
        icon: 'fa-comments',
        color: 'red',
        created_at: t,
        updated_at: t
      }
    ],
    team_goals: [],
    individual_goals: [],
    performance_records: [],
    work_tasks: [],
    settlement_calendar: [],
    automation_logs: [],
    report_history: [],
    interview_logs: [],
    audit_logs: []
  };
}

let writeChain = Promise.resolve();

function migrateDb(db) {
  const t = now();
  let changed = false;
  const requiredTables = [
    'users','sessions','team_identity','core_values','team_goals',
    'individual_goals','performance_records','work_tasks','settlement_calendar',
    'automation_logs','report_history','interview_logs','audit_logs',
    'settlement_reviews','team_directives',
    'settle_items','score_rules','kpi_definitions','task_categories',
    // ── Phase 1: 업무량 모니터링 ──
    'business_days','business_days_monthly','daily_work_entries',
    'workload_daily_cache','workload_thresholds',
    // ── Phase 4: 지식관리 (KB) ──
    'kb_categories','kb_documents','kb_document_versions','kb_issues',
    'kb_handovers','kb_handover_items',
    'kb_onboarding_tracks','kb_onboarding_milestones',
    // ── Phase 6: 이슈 카테고리 SSOT ──
    'issue_categories',
    // ── Phase 8: 휴가 + 게이미피케이션 ──
    'vacations', 'vacation_quotas',
    'engagement_points', 'point_rules', 'prize_rules', 'prize_history',
  ];
  for (const table of requiredTables) {
    if (!Array.isArray(db[table])) {
      db[table] = [];
      changed = true;
    }
  }
  if (!db.team_identity.length) {
    db.team_identity.push({
      id: 'default',
      mission: '팀 미션을 입력해주세요.',
      vision: '',
      updated_at: t,
      updated_by: ''
    });
    changed = true;
  }
  // settle_items 초기 시드 (26개 결산업무)
  if (!db.settle_items.length) {
    const seed = [
      ['s01','계리계약 마감','계약/준비금',5,'오정택'],
      ['s02','지급준비금 마감','계약/준비금',7,'이용우'],
      ['s03','준비금 마감','계약/준비금',8,'강세진'],
      ['s04','보험료분해 마감','계약/준비금',10,'김채린'],
      ['s05','재보험 마감 (출재/청구)','계약/준비금',12,'김예은'],
      ['s06','보증준비금 마감','계약/준비금',13,'강세진'],
      ['s07','잉여금처리 & 계약자배당','계약/준비금',null,'이상현'],
      ['s08','예금보험료','계약/준비금',null,'강세진'],
      ['s09','결산 모델 배포','모델/가정',1,'한인석'],
      ['s10','계리모델 입력데이터 준비','모델/가정',8,'김예은/이성원'],
      ['s11','경제적 가정 산출','모델/가정',7,'이상백'],
      ['s12','최초/후속 모델포인트 생성','모델/가정',9,'이성원'],
      ['s13','최초인식 보험부채 산출','부채산출',9,'김예은'],
      ['s14','후속측정 보험부채 산출','부채산출',12,'한인석/이성원'],
      ['s15','사업비 배부','부채산출',12,'마혜원'],
      ['s16','최초인식대상계약 확정','부채산출',9,'이용우'],
      ['s17','결산대상계약 확정','부채산출',10,'이용우'],
      ['s18','가중평균할인율 산출','부채산출',10,'예대호'],
      ['s19','BEL/RA data 입수 및 계약그룹 작업','ETL/데이터',12,'이동민'],
      ['s20','결산대상계약 및 실제CF 이관 (ETL)','ETL/데이터',12,'김예은'],
      ['s21','실제CF Data 이관 (ETL)','ETL/데이터',13,'이동민'],
      ['s22','가중평균할인율 산출 (재보험)','재보험',14,'예대호'],
      ['s23','BEL/RA data 입수 (재보험)','재보험',15,'김예은'],
      ['s24','부채결산 무브먼트','무브먼트/전송',15,'이동민'],
      ['s25','부채결산 무브먼트 (재보험)','무브먼트/전송',15,'김예은'],
      ['s26','회계팀 결산Data 전송','무브먼트/전송',15,'예대호'],
    ];
    db.settle_items = seed.map((r, i) => ({
      id: r[0], seq: i + 1, label: r[1], group_name: r[2],
      due_biz_day: r[3], assignee: r[4], is_active: true,
      created_at: t, updated_at: t
    }));
    changed = true;
  }
  // score_rules 초기 시드 (기한준수 점수 6단계)
  if (!db.score_rules.length) {
    const rules = [
      ['deadline', 2, 100, 'D-2 이상 조기완료'],
      ['deadline', 1, 90,  'D-1 조기완료'],
      ['deadline', 0, 80,  '기한 정시'],
      ['deadline', -1, 70, 'D+1 지연'],
      ['deadline', -2, 60, 'D+2 지연'],
      ['deadline', -99, 0, 'D+3 이상 지연'],
      ['csm', 1000, 100, '10억원 이상'],
      ['csm', 500,  90,  '5억원 이상'],
      ['csm', 200,  80,  '2억원 이상'],
      ['csm', 100,  70,  '1억원 이상'],
      ['csm', 0,    0,   '미달'],
      ['directive', 1, 100, '수행'],
      ['directive', 0, 0,   '미수행'],
      ['meeting', 1, 100, '1회 이상'],
      ['meeting', 0, 0,   '미수행'],
    ];
    db.score_rules = rules.map((r, i) => ({
      id: `sr_${i + 1}`, rule_type: r[0], threshold: r[1], score: r[2], label: r[3],
      created_at: t, updated_at: t
    }));
    changed = true;
  }
  // kpi_definitions 초기 시드 (KPI 1~3 + 정량 가중치)
  if (!db.kpi_definitions.length) {
    const year = new Date().getFullYear();
    const items = [
      ['kpi1',  '계리모델AI활용', 20, 'qual'],
      ['kpi2',  '재무수치분석',   20, 'qual'],
      ['kpi3',  '계리지원강화',   10, 'qual'],
      ['directive', '지시수행',   5,  'quant'],
      ['csm',       '재무수치안', 10, 'quant'],
      ['deadline',  '기한준수',   20, 'quant'],
      ['meeting',   '임원회의',   15, 'quant'],
    ];
    db.kpi_definitions = items.map((r, i) => ({
      id: `kpi_${year}_${r[0]}`, year, code: r[0],
      label: r[1], weight_pct: r[2], category: r[3], is_active: true,
      created_at: t, updated_at: t
    }));
    changed = true;
  }
  // task_categories 초기 시드 (work-personal 카테고리)
  if (!db.task_categories.length) {
    const cats = ['보고서 작성','회의/협의','데이터 분석','시스템 작업',
      'KPI1 관련','KPI2 관련','KPI3 관련','교육/연수',
      '프로젝트','타부서업무협조','금감원CPC','예보산출','내부통제','외부감사','기타'];
    db.task_categories = cats.map((label, i) => ({
      id: `tc_${i + 1}`, label, sort_order: i + 1, is_active: true,
      created_at: t, updated_at: t
    }));
    changed = true;
  }
  // 기존 score_rules의 deadline_perf → deadline 으로 통일 (kpi_definitions code와 일치)
  if (Array.isArray(db.score_rules)) {
    for (const r of db.score_rules) {
      if (r.rule_type === 'deadline_perf') {
        r.rule_type = 'deadline';
        changed = true;
      }
    }
  }
  // ── Phase 1: business_days 시드 (한국 법정공휴일 2025~2027 하드코딩) ──
  if (!db.business_days.length) {
    const HOLIDAYS = [
      // 2025
      ['2025-01-01','신정'],
      ['2025-01-28','설날연휴'],['2025-01-29','설날'],['2025-01-30','설날연휴'],
      ['2025-03-01','삼일절'],
      ['2025-05-01','근로자의날'],
      ['2025-05-05','어린이날'],['2025-05-06','대체공휴일'],
      ['2025-06-06','현충일'],
      ['2025-08-15','광복절'],
      ['2025-10-03','개천절'],
      ['2025-10-05','추석연휴'],['2025-10-06','추석'],['2025-10-07','추석연휴'],['2025-10-08','추석대체'],
      ['2025-10-09','한글날'],
      ['2025-12-25','크리스마스'],
      // 2026
      ['2026-01-01','신정'],
      ['2026-02-16','설날연휴'],['2026-02-17','설날'],['2026-02-18','설날연휴'],
      ['2026-03-01','삼일절'],['2026-03-02','삼일절대체'],
      ['2026-05-01','근로자의날'],
      ['2026-05-05','어린이날'],
      ['2026-05-24','석가탄신일'],['2026-05-25','석가탄신일대체'],
      ['2026-06-06','현충일'],
      ['2026-08-15','광복절'],
      ['2026-09-24','추석연휴'],['2026-09-25','추석'],['2026-09-26','추석연휴'],['2026-09-28','추석대체'],
      ['2026-10-03','개천절'],
      ['2026-10-09','한글날'],
      ['2026-12-25','크리스마스'],
      // 2027
      ['2027-01-01','신정'],
      ['2027-01-25','설날연휴'],['2027-01-26','설날'],['2027-01-27','설날연휴'],
      ['2027-03-01','삼일절'],
      ['2027-05-01','근로자의날'],
      ['2027-05-05','어린이날'],
      ['2027-05-13','석가탄신일'],
      ['2027-06-06','현충일'],['2027-06-07','현충일대체'],
      ['2027-08-15','광복절'],['2027-08-16','광복절대체'],
      ['2027-10-03','개천절'],['2027-10-04','개천절대체'],
      ['2027-10-09','한글날'],
      ['2027-10-14','추석연휴'],['2027-10-15','추석'],['2027-10-16','추석연휴'],['2027-10-18','추석대체'],
      ['2027-12-25','크리스마스'],
    ];
    db.business_days = HOLIDAYS.map(([date, name]) => ({
      id: `bd_${date}`,
      calendar_date: date,
      is_business_day: false,
      day_type: 'public_holiday',
      holiday_name: name,
      note: '',
      updated_by: 'system',
      created_at: t,
      updated_at: t,
    }));
    changed = true;
  }
  // ── Phase 1: 월별 영업일 캐시 (2025~2027) ──
  if (!db.business_days_monthly.length) {
    const bizMap = bizday.indexBusinessDays(db.business_days);
    db.business_days_monthly = bizday.buildMonthlyCacheRange(2025, 2027, bizMap)
      .map(r => ({ ...r, created_at: t, updated_at: t }));
    changed = true;
  }
  // ── Phase 1: 부하율 임계값 (단일 행 config) ──
  if (!db.workload_thresholds.length) {
    db.workload_thresholds = [{
      id: 'default',
      hours_per_day: bizday.HOURS_PER_DAY,
      overload_pct: 120,         // 일 부하율 > 120% → 과중
      idle_pct: 70,              // 일 부하율 < 70% → 유휴
      overload_consec_days: 3,   // 영업일 연속 N일 시 과중 플래그
      idle_consec_days: 5,       // 영업일 연속 N일 시 유휴 플래그
      created_at: t,
      updated_at: t,
    }];
    changed = true;
  }
  // ── Phase 6: 이슈 카테고리 시드 ──
  if (!db.issue_categories.length) {
    const cats = [
      ['ic_system',     '시스템'],
      ['ic_accounting', '회계'],
      ['ic_regulation', '규정'],
      ['ic_data',       '데이터'],
      ['ic_etc',        '기타'],
    ];
    db.issue_categories = cats.map(([id, label], i) => ({
      id, label, sort_order: i + 1, is_active: true,
      created_at: t, updated_at: t,
    }));
    changed = true;
  }
  // ── Phase 8: 포인트/상금 룰 시드 ──
  if (points.seedPointsConfig(db)) {
    changed = true;
  }
  // ── Phase 4: KB 카테고리 시드 (계층) ──
  if (!db.kb_categories.length) {
    const cats = [
      { id:'kbc_settlement', name:'결산',       parent_id:null, display_order:1 },
      { id:'kbc_settle_monthly', name:'월결산', parent_id:'kbc_settlement', display_order:1 },
      { id:'kbc_settle_quarterly', name:'분기결산', parent_id:'kbc_settlement', display_order:2 },
      { id:'kbc_settle_year', name:'연결산',   parent_id:'kbc_settlement', display_order:3 },
      { id:'kbc_validation', name:'검증·리뷰', parent_id:null, display_order:2 },
      { id:'kbc_reporting',  name:'보고서·산출물', parent_id:null, display_order:3 },
      { id:'kbc_automation', name:'자동화·시스템', parent_id:null, display_order:4 },
      { id:'kbc_regulation', name:'규정·기준', parent_id:null, display_order:5 },
      { id:'kbc_etc',        name:'기타',     parent_id:null, display_order:99 },
    ];
    db.kb_categories = cats.map(c => ({ ...c, created_at: t, updated_at: t }));
    changed = true;
  }
  // ── Phase 2: 기존 work_tasks → daily_work_entries 자동 변환 (한 번만) ──
  if (!db._meta) db._meta = {};
  if (!db._meta.migrated_work_tasks_to_daily) {
    let inserted = 0;
    for (const wt of (db.work_tasks || [])) {
      const member = wt.member_name;
      if (!member) continue;
      const dates = wt.settlement_dates || {};
      const times = wt.settlement_times || {};
      // 결산 항목별 일자/소요시간 → 일별 엔트리
      for (const [settleId, dateStr] of Object.entries(dates)) {
        if (!dateStr) continue;
        const minutes = Number(times[settleId]) || 0;
        if (minutes <= 0) continue;
        const settleItem = (db.settle_items || []).find(s => s.id === settleId);
        const label = settleItem ? settleItem.label : settleId;
        db.daily_work_entries.push({
          id: `dwe_settle_${member}_${settleId}_${dateStr}`,
          user_id: null,
          member_name: member,
          work_date: dateStr,
          task_category_id: null,
          task_label: label,
          duration_minutes: minutes,
          source: 'settlement_auto',
          settle_item_id: settleId,
          note: '결산 체크리스트에서 자동 변환',
          created_at: t,
          updated_at: t,
        });
        inserted++;
      }
    }
    db._meta.migrated_work_tasks_to_daily = { at: t, inserted };
    if (inserted > 0) changed = true;
  }
  // ── Phase 7-1: 기존 daily_work_entries에 time_entries 시간대 분산 (한 번만) ──
  if (!db._meta.migrated_to_time_entries_v1) {
    const bizMap = bizday.indexBusinessDays(db.business_days);
    let migrated = 0;
    for (const e of (db.daily_work_entries || [])) {
      // 이미 time_entries 있으면 스킵 (멱등성)
      if (Array.isArray(e.time_entries) && e.time_entries.length > 0) continue;
      const total = Number(e.duration_minutes) || 0;
      if (total <= 0 || !e.work_date) continue;
      // 시간대 분산: 종료일 = work_date, 18:00 기준 역산
      const segs = timeentry.spreadMinutesAcrossBusinessDays(total, e.work_date, bizMap);
      const summary = timeentry.summarize(segs);
      e.time_entries = segs;
      e.total_minutes = summary.total_minutes;
      e.start_date = summary.start_date;
      e.end_date = summary.end_date;
      e.time_entry_mode = summary.time_entry_mode;
      e.is_estimated = true; // 추정 라벨
      e.updated_at = t;
      migrated++;
    }
    db._meta.migrated_to_time_entries_v1 = { at: t, migrated };
    if (migrated > 0) changed = true;
  }
  if (changed) writeDb(db);
}

function readDb() {
  if (!fs.existsSync(DATA_PATH)) {
    const db = createInitialDatabase();
    fs.mkdirSync(path.dirname(DATA_PATH), { recursive: true });
    fs.writeFileSync(DATA_PATH, JSON.stringify(db, null, 2), 'utf8');
    return db;
  }
  const db = JSON.parse(fs.readFileSync(DATA_PATH, 'utf8'));
  migrateDb(db);
  return db;
}

function writeDb(db) {
  fs.mkdirSync(path.dirname(DATA_PATH), { recursive: true });
  fs.writeFileSync(DATA_PATH, JSON.stringify(db, null, 2), 'utf8');
}

function withDb(fn) {
  const job = writeChain.then(() => {
    const db = readDb();
    return fn(db);
  });
  writeChain = job.catch(console.error);
  return job;
}

function parseTablesRoute(reqUrl) {
  const u = new URL(reqUrl, 'http://internal');
  const match = u.pathname.match(/\/tables\/([^/]+)(?:\/([^/?#]+))?/);
  if (!match) return null;
  return {
    table: match[1],
    id: match[2] ? decodeURIComponent(match[2]) : null,
    searchParams: u.searchParams
  };
}

function applySearch(items, q) {
  if (!q) return items;
  const term = q.toLowerCase();
  return items.filter(item =>
    Object.values(item).some(v => String(v ?? '').toLowerCase().includes(term))
  );
}

function applySort(items, field) {
  if (!field) return items;
  return [...items].sort((a, b) => {
    const av = a[field] ?? 0;
    const bv = b[field] ?? 0;
    return bv > av ? 1 : bv < av ? -1 : 0;
  });
}

function applyPaging(items, page, limit) {
  const p = Math.max(1, Number(page || 1));
  const l = Math.max(1, Number(limit || 100));
  return items.slice((p - 1) * l, p * l);
}

// 감사 로그 대상 외 (자동 캐시/시스템 테이블)
const AUDIT_SKIP_TABLES = new Set([
  'audit_logs', 'sessions',
  'workload_daily_cache', 'business_days_monthly', 'kb_document_versions',
  'automation_logs', 'report_history',
  'audit_reports',  // 자동 점검 결과는 시스템 테이블 — 일반 audit_logs에 기록 안 함
]);
function appendAuditLog(db, table, action, route, before, after, reqHeaders) {
  if (AUDIT_SKIP_TABLES.has(table)) return;
  // 헤더 X-Actor-User / X-Actor-Username (클라이언트가 RBAC 세션에서 채워서 보냄)
  const actorId = (reqHeaders && reqHeaders['x-actor-user']) || '';
  let actorName = (reqHeaders && reqHeaders['x-actor-username']) || '';
  try { actorName = decodeURIComponent(actorName); } catch (_) { /* leave as-is */ }
  const actorRole = (reqHeaders && reqHeaders['x-actor-role']) || '';
  // 변경 요약
  let detail = `${table} ${action}`;
  const targetId = after?.id || before?.id || route?.id || '';
  if (targetId) detail += ` id=${targetId}`;
  // 주요 필드 (있는 경우만)
  const labelFields = ['title', 'label', 'name', 'member_name', 'target_name', 'task_label', 'holiday_name'];
  for (const f of labelFields) {
    if (after && after[f]) { detail += ` ${f}="${String(after[f]).slice(0, 60)}"`; break; }
    if (before && before[f]) { detail += ` ${f}="${String(before[f]).slice(0, 60)}"`; break; }
  }
  db.audit_logs = db.audit_logs || [];
  db.audit_logs.push({
    id: createId('aud'),
    user_id: actorId, username: actorName, role: actorRole,
    action: `${action}:${table}`,
    result: 'allowed',
    detail,
    created_at: now(), updated_at: now(),
  });
  // audit_logs는 무한 누적 방지: 최근 5000건만 보관
  const MAX_LOG = 5000;
  if (db.audit_logs.length > MAX_LOG) {
    db.audit_logs = db.audit_logs.slice(-MAX_LOG);
  }
}

// daily_work_entries POST/PUT 시 time_entries 자동 보정
// 입력 우선순위:
//  1) body.time_entries 직접 전달
//  2) body.start_date/end_date + body.start_time/end_time
//  3) body.work_date + body.duration_minutes (legacy 자동분산)
function normalizeTimeEntries(db, body) {
  const bizMap = bizday.indexBusinessDays(db.business_days);
  let entries = null;
  if (Array.isArray(body.time_entries) && body.time_entries.length > 0) {
    // minutes는 항상 점심 차감하여 재계산 (클라이언트가 보낸 값 신뢰 X — 표준 8h 정책)
    entries = body.time_entries.map(e => ({
      date: e.date,
      start: e.start,
      end: e.end,
      minutes: timeentry.netMinutesInRange(
        timeentry.timeToMin(e.start), timeentry.timeToMin(e.end)
      ),
    }));
  } else if (body.start_date && body.end_date && body.start_time && body.end_time) {
    entries = timeentry.buildEntriesFromRange(
      body.start_date, body.end_date, body.start_time, body.end_time
    );
  } else if (body.work_date && Number(body.duration_minutes) > 0) {
    entries = timeentry.spreadMinutesAcrossBusinessDays(
      Number(body.duration_minutes), body.work_date, bizMap
    );
  }
  if (!entries) return body;
  const summary = timeentry.summarize(entries);
  return {
    ...body,
    time_entries: entries,
    total_minutes: summary.total_minutes,
    start_date: summary.start_date,
    end_date: summary.end_date,
    time_entry_mode: summary.time_entry_mode,
    work_date: summary.end_date,            // 호환성 (deprecated)
    duration_minutes: summary.total_minutes, // 호환성 (deprecated)
  };
}

// daily_work_entries 캐시 갱신: time_entries의 모든 일자
function refreshDailyCacheFor(db, entry) {
  if (!entry || !entry.member_name) return;
  const dates = new Set();
  if (Array.isArray(entry.time_entries)) {
    entry.time_entries.forEach(e => e.date && dates.add(e.date));
  } else if (entry.work_date) {
    dates.add(entry.work_date);
  }
  for (const d of dates) {
    workload.upsertCacheRow(db, entry.member_name, d);
  }
}

// business_days 변경 시 영향 받는 연도를 캐시 재계산
function recomputeMonthlyCache(db, affectedYears) {
  const bizMap = bizday.indexBusinessDays(db.business_days);
  const years = affectedYears && affectedYears.length
    ? Array.from(new Set(affectedYears)).sort()
    : [2025, 2026, 2027];
  const minY = years[0], maxY = years[years.length - 1];
  const fresh = bizday.buildMonthlyCacheRange(minY, maxY, bizMap);
  const freshIds = new Set(fresh.map(r => r.id));
  // 영향 범위 외는 보존, 영향 범위 내는 새 값으로 교체
  const kept = (db.business_days_monthly || []).filter(r => !freshIds.has(r.id));
  db.business_days_monthly = [...kept, ...fresh.map(r => ({ ...r, updated_at: now() }))];
}

// ── Phase 8: 휴가 한도 동기화 ──
const DEFAULT_ANNUAL_QUOTA = 15;

function getOrCreateQuota(db, year, userId, memberName) {
  if (!Array.isArray(db.vacation_quotas)) db.vacation_quotas = [];
  let q = db.vacation_quotas.find(x =>
    x.year === year &&
    ((userId && x.user_id === userId) || (memberName && x.member_name === memberName))
  );
  if (!q) {
    q = {
      id: createId('vq'),
      year, user_id: userId || '',
      member_name: memberName || '',
      annual_total: DEFAULT_ANNUAL_QUOTA,
      used: 0,
      remaining: DEFAULT_ANNUAL_QUOTA,
      created_at: now(), updated_at: now(),
    };
    db.vacation_quotas.push(q);
  }
  return q;
}

function recomputeQuotaForYear(db, year, userId, memberName) {
  const q = getOrCreateQuota(db, year, userId, memberName);
  const usedSum = (db.vacations || [])
    .filter(v => v && (v.status === 'approved' || !v.status))
    .filter(v => {
      const matchUser = userId && v.user_id === userId;
      const matchName = memberName && v.member_name === memberName;
      return matchUser || matchName;
    })
    .filter(v => v.start_date && v.start_date.slice(0, 4) === String(year))
    .reduce((s, v) => s + (Number(v.days) || 0), 0);
  q.used = Math.round(usedSum * 10) / 10;
  q.remaining = Math.round((q.annual_total - q.used) * 10) / 10;
  q.updated_at = now();
  return q;
}

function syncVacationQuotaOnCreate(db, vacation) {
  if (!vacation || !vacation.start_date) return;
  const y = parseInt(vacation.start_date.slice(0, 4), 10);
  if (!Number.isFinite(y)) return;
  recomputeQuotaForYear(db, y, vacation.user_id, vacation.member_name);
}

function syncVacationQuotaOnUpdate(db, before, updated) {
  const years = new Set();
  if (before && before.start_date) years.add(parseInt(before.start_date.slice(0, 4), 10));
  if (updated && updated.start_date) years.add(parseInt(updated.start_date.slice(0, 4), 10));
  for (const y of years) {
    if (!Number.isFinite(y)) continue;
    recomputeQuotaForYear(db, y,
      updated.user_id || before.user_id,
      updated.member_name || before.member_name);
  }
}

/**
 * 단건 DELETE 시 자식/적립 데이터 좀비 방지.
 *  - daily_work_entries / kb_issues / kb_documents 삭제 → engagement_points 해당 적립 행 제거
 *  - kb_documents 삭제 → kb_document_versions / kb_attachments(parent_id 매칭) 제거
 *  - kb_issues   삭제 → kb_attachments(parent_id 매칭) 제거
 */
function cascadeDeleteRelated(db, table, removed) {
  if (!removed || !removed.id) return;
  const POINTS_ACTION_BY_TABLE = {
    daily_work_entries: 'work_entry',
    kb_issues: 'issue_register',
    kb_documents: 'sop_create',
  };
  const action = POINTS_ACTION_BY_TABLE[table];
  if (action && Array.isArray(db.engagement_points)) {
    const key = `${action}:${removed.id}`;
    db.engagement_points = db.engagement_points.filter(p => p.idempotency_key !== key);
  }
  // Phase 9: 선착순 보너스(first_sop / first_issue) 도 record 삭제 시 회수
  //   tryAwardFirstBonus 가 action_ref 에 record.id 를 저장하므로 정확 매칭으로 정리.
  //   이후 분기 내에 같은 action_type 입력이 또 들어오면 그 사람에게 보너스 재발급.
  if (table === 'kb_documents' && Array.isArray(db.engagement_points)) {
    db.engagement_points = db.engagement_points.filter(p =>
      !(p.action_type === 'first_sop' && p.action_ref === removed.id));
  }
  if (table === 'kb_issues' && Array.isArray(db.engagement_points)) {
    db.engagement_points = db.engagement_points.filter(p =>
      !(p.action_type === 'first_issue' && p.action_ref === removed.id));
  }
  // work_tasks 삭제 → kpi_entry / settlement_check 적립 좀비 정리
  // - kpi_entry:   idempotency_key ends with ':<work_task.id>'
  // - settlement_check: idempotency_key starts with 'settlement_check:<work_task.id>:'
  if (table === 'work_tasks' && Array.isArray(db.engagement_points)) {
    const wtId = removed.id;
    db.engagement_points = db.engagement_points.filter(p => {
      if (p.action_ref === wtId) return false; // direct ref (kpi_entry 등)
      if (typeof p.idempotency_key === 'string') {
        if (p.idempotency_key.endsWith(':' + wtId)) return false; // kpi_entry
        if (p.idempotency_key.startsWith(`settlement_check:${wtId}:`)) return false; // settlement_check
      }
      return true;
    });
  }
  if (table === 'kb_documents') {
    if (Array.isArray(db.kb_document_versions)) {
      db.kb_document_versions = db.kb_document_versions.filter(v => v.document_id !== removed.id);
    }
    if (Array.isArray(db.kb_attachments)) {
      db.kb_attachments = db.kb_attachments.filter(a => a.parent_id !== removed.id);
    }
  }
  if (table === 'kb_issues' && Array.isArray(db.kb_attachments)) {
    db.kb_attachments = db.kb_attachments.filter(a => a.parent_id !== removed.id);
  }
}

function syncVacationQuotaOnDelete(db, removed) {
  if (!removed || !removed.start_date) return;
  const y = parseInt(removed.start_date.slice(0, 4), 10);
  if (!Number.isFinite(y)) return;
  recomputeQuotaForYear(db, y, removed.user_id, removed.member_name);
}

// 외부에서 직접 변경하면 점수 위변조가 되는 시스템 테이블 — 쓰기 차단
const POINTS_PROTECTED_TABLES = new Set([
  'engagement_points',
  'prize_history',
  'audit_reports',
  'audit_logs',
]);

function handleTablesRequest(route, method, bodyStr, reqHeaders) {
  return withDb(db => {
    const table = route.table;
    if (!Object.prototype.hasOwnProperty.call(db, table)) {
      return { status: 404, body: { error: `Unknown table: ${table}` } };
    }
    // 점수·감사 테이블은 GET 만 허용 (서버 내부 훅으로만 수정)
    if (POINTS_PROTECTED_TABLES.has(table) && method !== 'GET') {
      return { status: 403, body: { error: `${table} 는 직접 수정 불가 — 서버 내부 훅으로만 변경됩니다` } };
    }
    const collection = db[table];
    const body = bodyStr ? JSON.parse(bodyStr) : null;

    if (method === 'GET' && !route.id) {
      let items = applySearch(collection, route.searchParams.get('search') || '');
      items = applySort(items, route.searchParams.get('sort') || '');
      const paged = applyPaging(items, route.searchParams.get('page'), route.searchParams.get('limit') || '100');
      return { status: 200, body: { rows: paged, data: paged, total: items.length } };
    }

    if (method === 'GET' && route.id) {
      const item = collection.find(x => String(x.id) === String(route.id));
      if (!item) return { status: 404, body: { error: 'Not found' } };
      return { status: 200, body: item };
    }

    if (method === 'POST' && !route.id) {
      const id = body?.id || createId(table);
      let payload = body || {};
      // daily_work_entries: time_entries 자동 보정
      if (table === 'daily_work_entries') {
        payload = normalizeTimeEntries(db, payload);
      }
      // vacations: 직접 POST 도 /api/vacations/use 와 동일 안전망 적용
      //  - status 강제 'approved' (audit `vacation_no_status` 차단)
      //  - 시간대 있으면 buildEntriesFromRange 로 minutes/hours/days 서버 재계산
      //  - quota 한도 검사 (초과 시 400)
      if (table === 'vacations') {
        const sd = payload.start_date || '';
        const ed = payload.end_date || sd;
        if (!payload.member_name || !sd || !ed || !payload.vacation_type) {
          return { status: 400, body: { error: 'vacations 필수: member_name/start_date/end_date/vacation_type' } };
        }
        let minutes = 0, hours = 0, days = Number(payload.days) || 0;
        let time_entries = Array.isArray(payload.time_entries) ? payload.time_entries : [];
        if (payload.start_time && payload.end_time) {
          try {
            time_entries = timeentry.buildEntriesFromRange(sd, ed, payload.start_time, payload.end_time);
            minutes = time_entries.reduce((s, te) => s + (Number(te.minutes) || 0), 0);
            hours = Math.round((minutes / 60) * 10) / 10;
            days  = Math.round((minutes / (8 * 60)) * 100) / 100;
          } catch (e) {
            return { status: 400, body: { error: e.message } };
          }
        } else {
          if (!days || days <= 0) days = ['반차','2H','3H'].includes(payload.vacation_type) ? 0.5 : 1;
          minutes = Math.round(days * 8 * 60);
          hours = Math.round((minutes / 60) * 10) / 10;
        }
        const y = parseInt(sd.slice(0, 4), 10);
        const q = getOrCreateQuota(db, y, payload.user_id, payload.member_name);
        if ((Number(q.used) || 0) + days > q.annual_total + 0.001) {
          return { status: 400, body: { error: '연차 한도 초과', quota: q, request_days: days } };
        }
        payload = {
          ...payload,
          minutes, hours, days,
          time_entries,
          status: 'approved',
        };
      }
      const created = { ...payload, id, created_at: now(), updated_at: now() };
      db[table] = [...collection, created];
      // business_days 변경 → 월별 캐시 재계산
      if (table === 'business_days' && created.calendar_date) {
        const y = parseInt(created.calendar_date.slice(0, 4), 10);
        recomputeMonthlyCache(db, [y]);
      }
      // daily_work_entries 변경 → workload_daily_cache 재계산 (모든 영향 일자)
      if (table === 'daily_work_entries') {
        refreshDailyCacheFor(db, created);
      }
      // ── Phase 8: 포인트 적립 훅 (POST 성공 시) ──
      // actor 추출 — X-Actor-* 헤더 (portal.js fetch 인터셉터가 자동 첨부)
      try {
        const actorId = (reqHeaders && reqHeaders['x-actor-user']) || '';
        let actorName = (reqHeaders && reqHeaders['x-actor-username']) || '';
        try { actorName = decodeURIComponent(actorName); } catch (_) {}
        // username으로는 full_name 매칭 안 되니 users에서 다시 조회
        let actorFullName = '';
        if (actorId) {
          const u = (db.users || []).find(x => x.id === actorId);
          if (u) actorFullName = u.full_name || u.username || '';
        }
        const actorOpts = { actorId, actorName: actorFullName };
        if (table === 'daily_work_entries') {
          // work_entry: 그룹 멱등 — (member × 월 × task_label × task_category) 당 1회만 적립
          // 시간대 분할 입력으로 부풀리기 차단 (DATA_SYNC_RULES §8.6)
          const ym = (created.start_date || created.end_date || '').slice(0, 7); // 'YYYY-MM'
          // streak용 날짜: time_entries 첫 date 또는 start_date
          let entryDate = created.start_date || '';
          try {
            const te = typeof created.time_entries === 'string' ? JSON.parse(created.time_entries) : created.time_entries;
            if (Array.isArray(te) && te.length > 0 && te[0].date) entryDate = te[0].date;
          } catch (_) {}
          points.awardWorkEntryGrouped(
            db, created.id, created.user_id, created.member_name,
            ym, created.task_label || '', created.task_category || '',
            actorOpts, entryDate
          );
        } else if (table === 'kb_issues') {
          const memberName = created.member_name || created.created_by_name || created.author_name || '';
          const issueUserId = created.created_by || created.user_id;
          points.awardPoints(db, issueUserId, memberName, 'issue_register', created.id, actorOpts);
          // Phase 9: 분기 선착순 보너스 (전체 첫 이슈 등록자만)
          points.tryAwardFirstBonus(db, issueUserId, memberName, 'issue_register', actorOpts, created.id);
          // Phase 9: quarterly_mission 체크
          points.tryAwardQuarterlyMission(db, issueUserId, memberName, actorOpts);
        } else if (table === 'kb_documents') {
          const memberName = created.author_name || created.created_by_name || '';
          const sopUserId = created.author_id || created.created_by;
          points.awardPoints(db, sopUserId, memberName, 'sop_create', created.id, actorOpts);
          // Phase 9: 분기 선착순 보너스 (전체 첫 절차서 등록자만)
          points.tryAwardFirstBonus(db, sopUserId, memberName, 'sop_create', actorOpts, created.id);
          // Phase 9: quarterly_mission 체크
          points.tryAwardQuarterlyMission(db, sopUserId, memberName, actorOpts);
        } else if (table === 'vacations') {
          // 휴가 등록 시 vacation_quotas.used 자동 증가 (table 직접 POST 경로)
          syncVacationQuotaOnCreate(db, created);
        }
      } catch (e) { console.error('[points hook:create]', e.message); }
      appendAuditLog(db, table, 'create', route, null, created, reqHeaders);
      writeDb(db);
      return { status: 201, body: created };
    }

    if ((method === 'PATCH' || method === 'PUT') && route.id) {
      const idx = collection.findIndex(x => String(x.id) === String(route.id));
      if (idx === -1) return { status: 404, body: { error: 'Not found' } };
      const before = collection[idx];
      // ── Phase 4: kb_documents content 변경 시 자동 버전 스냅샷 ──
      let nextVersion = before.version || 1;
      if (table === 'kb_documents' && body && Object.prototype.hasOwnProperty.call(body, 'content')
          && before.content !== body.content) {
        db.kb_document_versions.push({
          id: createId('kbv'),
          document_id: before.id,
          version: before.version || 1,
          title: before.title,
          content: before.content,
          modified_by: before.author_id || null,
          modified_at: before.updated_at || now(),
          change_note: (body.change_note ? String(body.change_note) : ''),
          created_at: now(),
          updated_at: now(),
        });
        nextVersion = (before.version || 1) + 1;
      }
      // daily_work_entries: time_entries 자동 보정 (변경 사항이 시간대 영향 시)
      let mergedBody = body || {};
      if (table === 'daily_work_entries' &&
          (mergedBody.time_entries !== undefined ||
           mergedBody.start_time || mergedBody.end_time ||
           mergedBody.start_date || mergedBody.end_date ||
           mergedBody.duration_minutes !== undefined)) {
        mergedBody = normalizeTimeEntries(db, { ...before, ...mergedBody });
      }
      const updated = {
        ...before, ...mergedBody, id: before.id,
        ...(table === 'kb_documents' ? { version: nextVersion } : {}),
        updated_at: now(),
      };
      db[table][idx] = updated;
      if (table === 'business_days' && updated.calendar_date) {
        const y = parseInt(updated.calendar_date.slice(0, 4), 10);
        recomputeMonthlyCache(db, [y]);
      }
      if (table === 'daily_work_entries') {
        // before/after 양쪽 영향 일자 모두 재계산
        refreshDailyCacheFor(db, before);
        refreshDailyCacheFor(db, updated);
      }
      // ── Phase 8: KPI 입력 적립 훅 (work_tasks PATCH 시) ──
      try {
        const actorId = (reqHeaders && reqHeaders['x-actor-user']) || '';
        let actorFullName = '';
        if (actorId) {
          const u = (db.users || []).find(x => x.id === actorId);
          if (u) actorFullName = u.full_name || u.username || '';
        }
        const actorOpts = { actorId, actorName: actorFullName };
        if (table === 'work_tasks') {
          // KPI 입력 적립 (분기당 1회)
          const kpiFields = ['kpi1_score','kpi2_score','kpi3_score','kpi1_eval','kpi2_eval','kpi3_eval'];
          const filled = kpiFields.some(f => updated[f] != null && updated[f] !== '' && (before[f] == null || before[f] === ''));
          if (filled) {
            const userId = updated.user_id || updated.member_id || '';
            const memberName = updated.member_name || updated.target_name || '';
            points.awardPointsOncePerQuarter(db, userId, memberName, 'kpi_entry', updated.id, actorOpts);
          }
          // settlement_check 적립·회수 — settlement_done 배열 변경 감지 (DATA_SYNC_RULES §8.6)
          const prevDone = Array.isArray(before.settlement_done) ? before.settlement_done : [];
          const nextDone = Array.isArray(updated.settlement_done) ? updated.settlement_done : [];
          const doneChanged = prevDone.length !== nextDone.length ||
            nextDone.some(k => !prevDone.includes(k)) ||
            prevDone.some(k => !nextDone.includes(k));
          if (doneChanged) {
            points.syncSettlementCheckPoints(db, updated, before, actorOpts);
          }
        } else if (table === 'vacations') {
          syncVacationQuotaOnUpdate(db, before, updated);
        }
      } catch (e) { console.error('[points hook:update]', e.message); }
      appendAuditLog(db, table, 'update', route, before, updated, reqHeaders);
      writeDb(db);
      return { status: 200, body: updated };
    }

    if (method === 'DELETE' && route.id) {
      const idx = collection.findIndex(x => String(x.id) === String(route.id));
      if (idx === -1) return { status: 404, body: { error: 'Not found' } };
      const removed = collection[idx];
      db[table].splice(idx, 1);
      if (table === 'business_days' && removed && removed.calendar_date) {
        const y = parseInt(removed.calendar_date.slice(0, 4), 10);
        recomputeMonthlyCache(db, [y]);
      }
      if (table === 'daily_work_entries' && removed) {
        refreshDailyCacheFor(db, removed);
      }
      // ── Phase 8: 휴가 삭제 시 quotas.used 복원 ──
      try {
        if (table === 'vacations' && removed) {
          syncVacationQuotaOnDelete(db, removed);
        }
      } catch (e) { console.error('[points hook:delete]', e.message); }
      // ── 정합성 cascade: 적립 포인트·버전·첨부 좀비 정리 ──
      try {
        cascadeDeleteRelated(db, table, removed);
      } catch (e) { console.error('[cascade:delete]', e.message); }
      appendAuditLog(db, table, 'delete', route, removed, null, reqHeaders);
      writeDb(db);
      return { status: 200, body: { success: true } };
    }

    return { status: 405, body: { error: 'Method not allowed' } };
  });
}

function safeResolveStatic(urlPath) {
  const decoded = decodeURIComponent(urlPath.split('?')[0]);
  const rel = decoded.replace(/^\/+/, '');
  const abs = path.normalize(path.join(ROOT, rel));
  if (!abs.startsWith(ROOT)) return null;
  return abs;
}

function sendStatic(absPath, res) {
  fs.stat(absPath, (err, st) => {
    if (err || !st.isFile()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not found');
      return;
    }
    const ext = path.extname(absPath).toLowerCase();
    const headers = { 'Content-Type': MIME[ext] || 'application/octet-stream' };
    // HTML은 항상 fresh 가져오도록 (코드 업데이트 즉시 반영)
    // JS/CSS는 ?v=N 쿼리로 cache-busting 하므로 일반 캐시 OK
    if (ext === '.html') {
      headers['Cache-Control'] = 'no-cache, no-store, must-revalidate';
      headers['Pragma'] = 'no-cache';
      headers['Expires'] = '0';
    }
    res.writeHead(200, headers);
    fs.createReadStream(absPath).pipe(res);
  });
}

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PUT,PATCH,DELETE,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  const urlPath = req.url || '/';
  // [DIAG] 요청 로그 (Phase 6 진단용 — 운영 시 제거)
  const _t0 = Date.now();
  const _origEnd = res.end;
  res.end = function(...args) {
    console.log(`[REQ] ${req.method} ${urlPath} → ${res.statusCode} (${Date.now()-_t0}ms)`);
    return _origEnd.apply(res, args);
  };

  // Report generation: POST /api/reports/generate
  if (req.method === 'POST' && urlPath === '/api/reports/generate') {
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', async () => {
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        const { type, ym, author } = body;
        const ALLOWED = ['actuary', 'management', 'finance'];
        if (!ALLOWED.includes(type)) {
          res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify({ error: 'Unknown report type' }));
          return;
        }
        const outDir   = path.join(ROOT, 'reports', 'output');
        let args;
        if (type === 'actuary') {
          // 엑셀 리포트 생성기 (make_actuarial.py)
          const script = path.join(ROOT, 'reports', 'make_actuarial.py');
          args = [script, '--ym', ym || '', '--out', outDir];
        } else {
          // 워드 리포트 생성기 (generator.py)
          const dbPath = path.join(__dirname, 'data', 'actuarial.db');
          const script = path.join(ROOT, 'reports', 'generator.py');
          args = [script, '--type', type, '--ym', ym || '', '--db', dbPath, '--out', outDir, '--author', author || '계리결산팀'];
        }

        const runPy = (cmd) => new Promise(resolve => {
          const pyEnv = { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' };
          execFile(cmd, args, { timeout: 120000, cwd: ROOT, env: pyEnv },
            (err, stdout, stderr) => resolve({ err, stdout: stdout || '', stderr: stderr || '' }));
        });
        let r = await runPy('python');
        if (r.err && r.err.code === 'ENOENT') r = await runPy('python3');

        const output = r.stdout || r.stderr || (r.err?.message || '알 수 없는 오류');
        let parsed = {};
        try {
          const lines = output.trim().split('\n');
          parsed = JSON.parse(lines[lines.length - 1]);
        } catch (_) {}

        const runStatus = (r.err && !r.stdout) ? 'error' : (parsed.status || 'success');

        await withDb(db => {
          const log = {
            id: createId('rpt'), type, ym: ym || '', author: author || '',
            status: runStatus,
            filename: parsed.filename || '',
            output,
            created_at: now(), updated_at: now()
          };
          db.report_history.push(log);
          writeDb(db);
          return log;
        });

        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ status: runStatus, output, ...parsed }));
      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ error: String(e.message || e), status: 'error' }));
      }
    });
    return;
  }

  // Report download: GET /api/reports/download/:filename
  if (req.method === 'GET' && urlPath.startsWith('/api/reports/download/')) {
    const filename = decodeURIComponent(urlPath.slice('/api/reports/download/'.length));
    if (filename.includes('/') || filename.includes('\\') || !filename.endsWith('.docx')) {
      res.writeHead(400); res.end('Bad filename'); return;
    }
    const filePath = path.join(ROOT, 'reports', 'output', filename);
    fs.stat(filePath, (err, st) => {
      if (err || !st.isFile()) { res.writeHead(404); res.end('Not found'); return; }
      res.writeHead(200, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`
      });
      fs.createReadStream(filePath).pipe(res);
    });
    return;
  }

  // Automation endpoint: POST /api/automate/:type
  if (req.method === 'POST' && urlPath.startsWith('/api/automate/')) {
    const type = (urlPath.split('/api/automate/')[1] || '').split('?')[0].trim();
    const SCRIPT_MAP = {
      public_rate:   'public_rate_entry.py',
      assumption:    'assumption_keyin.py',
      expense_ratio: 'expense_ratio.py'
    };
    if (!SCRIPT_MAP[type]) {
      res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ error: 'Unknown automation type' }));
      return;
    }
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', async () => {
      const uploadsDir = path.join(__dirname, 'data', 'uploads');
      let tmpPath = null;
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        const { filename, content, ym } = body;
        fs.mkdirSync(uploadsDir, { recursive: true });
        const tmpName = `tmp_${Date.now()}_${crypto.randomBytes(4).toString('hex')}.xlsx`;
        tmpPath = path.join(uploadsDir, tmpName);
        fs.writeFileSync(tmpPath, Buffer.from(content, 'base64'));

        const dbPath = path.join(__dirname, 'data', 'actuarial.db');
        const scriptPath = path.join(ROOT, 'automation', SCRIPT_MAP[type]);
        const args = [scriptPath, '--file', tmpPath, '--db', dbPath];
        if (ym) args.push('--ym', ym);

        const runPy = (cmd) => new Promise(resolve => {
          execFile(cmd, args, { timeout: 60000, cwd: ROOT },
            (err, stdout, stderr) => resolve({ err, stdout: stdout || '', stderr: stderr || '' }));
        });

        let r = await runPy('python');
        if (r.err && r.err.code === 'ENOENT') r = await runPy('python3');

        const output = r.stdout || r.stderr || (r.err?.message || '알 수 없는 오류');
        let parsed = {};
        try {
          const lines = output.trim().split('\n');
          parsed = JSON.parse(lines[lines.length - 1]);
        } catch (_) {}

        const runStatus = (r.err && !r.stdout) ? 'error' : (parsed.status || 'success');

        await withDb(db => {
          const log = {
            id: createId('aut'), type,
            filename: filename || '',
            ym: ym || '',
            status: runStatus,
            rows_inserted: parsed.rows_inserted || 0,
            rows_updated: parsed.rows_updated || 0,
            rows_failed: parsed.rows_failed || 0,
            output,
            created_at: now(), updated_at: now()
          };
          db.automation_logs.push(log);
          writeDb(db);
          return log;
        });

        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ status: runStatus, output, ...parsed }));
      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ error: String(e.message || e), status: 'error' }));
      } finally {
        if (tmpPath) try { fs.unlinkSync(tmpPath); } catch (_) {}
      }
    });
    return;
  }

  // Bot status: GET /api/bot-status
  if (req.method === 'GET' && urlPath === '/api/bot-status') {
    const dbPath = path.join(__dirname, 'data', 'actuarial.db');
    const script = path.join(ROOT, 'bot', 'status_query.py');
    const args = [script, '--db', dbPath, '--limit', '50'];
    (async () => {
      const runPy = (cmd) => new Promise(resolve => {
        execFile(cmd, args, { timeout: 10000, cwd: ROOT },
          (err, stdout, stderr) => resolve({ err, stdout: stdout || '', stderr: stderr || '' }));
      });
      let r = await runPy('python');
      if (r.err && r.err.code === 'ENOENT') r = await runPy('python3');
      try {
        const lines = (r.stdout || '').trim().split('\n');
        const parsed = JSON.parse(lines[lines.length - 1]);
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify(parsed));
      } catch (_) {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ logs: [], total: 0, today: 0, last_query_at: null, status: 'error' }));
      }
    })();
    return;
  }

  // Bot heartbeat: GET /api/bot-heartbeat
  if (req.method === 'GET' && urlPath === '/api/bot-heartbeat') {
    const hbPath = path.join(__dirname, 'data', 'bot-heartbeat.json');
    fs.readFile(hbPath, 'utf8', (err, data) => {
      if (err) {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ last_alive: null, status: 'unknown', pid: null }));
        return;
      }
      try {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(data);
      } catch (_) {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ last_alive: null, status: 'unknown', pid: null }));
      }
    });
    return;
  }

  // ── Phase 7-2: 시간대 입력 검증/충돌/분산 미리보기 API ──
  if (urlPath.startsWith('/api/tasks/')) {
    const u = new URL(urlPath, 'http://internal');
    const subpath = u.pathname.slice('/api/tasks/'.length);
    const send = (status, body) => {
      res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(body));
    };
    const readBody = () => new Promise((resolve, reject) => {
      const chunks = [];
      req.on('data', c => chunks.push(c));
      req.on('end', () => {
        try { resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : null); }
        catch (e) { reject(e); }
      });
      req.on('error', reject);
    });

    (async () => {
      try {
        // POST /api/tasks/validate-time — time_entries 또는 from/to 검증
        if (req.method === 'POST' && subpath === 'validate-time') {
          const body = await readBody();
          if (!body) return send(400, { error: 'body 필수' });
          await withDb(db => {
            const bizMap = bizday.indexBusinessDays(db.business_days);
            let entries = body.time_entries;
            if (!entries && body.start_date && body.end_date && body.start_time && body.end_time) {
              try {
                entries = timeentry.buildEntriesFromRange(
                  body.start_date, body.end_date, body.start_time, body.end_time
                );
              } catch (e) {
                return send(200, { ok: false, errors: [e.message], warnings: [], entries: [] });
              }
            }
            if (!Array.isArray(entries) || entries.length === 0) {
              return send(200, { ok: false, errors: ['time_entries 또는 start_date/end_date/start_time/end_time 필수'], warnings: [], entries: [] });
            }
            const entry_results = entries.map(e => ({
              entry: e,
              ...timeentry.validateEntry(e, bizMap),
            }));
            const allErrors = entry_results.flatMap(r => r.errors);
            const allWarnings = entry_results.flatMap(r => r.warnings);
            const summary = timeentry.summarize(entries);
            send(200, {
              ok: allErrors.length === 0,
              errors: allErrors,
              warnings: allWarnings,
              entries,
              summary,
              entry_results,
            });
          });
          return;
        }

        // POST /api/tasks/conflicts — 동일 사용자 시간대 겹침 체크
        if (req.method === 'POST' && subpath === 'conflicts') {
          const body = await readBody();
          if (!body || !body.member_name || !Array.isArray(body.time_entries)) {
            return send(400, { error: 'member_name, time_entries 필수' });
          }
          await withDb(db => {
            const conflicts = timeentry.findOverlaps(
              db, body.member_name, body.time_entries, body.exclude_entry_id
            );
            send(200, { conflicts });
          });
          return;
        }

        // POST /api/tasks/spread — 분산 미리보기 (총 분량 + 종료일 → 시간대 배열)
        // body: { total_minutes, end_date }
        // 또는: { start_date, end_date, start_time, end_time }
        if (req.method === 'POST' && subpath === 'spread') {
          const body = await readBody();
          if (!body) return send(400, { error: 'body 필수' });
          await withDb(db => {
            const bizMap = bizday.indexBusinessDays(db.business_days);
            let entries = [];
            try {
              if (body.start_date && body.end_date && body.start_time && body.end_time) {
                entries = timeentry.buildEntriesFromRange(
                  body.start_date, body.end_date, body.start_time, body.end_time
                );
              } else if (Number(body.total_minutes) > 0 && body.end_date) {
                entries = timeentry.spreadMinutesAcrossBusinessDays(
                  Number(body.total_minutes), body.end_date, bizMap
                );
              } else {
                return send(400, { error: 'total_minutes+end_date 또는 from/to 필수' });
              }
            } catch (e) {
              return send(400, { error: String(e.message || e) });
            }
            const summary = timeentry.summarize(entries);
            send(200, { entries, summary });
          });
          return;
        }

        send(404, { error: 'Unknown tasks endpoint' });
      } catch (e) {
        send(500, { error: String(e.message || e) });
      }
    })();
    return;
  }

  // ── 자동 무결성 점검 API ──
  if (urlPath.startsWith('/api/audit/')) {
    const u = new URL(urlPath, 'http://internal');
    const subpath = u.pathname.slice('/api/audit/'.length);
    const send = (status, body) => {
      res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(body));
    };
    if (subpath === 'run' && req.method === 'POST') {
      try {
        runAuditAndSave('manual');
        const db = readDb();
        const reports = db.audit_reports || [];
        const latest = reports[reports.length - 1] || null;
        send(200, { ok: true, latest });
      } catch (e) {
        send(500, { error: 'audit failed', message: e.message });
      }
      return;
    }
    send(404, { error: 'unknown audit endpoint' });
    return;
  }

  // ── Phase 4: KB 전용 API ──
  if (urlPath.startsWith('/api/kb/')) {
    const u = new URL(urlPath, 'http://internal');
    const subpath = u.pathname.slice('/api/kb/'.length);
    const sp = u.searchParams;
    const send = (status, body) => {
      res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(body));
    };
    const readBody = () => new Promise((resolve, reject) => {
      const chunks = [];
      req.on('data', c => chunks.push(c));
      req.on('end', () => {
        try { resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : null); }
        catch (e) { reject(e); }
      });
      req.on('error', reject);
    });

    (async () => {
      try {
        // POST /api/kb/documents/:id/helpful — 유용성 카운터 증가
        const helpfulMatch = subpath.match(/^documents\/([^/]+)\/helpful$/);
        if (req.method === 'POST' && helpfulMatch) {
          const docId = decodeURIComponent(helpfulMatch[1]);
          await withDb(db => {
            const idx = db.kb_documents.findIndex(d => d.id === docId);
            if (idx === -1) return send(404, { error: 'Document not found' });
            db.kb_documents[idx].helpful_count = (db.kb_documents[idx].helpful_count || 0) + 1;
            db.kb_documents[idx].updated_at = now();
            writeDb(db);
            send(200, { id: docId, helpful_count: db.kb_documents[idx].helpful_count });
          });
          return;
        }

        // POST /api/kb/documents/:id/view — 조회수 증가 (선택)
        const viewMatch = subpath.match(/^documents\/([^/]+)\/view$/);
        if (req.method === 'POST' && viewMatch) {
          const docId = decodeURIComponent(viewMatch[1]);
          await withDb(db => {
            const idx = db.kb_documents.findIndex(d => d.id === docId);
            if (idx === -1) return send(404, { error: 'Document not found' });
            db.kb_documents[idx].view_count = (db.kb_documents[idx].view_count || 0) + 1;
            db.kb_documents[idx].updated_at = now();
            writeDb(db);
            send(200, { id: docId, view_count: db.kb_documents[idx].view_count });
          });
          return;
        }

        // GET /api/kb/documents/:id/versions — 버전 목록
        const versionsMatch = subpath.match(/^documents\/([^/]+)\/versions$/);
        if (req.method === 'GET' && versionsMatch) {
          const docId = decodeURIComponent(versionsMatch[1]);
          await withDb(db => {
            const versions = (db.kb_document_versions || [])
              .filter(v => v.document_id === docId)
              .sort((a, b) => (b.version || 0) - (a.version || 0));
            send(200, { document_id: docId, versions });
          });
          return;
        }

        // GET /api/kb/issues/:id/similar — 태그/카테고리 기반 유사
        const similarMatch = subpath.match(/^issues\/([^/]+)\/similar$/);
        if (req.method === 'GET' && similarMatch) {
          const issueId = decodeURIComponent(similarMatch[1]);
          await withDb(db => {
            const target = (db.kb_issues || []).find(i => i.id === issueId);
            if (!target) return send(404, { error: 'Issue not found' });
            const targetTags = String(target.tags || '').split(',').map(s => s.trim()).filter(Boolean);
            const scored = (db.kb_issues || [])
              .filter(i => i.id !== issueId)
              .map(i => {
                const itTags = String(i.tags || '').split(',').map(s => s.trim()).filter(Boolean);
                const tagOverlap = targetTags.filter(t => itTags.includes(t)).length;
                const catMatch = i.category && i.category === target.category ? 1 : 0;
                return { issue: i, score: tagOverlap * 2 + catMatch };
              })
              .filter(x => x.score > 0)
              .sort((a, b) => b.score - a.score)
              .slice(0, 10)
              .map(x => ({ ...x.issue, _similarity: x.score }));
            send(200, { source_id: issueId, similar: scored });
          });
          return;
        }

        // POST /api/kb/upload — 첨부파일 업로드 (base64 JSON)
        // body: { filename, content (base64), context?: 'sop'|'issue'|'handover' }
        if (req.method === 'POST' && subpath === 'upload') {
          const body = await readBody();
          if (!body || !body.filename || !body.content) {
            return send(400, { error: 'filename / content (base64) 필수' });
          }
          const safeOriginal = String(body.filename).replace(/[\\/]/g, '_');
          const ext = path.extname(safeOriginal).toLowerCase();
          const allowed = ['.pdf','.xlsx','.xls','.docx','.doc','.png','.jpg','.jpeg','.csv','.txt','.zip'];
          if (!allowed.includes(ext)) {
            return send(400, { error: '허용되지 않은 확장자: ' + ext });
          }
          const uploadsDir = path.join(__dirname, 'data', 'kb_files');
          fs.mkdirSync(uploadsDir, { recursive: true });
          const stored = `${Date.now()}_${crypto.randomBytes(4).toString('hex')}${ext}`;
          const fullPath = path.join(uploadsDir, stored);
          fs.writeFileSync(fullPath, Buffer.from(body.content, 'base64'));
          const stat = fs.statSync(fullPath);
          send(200, {
            stored_name: stored,
            original_name: safeOriginal,
            size: stat.size,
            url: `/api/kb/download/${encodeURIComponent(stored)}`,
            ext,
          });
          return;
        }

        // GET /api/kb/download/:storedName — 첨부파일 다운로드
        const downloadMatch = subpath.match(/^download\/([^/]+)$/);
        if (req.method === 'GET' && downloadMatch) {
          const stored = decodeURIComponent(downloadMatch[1]);
          if (stored.includes('/') || stored.includes('\\') || stored.includes('..')) {
            return send(400, { error: 'Bad filename' });
          }
          const fullPath = path.join(__dirname, 'data', 'kb_files', stored);
          fs.stat(fullPath, (err, st) => {
            if (err || !st.isFile()) { res.writeHead(404); res.end('Not found'); return; }
            const ext = path.extname(stored).toLowerCase();
            const ct = MIME[ext] || 'application/octet-stream';
            res.writeHead(200, {
              'Content-Type': ct,
              'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(stored)}`,
              'Content-Length': st.size,
            });
            fs.createReadStream(fullPath).pipe(res);
          });
          return;
        }

        send(404, { error: 'Unknown KB endpoint' });
      } catch (e) {
        send(500, { error: String(e.message || e) });
      }
    })();
    return;
  }

  // ── Phase 8: 게이미피케이션 (points / prizes) API ──
  if (urlPath.startsWith('/api/points/') || urlPath.startsWith('/api/prizes/') || urlPath.startsWith('/api/vacations/')) {
    const u = new URL(urlPath, 'http://internal');
    const sp = u.searchParams;
    const send = (status, body) => {
      res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(body));
    };
    const readBody = () => new Promise(resolve => {
      const cs = [];
      req.on('data', c => cs.push(c));
      req.on('end', () => {
        const s = Buffer.concat(cs).toString('utf8');
        try { resolve(s ? JSON.parse(s) : {}); } catch (_) { resolve({}); }
      });
    });

    (async () => {
      try {
        // GET /api/points/me?user=<id>&member=<name>
        if (req.method === 'GET' && u.pathname === '/api/points/me') {
          const userId = sp.get('user') || '';
          const memberName = sp.get('member') || '';
          await withDb(db => {
            const q = sp.get('quarter') || points.currentQuarter();
            const mine = (db.engagement_points || []).filter(p =>
              (userId && p.user_id === userId) || (memberName && p.member_name === memberName)
            );
            const byQuarter = {};
            for (const p of mine) {
              byQuarter[p.quarter] = (byQuarter[p.quarter] || 0) + (Number(p.points) || 0);
            }
            const currentTotal = mine.filter(p => p.quarter === q).reduce((s, p) => s + (Number(p.points) || 0), 0);
            send(200, {
              user_id: userId, member_name: memberName,
              quarter: q,
              current_total: currentTotal,
              entries: mine.filter(p => p.quarter === q).sort((a, b) => b.awarded_at - a.awarded_at),
              by_quarter: byQuarter,
            });
          });
          return;
        }
        // GET /api/points/ranking?quarter=YYYY-Qn
        if (req.method === 'GET' && u.pathname === '/api/points/ranking') {
          const q = sp.get('quarter') || points.currentQuarter();
          await withDb(db => {
            const ranking = points.getQuarterRanking(db, q);
            send(200, { quarter: q, ranking });
          });
          return;
        }
        // GET /api/points/top3?quarter=...
        if (req.method === 'GET' && u.pathname === '/api/points/top3') {
          const q = sp.get('quarter') || points.currentQuarter();
          await withDb(db => {
            send(200, points.top3WithPrizes(db, q));
          });
          return;
        }
        // GET /api/points/awards?quarter=... — Phase 9: 전체 보상 현황 (top3+참여상+성장상+MVP)
        if (req.method === 'GET' && u.pathname === '/api/points/awards') {
          const q = sp.get('quarter') || points.currentQuarter();
          await withDb(db => {
            send(200, points.getAllAwards(db, q));
          });
          return;
        }
        // POST /api/prizes/finalize?quarter=...
        if (req.method === 'POST' && u.pathname === '/api/prizes/finalize') {
          const q = sp.get('quarter') || points.currentQuarter();
          const role = (req.headers['x-actor-role'] || '').toLowerCase();
          if (role && role !== 'team_leader') {
            return send(403, { error: '팀장만 시상 확정 가능' });
          }
          await withDb(db => {
            const r = points.finalizeQuarter(db, q);
            writeDb(db);
            send(200, r);
          });
          return;
        }
        // POST /api/points/recompute — engagement_points 전체 재계산 (팀장만)
        //   현재 DB의 record를 직접 스캔 → 본인=target 가정 + audit_logs로 actor 보강 검증
        if (req.method === 'POST' && u.pathname === '/api/points/recompute') {
          const actorRole = req.headers && req.headers['x-actor-role'];
          if (actorRole && actorRole !== 'team_leader') {
            return send(403, { error: '팀장만 실행 가능' });
          }
          await withDb(db => {
            const usersById = {};
            const usersByName = {};
            for (const u of (db.users || [])) {
              usersById[u.id] = u;
              if (u.full_name) usersByName[u.full_name] = u;
              if (u.username)  usersByName[u.username] = u;
            }
            // audit_logs에서 record_id별 마지막 actor 매핑 (감사 보강)
            const recordActor = {};
            for (const log of (db.audit_logs || [])) {
              if (!log.action || !log.action.startsWith('create:')) continue;
              const m = (log.detail || '').match(/id=(\S+)/);
              if (!m) continue;
              const rid = m[1];
              const actor = usersById[log.user_id];
              if (actor) recordActor[rid] = actor;
            }

            // 모든 engagement_points 삭제
            db.engagement_points = [];

            // strict 모드: ?strict=1 이면 actor 미상 record 는 skip (audit_logs 한도 초과시 형평성 보호)
            const strictMode = (sp && sp.get('strict')) === '1';

            const tables = [
              { name: 'daily_work_entries', action: 'work_entry' },
              { name: 'kb_issues',          action: 'issue_register' },
              { name: 'kb_documents',       action: 'sop_create' },
            ];
            let awarded = 0, skipped = 0;
            const detail = {};
            const skipReasons = { no_target: 0, team_leader: 0, actor_unknown_strict: 0, actor_mismatch: 0, no_member: 0, dedup: 0 };
            for (const tdef of tables) {
              const list = db[tdef.name] || [];
              for (const rec of list) {
                const targetUserId = rec.user_id || rec.author_id || rec.created_by || '';
                const targetName = rec.member_name || rec.author_name || rec.created_by_name || '';
                if (!targetUserId && !targetName) { skipped++; skipReasons.no_member++; continue; }
                const targetUser = usersById[targetUserId] || usersByName[targetName];
                if (!targetUser) { skipped++; skipReasons.no_target++; continue; }
                if (targetUser.role === 'team_leader') { skipped++; skipReasons.team_leader++; continue; }
                const actor = recordActor[rec.id];
                if (actor && actor.id !== targetUser.id) {
                  skipped++; skipReasons.actor_mismatch++; continue; // 대리 입력 차단
                }
                // strict 모드: audit_logs에서 actor를 못 찾으면 skip (본인 가정 금지)
                if (strictMode && !actor) {
                  skipped++; skipReasons.actor_unknown_strict++; continue;
                }
                const actorOpts = actor
                  ? { actorId: actor.id, actorName: actor.full_name || actor.username }
                  : { actorId: targetUser.id, actorName: targetUser.full_name || targetUser.username };
                const result = points.awardPoints(db, targetUser.id,
                  targetUser.full_name || targetUser.username,
                  tdef.action, rec.id, actorOpts);
                if (result) {
                  awarded++;
                  detail[tdef.action] = (detail[tdef.action] || 0) + 1;
                  // Phase 9: first_sop / first_issue 보너스 재계산
                  //   awardPoints 내부에서 streak_bonus / quarterly_mission 은 자동 호출되나
                  //   first_bonus 는 server.js POST 훅에 있어서 recompute 에서 별도 호출.
                  if (tdef.action === 'issue_register' || tdef.action === 'sop_create') {
                    points.tryAwardFirstBonus(db, targetUser.id,
                      targetUser.full_name || targetUser.username,
                      tdef.action, actorOpts, rec.id);
                  }
                } else {
                  skipped++; skipReasons.dedup++;
                }
              }
            }

            // KPI (work_tasks) — 분기당 1회 적립. 분기별로 한 사용자에게 한 번만.
            // 어떤 분기에서든 KPI 필드가 채워진 work_task 가 있으면 그 분기에 적립.
            const wt_list = db.work_tasks || [];
            const kpiFields = ['kpi1_score','kpi2_score','kpi3_score','kpi1_eval','kpi2_eval','kpi3_eval'];
            // year-month → quarter 환산용
            const toQuarter = (y, m) => `${y}-Q${Math.floor((m - 1) / 3) + 1}`;
            for (const t of wt_list) {
              const filled = kpiFields.some(f => t[f] != null && t[f] !== '');
              if (!filled) continue;
              const targetUserId = t.user_id || t.member_id || '';
              const targetName = t.member_name || t.target_name || '';
              const targetUser = usersById[targetUserId] || usersByName[targetName];
              if (!targetUser) { skipped++; skipReasons.no_target++; continue; }
              if (targetUser.role === 'team_leader') { skipped++; skipReasons.team_leader++; continue; }
              const actor = recordActor[t.id];
              if (actor && actor.id !== targetUser.id) {
                skipped++; skipReasons.actor_mismatch++; continue;
              }
              if (strictMode && !actor) {
                skipped++; skipReasons.actor_unknown_strict++; continue;
              }
              // 해당 work_task 가 어느 분기인지 추정 — t.year / t.month 또는 t.quarter
              let quarter = t.quarter;
              if (!quarter && t.year && t.month) quarter = toQuarter(Number(t.year), Number(t.month));
              if (!quarter) { skipped++; skipReasons.no_member++; continue; }
              // 멱등 — 분기+사용자+kpi_entry 한 번
              const dedupKey = `kpi_entry:${quarter}:${targetUser.full_name || targetUser.username}`;
              if ((db.engagement_points || []).some(p => p.idempotency_key && p.idempotency_key.startsWith(dedupKey))) {
                skipped++; skipReasons.dedup++; continue;
              }
              const actorOpts = actor
                ? { actorId: actor.id, actorName: actor.full_name || actor.username }
                : { actorId: targetUser.id, actorName: targetUser.full_name || targetUser.username };
              // awardPoints (kpi_entry) - 직접 호출 + idempotency_key 강제로 분기 기반
              const t_ms = Date.now();
              const points_v = (db.point_rules || []).find(r => r.action_type === 'kpi_entry')?.points || 10;
              db.engagement_points.push({
                id: 'ep_kpi_' + Math.random().toString(16).slice(2, 14) + t_ms.toString(36),
                user_id: targetUser.id,
                member_name: targetUser.full_name || targetUser.username,
                action_type: 'kpi_entry',
                action_ref: t.id,
                points: points_v,
                quarter,
                awarded_at: t_ms,
                idempotency_key: `${dedupKey}:${t.id}`,
                actor_user_id: actorOpts.actorId || '',
                actor_name: actorOpts.actorName || '',
                created_at: t_ms, updated_at: t_ms,
              });
              awarded++;
              detail.kpi_entry = (detail.kpi_entry || 0) + 1;
            }
            // settlement_check (work_tasks) — settlement_done 배열 키당 3pt, 분기당 30건 캡
            for (const t of wt_list) {
              const doneDone = Array.isArray(t.settlement_done) ? t.settlement_done : [];
              if (doneDone.length === 0) continue;
              const targetUserId = t.user_id || t.member_id || '';
              const targetName = t.member_name || t.target_name || '';
              const targetUser = usersById[targetUserId] || usersByName[targetName];
              if (!targetUser) { skipped += doneDone.length; skipReasons.no_target += doneDone.length; continue; }
              if (targetUser.role === 'team_leader') { skipped += doneDone.length; skipReasons.team_leader += doneDone.length; continue; }
              // actor 검증은 strict 모드에서만
              const actor = recordActor[t.id];
              if (actor && actor.id !== targetUser.id) {
                skipped += doneDone.length; skipReasons.actor_mismatch += doneDone.length; continue;
              }
              if (strictMode && !actor) {
                skipped += doneDone.length; skipReasons.actor_unknown_strict += doneDone.length; continue;
              }
              const actorOpts2 = actor
                ? { actorId: actor.id, actorName: actor.full_name || actor.username }
                : { actorId: targetUser.id, actorName: targetUser.full_name || targetUser.username };
              // syncSettlementCheckPoints 는 before/after diff 기반이라 recompute에선 직접 삽입
              const rule_sc = (db.point_rules || []).find(r => r.action_type === 'settlement_check' && r.is_active !== false);
              const sc_pts = rule_sc ? (Number(rule_sc.points) || 0) : 3;
              const QUARTER_CAP = 30;
              // work_task 의 연/월에서 분기 추정
              let wt_quarter = t.quarter;
              if (!wt_quarter && t.year && t.month) wt_quarter = toQuarter(Number(t.year), Number(t.month));
              if (!wt_quarter) { skipped += doneDone.length; skipReasons.no_member += doneDone.length; continue; }
              for (const key of doneDone) {
                const ikey = `settlement_check:${t.id}:${key}`;
                if ((db.engagement_points || []).some(p => p.idempotency_key === ikey)) {
                  skipped++; skipReasons.dedup++; continue;
                }
                // 분기 캡
                const quarterCount = (db.engagement_points || []).filter(p =>
                  p.action_type === 'settlement_check' && p.quarter === wt_quarter &&
                  (p.user_id === targetUser.id || p.member_name === (targetUser.full_name || targetUser.username))
                ).length;
                if (quarterCount >= QUARTER_CAP) { skipped++; skipReasons.dedup++; continue; }
                if (sc_pts <= 0) { skipped++; continue; }
                const t_ms2 = Date.now();
                db.engagement_points.push({
                  id: 'ep_sc_' + Math.random().toString(16).slice(2, 14),
                  user_id: targetUser.id,
                  member_name: targetUser.full_name || targetUser.username,
                  action_type: 'settlement_check',
                  action_ref: `${t.id}:${key}`,
                  points: sc_pts,
                  quarter: wt_quarter,
                  awarded_at: t_ms2,
                  idempotency_key: ikey,
                  actor_user_id: actorOpts2.actorId || '',
                  actor_name: actorOpts2.actorName || '',
                  created_at: t_ms2, updated_at: t_ms2,
                });
                awarded++;
                detail.settlement_check = (detail.settlement_check || 0) + 1;
              }
            }

            // work_entry 재계산: 그룹 멱등 반영 — recompute 시 group_key 기반 중복 제거
            // (위 tables 루프에서 awardPoints를 직접 호출하므로 group_key 미부여. 사후에 정규화)
            // daily_work_entries 를 재스캔해서 group 중복된 ep row를 제거
            {
              const groupSeen = new Set();
              const toRemoveIds = new Set();
              // awarded 된 work_entry rows (위에서 이미 삽입됨) 를 후처리
              const epList = db.engagement_points || [];
              const weRows = epList.filter(p => p.action_type === 'work_entry');
              for (const ep of weRows) {
                // group_key 없는 경우(레거시) → dwe record에서 group_key 유추
                if (!ep.group_key) {
                  const dwe = (db.daily_work_entries || []).find(e => e.id === ep.action_ref);
                  if (dwe) {
                    const ym = (dwe.start_date || dwe.end_date || '').slice(0, 7);
                    ep.group_key = `${ep.member_name}:${ym}:${dwe.task_label || ''}:${dwe.task_category || ''}`;
                  }
                }
                if (!ep.group_key) continue;
                if (groupSeen.has(ep.group_key)) {
                  toRemoveIds.add(ep.id); // 그룹 중복 → 제거
                } else {
                  groupSeen.add(ep.group_key);
                }
              }
              if (toRemoveIds.size > 0) {
                db.engagement_points = db.engagement_points.filter(p => !toRemoveIds.has(p.id));
                skipped += toRemoveIds.size;
                skipReasons.dedup += toRemoveIds.size;
              }
            }

            // streak_bonus 백필 — 멤버별로 입력일 정렬 후 각 일자에 streak 시도
            //   awardWorkEntryGrouped 는 idempotency_key 통과한 경우만 streak 호출하므로
            //   recompute(직접 awardPoints) 경로에선 streak 누락. 여기서 일괄 채운다.
            //   quarterly_mission 도 마지막 work_entry 적립 후 1회 호출.
            {
              const memberDates = {}; // member_name → Set<date>
              for (const dwe of (db.daily_work_entries || [])) {
                const m = dwe.member_name;
                if (!m) continue;
                let dates = [];
                try {
                  const te = typeof dwe.time_entries === 'string' ? JSON.parse(dwe.time_entries) : dwe.time_entries;
                  if (Array.isArray(te) && te.length > 0) dates = te.map(t => t && t.date).filter(Boolean);
                } catch (_) {}
                if (dates.length === 0 && dwe.start_date) dates = [dwe.start_date];
                if (!memberDates[m]) memberDates[m] = new Set();
                for (const d of dates) memberDates[m].add(d);
              }
              for (const [memberName, dateSet] of Object.entries(memberDates)) {
                const targetUser = usersByName[memberName];
                if (!targetUser) continue;
                if (targetUser.role === 'team_leader') continue;
                const actor = recordActor[memberName] || null;
                if (strictMode && !actor) continue;
                const actorOptsM = { actorId: targetUser.id, actorName: memberName };
                const sortedDates = Array.from(dateSet).sort();
                for (const d of sortedDates) {
                  try {
                    const before = (db.engagement_points || []).length;
                    points.tryAwardStreakBonus(db, targetUser.id, memberName, d, actorOptsM);
                    if ((db.engagement_points || []).length > before) {
                      awarded++;
                      detail.streak_bonus = (detail.streak_bonus || 0) + 1;
                    }
                  } catch (_) {}
                }
                // 분기 미션 1회 시도
                try {
                  const before = (db.engagement_points || []).length;
                  points.tryAwardQuarterlyMission(db, targetUser.id, memberName, actorOptsM);
                  if ((db.engagement_points || []).length > before) {
                    awarded++;
                    detail.quarterly_mission = (detail.quarterly_mission || 0) + 1;
                  }
                } catch (_) {}
              }
            }

            writeDb(db);
            send(200, { awarded, skipped, detail, skip_reasons: skipReasons,
                        total_audit_logs: (db.audit_logs || []).length,
                        strict_mode: strictMode });
          });
          return;
        }
        // POST /api/points/quarter-reset — 팀장 전용 강제 초기화 (분기 외 시점이라도 실행)
        if (req.method === 'POST' && u.pathname === '/api/points/quarter-reset') {
          const actorRole = req.headers && req.headers['x-actor-role'];
          if (actorRole && actorRole !== 'team_leader') {
            return send(403, { error: '팀장만 실행 가능' });
          }
          await withDb(db => {
            const before = (db.engagement_points || []).length;
            db.engagement_points = [];
            db.meta = db.meta || {};
            const now = new Date();
            const qKey = `${now.getFullYear()}-Q${Math.floor(now.getMonth() / 3) + 1}`;
            db.meta.last_quarter_reset = qKey;
            db.meta.last_quarter_reset_at = Date.now();
            writeDb(db);
            send(200, { ok: true, reset_count: before, quarter: qKey, note: '업무 데이터는 보존됨' });
          });
          return;
        }
        // GET /api/prizes/history
        if (req.method === 'GET' && u.pathname === '/api/prizes/history') {
          await withDb(db => {
            const rows = [...(db.prize_history || [])].sort((a, b) =>
              String(b.quarter).localeCompare(String(a.quarter)) || a.rank - b.rank);
            send(200, { rows });
          });
          return;
        }
        // POST /api/vacations/use
        // body: { user_id, member_name, vacation_type,
        //         start_date, end_date,
        //         start_time?, end_time?,        ← 30분 단위 HH:MM (선택)
        //         days?,                          ← 시간대 없으면 fallback
        //         note }
        // 시간대(start_time/end_time) 있으면 업무시간과 동일한 timeentry 매커니즘으로
        // 점심 1h 자동 차감 → 시간/일수(8h=1일) 환산.
        if (req.method === 'POST' && u.pathname === '/api/vacations/use') {
          const body = await readBody();
          const { user_id, member_name, vacation_type, start_date, end_date,
                  start_time, end_time, note } = body || {};
          if (!member_name || !start_date || !end_date || !vacation_type) {
            return send(400, { error: 'member_name, vacation_type, start_date, end_date 필수' });
          }
          let minutes = 0, hours = 0, days = Number(body && body.days);
          let time_entries = [];
          // 시간대 입력 (30분 단위) — 업무시간 timeentry 매커니즘 재활용
          if (start_time && end_time) {
            try {
              time_entries = timeentry.buildEntriesFromRange(start_date, end_date, start_time, end_time);
              minutes = time_entries.reduce((s, te) => s + (Number(te.minutes) || 0), 0);
              hours = Math.round((minutes / 60) * 10) / 10;
              days = Math.round((minutes / (8 * 60)) * 100) / 100;
            } catch (e) {
              return send(400, { error: e.message });
            }
          } else if (!Number.isFinite(days) || days <= 0) {
            // fallback: days 직접 입력도 시간대도 없으면 영업일 카운트
            await withDb(db => {
              const bizMap = bizday.indexBusinessDays(db.business_days);
              const startD = new Date(start_date + 'T00:00:00');
              const endD = new Date(end_date + 'T00:00:00');
              let count = 0;
              const cur = new Date(startD);
              while (cur <= endD) {
                if (bizday.isBusinessDay(isoOf(cur), bizMap)) count++;
                cur.setDate(cur.getDate() + 1);
              }
              days = ['반차','2H','3H'].includes(vacation_type) ? 0.5 : count;
            });
          }
          if (!minutes) {
            minutes = Math.round(days * 8 * 60);
            hours = Math.round((minutes / 60) * 10) / 10;
          }
          let result = null;
          let errOut = null;
          await withDb(db => {
            const y = parseInt(start_date.slice(0, 4), 10);
            const q = getOrCreateQuota(db, y, user_id, member_name);
            if (q.used + days > q.annual_total) {
              errOut = { status: 400, body: { error: '연차 한도 초과', quota: q, request_days: days } };
              return;
            }
            const t = now();
            const row = {
              id: createId('vac'),
              user_id: user_id || '',
              member_name,
              vacation_type,
              start_date, end_date,
              start_time: start_time || '',
              end_time: end_time || '',
              minutes, hours, days,
              time_entries,
              note: note || '',
              status: 'approved',
              approved_by: '',
              created_at: t, updated_at: t,
            };
            db.vacations = [...(db.vacations || []), row];
            recomputeQuotaForYear(db, y, user_id, member_name);
            writeDb(db);
            result = { vacation: row, quota: db.vacation_quotas.find(x =>
              x.year === y && ((user_id && x.user_id === user_id) || x.member_name === member_name)) };
          });
          if (errOut) return send(errOut.status, errOut.body);
          return send(201, result);
        }
        // POST /api/vacations/update
        // body: { id, vacation_type, start_date, end_date, start_time?, end_time?, note? }
        // 기존 휴가 row 재계산(time_entries / minutes / hours / days) + quota 한도 검사 + recompute.
        // status='cancelled' 인 row 는 수정 불가 (재등록 필요).
        if (req.method === 'POST' && u.pathname === '/api/vacations/update') {
          const body = await readBody();
          const { id, vacation_type, start_date, end_date, start_time, end_time, note } = body || {};
          if (!id) return send(400, { error: 'id 필수' });
          if (!vacation_type || !start_date || !end_date) {
            return send(400, { error: 'vacation_type, start_date, end_date 필수' });
          }
          let result = null, errOut = null;
          await withDb(db => {
            const idx = (db.vacations || []).findIndex(v => v.id === id);
            if (idx < 0) { errOut = { status: 404, body: { error: '휴가 없음' } }; return; }
            const before = db.vacations[idx];
            if (before.status === 'cancelled') {
              errOut = { status: 400, body: { error: '취소된 휴가는 수정할 수 없습니다. 새로 등록하세요.' } };
              return;
            }
            // 1) 시간/일수 재계산
            let minutes = 0, hours = 0, days = 0, time_entries = [];
            if (start_time && end_time) {
              try {
                time_entries = timeentry.buildEntriesFromRange(start_date, end_date, start_time, end_time);
                minutes = time_entries.reduce((s, te) => s + (Number(te.minutes) || 0), 0);
                hours = Math.round((minutes / 60) * 10) / 10;
                days = Math.round((minutes / (8 * 60)) * 100) / 100;
              } catch (e) {
                errOut = { status: 400, body: { error: e.message } };
                return;
              }
            } else {
              const bizMap = bizday.indexBusinessDays(db.business_days);
              const startD = new Date(start_date + 'T00:00:00');
              const endD = new Date(end_date + 'T00:00:00');
              let count = 0;
              const cur = new Date(startD);
              while (cur <= endD) {
                if (bizday.isBusinessDay(isoOf(cur), bizMap)) count++;
                cur.setDate(cur.getDate() + 1);
              }
              days = ['반차','2H','3H'].includes(vacation_type) ? 0.5 : count;
              minutes = Math.round(days * 8 * 60);
              hours = Math.round((minutes / 60) * 10) / 10;
            }
            // 2) 한도 체크 — (현재 used) - (기존 days) + (새 days)
            const y = parseInt(start_date.slice(0, 4), 10);
            const q = getOrCreateQuota(db, y, before.user_id, before.member_name);
            const projectedUsed = (Number(q.used) || 0) - (Number(before.days) || 0) + days;
            if (projectedUsed > q.annual_total + 0.001) {
              errOut = { status: 400, body: { error: '연차 한도 초과', quota: q, projected_used: projectedUsed } };
              return;
            }
            // 3) row 업데이트
            const updated = {
              ...before,
              vacation_type,
              start_date, end_date,
              start_time: start_time || '',
              end_time: end_time || '',
              minutes, hours, days,
              time_entries,
              note: note != null ? note : (before.note || ''),
              updated_at: now(),
            };
            db.vacations[idx] = updated;
            // 4) quota 재계산 (before/after 연도 모두)
            syncVacationQuotaOnUpdate(db, before, updated);
            writeDb(db);
            result = { vacation: updated, quota: db.vacation_quotas.find(x =>
              x.year === y && ((before.user_id && x.user_id === before.user_id) || x.member_name === before.member_name)) };
          });
          if (errOut) return send(errOut.status, errOut.body);
          return send(200, result);
        }
        // POST /api/vacations/cancel — status='cancelled' 로 PATCH (이력 보존 + quota 복원)
        if (req.method === 'POST' && u.pathname === '/api/vacations/cancel') {
          const body = await readBody();
          const { id } = body || {};
          if (!id) return send(400, { error: 'id 필수' });
          let result = null, errOut = null;
          await withDb(db => {
            const idx = (db.vacations || []).findIndex(v => v.id === id);
            if (idx < 0) { errOut = { status: 404, body: { error: '휴가 없음' } }; return; }
            const before = db.vacations[idx];
            if (before.status === 'cancelled') {
              errOut = { status: 400, body: { error: '이미 취소된 휴가입니다.' } };
              return;
            }
            const updated = { ...before, status: 'cancelled', cancelled_at: now(), updated_at: now() };
            db.vacations[idx] = updated;
            syncVacationQuotaOnUpdate(db, before, updated);
            writeDb(db);
            result = { vacation: updated };
          });
          if (errOut) return send(errOut.status, errOut.body);
          return send(200, result);
        }
        // GET /api/vacations/list?member=NAME&year=YYYY
        if (req.method === 'GET' && u.pathname === '/api/vacations/list') {
          const memberName = sp.get('member') || '';
          const year = sp.get('year') || String(new Date().getFullYear());
          await withDb(db => {
            const rows = (db.vacations || []).filter(v =>
              (!memberName || v.member_name === memberName) &&
              (!year || (v.start_date && v.start_date.slice(0, 4) === String(year)))
            ).sort((a, b) => String(b.start_date).localeCompare(String(a.start_date)));
            const quota = memberName
              ? (db.vacation_quotas || []).find(x => x.year === parseInt(year, 10) && x.member_name === memberName) || null
              : null;
            send(200, { rows, quota });
          });
          return;
        }
        // GET /api/vacations/quota?member=NAME&year=YYYY
        if (req.method === 'GET' && u.pathname === '/api/vacations/quota') {
          const memberName = sp.get('member') || '';
          const userId = sp.get('user') || '';
          const year = parseInt(sp.get('year') || String(new Date().getFullYear()), 10);
          await withDb(db => {
            const q = getOrCreateQuota(db, year, userId, memberName);
            recomputeQuotaForYear(db, year, userId, memberName);
            writeDb(db);
            send(200, q);
          });
          return;
        }
        send(404, { error: 'Unknown endpoint', path: u.pathname });
      } catch (e) {
        send(500, { error: String(e.message || e) });
      }
    })();
    return;
  }

  // ── Phase 2: 업무량 모니터링 API ──
  if (urlPath.startsWith('/api/workload/')) {
    const u = new URL(urlPath, 'http://internal');
    const subpath = u.pathname.slice('/api/workload/'.length);
    const sp = u.searchParams;

    // 활성 팀원 목록 (member_name 기준)
    const activeMembers = (db) =>
      (db.users || [])
        .filter(x => x.is_active !== false && x.role !== 'team_leader')
        .map(x => x.full_name || x.username)
        .filter(Boolean);

    const send = (status, body) => {
      res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify(body));
    };

    (async () => {
      try {
        if (req.method === 'GET' && subpath === 'team') {
          const from = sp.get('from'); const to = sp.get('to');
          if (!from || !to) return send(400, { error: 'from/to 필수 (YYYY-MM-DD)' });
          await withDb(db => {
            const members = activeMembers(db);
            const result = workload.computeRange(db, members, from, to);
            send(200, result);
          });
          return;
        }
        if (req.method === 'GET' && subpath.startsWith('user/')) {
          const memberName = decodeURIComponent(subpath.slice('user/'.length));
          const period = sp.get('period') || 'month';
          const from = sp.get('from'), to = sp.get('to');
          await withDb(db => {
            let fromStr = from, toStr = to;
            if (!fromStr || !toStr) {
              const today = new Date();
              const f = new Date(today);
              if (period === 'week') f.setDate(today.getDate() - 6);
              else if (period === 'quarter') f.setDate(today.getDate() - 89);
              else f.setDate(today.getDate() - 29); // month default 30일
              fromStr = isoOf(f); toStr = isoOf(today);
            }
            const series = workload.computeUserSeries(db, memberName, fromStr, toStr);
            const ym = toStr.slice(0, 7);
            const monthly = workload.computeMonthlyForUser(db, memberName, ym);
            const byType = workload.computeByType(db, { fromStr, toStr, memberName });
            send(200, { member_name: memberName, from: fromStr, to: toStr, series, monthly, by_type: byType });
          });
          return;
        }
        if (req.method === 'GET' && subpath === 'summary') {
          const date = sp.get('date');
          await withDb(db => {
            const members = activeMembers(db);
            send(200, workload.computeSummary(db, members, date));
          });
          return;
        }
        if (req.method === 'GET' && subpath === 'by-type') {
          const fromStr = sp.get('from'), toStr = sp.get('to');
          const scope = sp.get('scope') || 'team';
          const memberName = sp.get('member') || null;
          await withDb(db => {
            const result = workload.computeByType(db, {
              fromStr, toStr,
              memberName: scope === 'me' ? memberName : null,
            });
            send(200, { items: result });
          });
          return;
        }
        if (req.method === 'GET' && subpath === 'alerts') {
          await withDb(db => {
            const members = activeMembers(db);
            send(200, workload.computeAlerts(db, members));
          });
          return;
        }
        if (req.method === 'POST' && subpath === 'recompute') {
          await withDb(db => {
            const members = activeMembers(db);
            const r = workload.recomputeAllCache(db, members);
            writeDb(db);
            send(200, { status: 'ok', ...r });
          });
          return;
        }
        send(404, { error: 'Unknown workload endpoint' });
      } catch (e) {
        send(500, { error: String(e.message || e) });
      }
    })();
    return;
  }

  if (urlPath.startsWith('/tables/') || urlPath === '/tables') {
    const route = parseTablesRoute(urlPath);
    if (!route) {
      res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ error: 'Bad tables path' }));
      return;
    }
    const method = (req.method || 'GET').toUpperCase();
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', () => {
      handleTablesRequest(route, method, Buffer.concat(chunks).toString('utf8'), req.headers)
        .then(out => {
          res.writeHead(out.status, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify(out.body));
        })
        .catch(e => {
          res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify({ error: String(e.message || e) }));
        });
    });
    return;
  }

  let p = urlPath.split('?')[0];
  if (p === '/' || p === '') p = '/login.html';
  const abs = safeResolveStatic(p);
  if (!abs) { res.writeHead(403); res.end(); return; }
  sendStatic(abs, res);
});

server.listen(PORT, HOST, () => {
  const lanIp = Object.values(require('os').networkInterfaces())
    .flat().find(i => i.family === 'IPv4' && !i.internal)?.address || '(LAN IP 미확인)';
  console.log(`\n계리결산팀 운영관리포탈`);
  console.log(`  로컬:  http://127.0.0.1:${PORT}/login.html`);
  console.log(`  팀원:  http://${lanIp}:${PORT}/login.html`);
  console.log(`  DB:    ${DATA_PATH}\n`);

  // ── 자동 무결성 점검 (매일 새벽 4시) ──
  scheduleNextAudit();
  // 서버 시작 직후 sanity 검사 — 마지막 audit이 24시간 이상 전이면 즉시 1회
  setTimeout(maybeRunStartupAudit, 5000);
  // ── 분기 초기화 (매월 1일 00:05) ──
  scheduleNextQuarterCheck();
  // 서버 시작 시 1·4·7·10월 첫 주면 누락분 보강
  setTimeout(maybeRunStartupQuarterReset, 6000);
});

/**
 * 분기 시작일(1·4·7·10월 1일) 자정 직후 엔게이지먼트 포인트만 초기화.
 *  - engagement_points 전부 비움 (work_tasks/daily_work_entries/vacations 등 업무 데이터는 그대로)
 *  - 마지막 실행 시각을 db.meta.last_quarter_reset 에 기록하여 멱등 보장
 *  - 직전 분기 prize_history 는 그대로 유지 (성장상·MVP 계산 기준)
 */
function resetEngagementPointsForNewQuarter(reason) {
  try {
    const db = readDb();
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth() + 1;  // 1~12
    // 분기 시작 월인지 확인
    if (![1, 4, 7, 10].includes(m)) {
      console.log(`[QuarterReset:${reason}] 분기 시작월 아님 (현재 ${y}-${m}) — skip`);
      return;
    }
    // 같은 분기에 이미 초기화했으면 skip (멱등)
    const qKey = `${y}-Q${Math.floor((m - 1) / 3) + 1}`;
    db.meta = db.meta || {};
    if (db.meta.last_quarter_reset === qKey) {
      console.log(`[QuarterReset:${reason}] ${qKey} 이미 초기화 완료 — skip`);
      return;
    }
    const before = (db.engagement_points || []).length;
    db.engagement_points = [];
    db.meta.last_quarter_reset = qKey;
    db.meta.last_quarter_reset_at = Date.now();
    writeDb(db);
    console.log(`[QuarterReset:${reason}] ✓ ${qKey} 시작 — engagement_points ${before}건 초기화 (업무 데이터 보존)`);
  } catch (e) {
    console.error(`[QuarterReset:${reason}] 실패:`, e.message);
  }
}

/**
 * 다음 매월 1일 00:05 에 resetEngagementPointsForNewQuarter 호출.
 *  - 매월 체크하고 분기 시작월이면 초기화. 아니면 그냥 skip.
 *  - audit 4시보다 먼저 돌도록 00:05 로 잡음.
 */
function scheduleNextQuarterCheck() {
  const now = new Date();
  const next = new Date(now.getFullYear(), now.getMonth() + 1, 1, 0, 5, 0); // 다음 달 1일 00:05
  const ms = next - now;
  setTimeout(() => {
    resetEngagementPointsForNewQuarter('scheduled');
    scheduleNextQuarterCheck();
  }, ms);
  console.log(`  QuarterReset: 다음 분기 체크 → ${next.toLocaleString('ko-KR')}`);
}

/**
 * 서버 시작 시 분기 초기화 누락분 보강 (예: 서버가 1/1 자정에 안 떠있어서 놓친 경우)
 */
function maybeRunStartupQuarterReset() {
  try {
    const now = new Date();
    if (![1, 4, 7, 10].includes(now.getMonth() + 1)) return;
    // 분기 첫 주 (1~7일) 안에 서버 시작 시 한 번 보강
    if (now.getDate() > 7) return;
    resetEngagementPointsForNewQuarter('startup');
  } catch (e) {
    console.error('Startup quarter reset 실패:', e.message);
  }
}

/**
 * 다음 새벽 4시에 runAuditAndSave 실행하도록 setTimeout 등록.
 * 실행 후 자기 자신을 다시 호출하여 매일 반복.
 */
function scheduleNextAudit() {
  const now = new Date();
  const next4am = new Date(now);
  next4am.setHours(4, 0, 0, 0);
  if (next4am <= now) next4am.setDate(next4am.getDate() + 1);
  const ms = next4am - now;
  setTimeout(() => {
    runAuditAndSave('scheduled');
    scheduleNextAudit();
  }, ms);
  console.log(`  Audit: 다음 자동 점검 → ${next4am.toLocaleString('ko-KR')}`);
}

/**
 * 서버 시작 시 마지막 audit이 24시간 이상 전이면 즉시 1회 실행.
 */
function maybeRunStartupAudit() {
  try {
    const db = readDb();
    const reports = db.audit_reports || [];
    const latest = reports.length ? reports[reports.length - 1] : null;
    const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000;
    if (!latest || (latest.run_at || 0) < oneDayAgo) {
      runAuditAndSave('startup');
    }
  } catch (e) {
    console.error('Startup audit 실패:', e.message);
  }
}

/**
 * 무결성 점검 실행 + audit_reports 에 저장 + 콘솔 요약 출력.
 * @param {string} trigger - 'scheduled' | 'startup' | 'manual'
 */
function runAuditAndSave(trigger) {
  try {
    const db = readDb();
    // 1차 점검
    const firstReport = runAudit(db);
    // 자동 수정 (사람 판단 불필요 카테고리만)
    const autofix = applyAutoFix(db, firstReport.issues || []);
    // 자동 수정 결과 반영 위해 재점검
    let finalReport = firstReport;
    if (autofix.fixed.length > 0) {
      finalReport = runAudit(db);
    }
    finalReport.trigger = trigger;
    finalReport.autofix = {
      fixed_count: autofix.fixed.length,
      skipped_count: autofix.skipped.length,
      fixed: autofix.fixed,
      skipped: autofix.skipped,
      first_total: firstReport.summary.total_issues,
    };
    if (!Array.isArray(db.audit_reports)) db.audit_reports = [];
    db.audit_reports.push(finalReport);
    if (db.audit_reports.length > 30) {
      db.audit_reports = db.audit_reports.slice(-30);
    }
    writeDb(db);
    console.log(`[Audit:${trigger}] ${finalReport.status} — 최초 ${firstReport.summary.total_issues}건 → 자동수정 ${autofix.fixed.length} / 남음 ${finalReport.summary.total_issues} (high:${finalReport.summary.by_severity.high} medium:${finalReport.summary.by_severity.medium}) / ${finalReport.duration_ms}ms`);
  } catch (e) {
    console.error(`[Audit:${trigger}] 실행 실패:`, e.message);
  }
}

// 외부에서 수동 트리거 가능하게 export (테스트/디버그용)
module.exports = { runAuditAndSave };
