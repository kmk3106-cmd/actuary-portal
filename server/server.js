'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFile } = require('child_process');
const bizday = require('./lib/bizday');
const workload = require('./lib/workload');

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
    'issue_categories'
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

function handleTablesRequest(route, method, bodyStr, reqHeaders) {
  return withDb(db => {
    const table = route.table;
    if (!Object.prototype.hasOwnProperty.call(db, table)) {
      return { status: 404, body: { error: `Unknown table: ${table}` } };
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
      const created = { ...body, id, created_at: now(), updated_at: now() };
      db[table] = [...collection, created];
      // business_days 변경 → 월별 캐시 재계산
      if (table === 'business_days' && created.calendar_date) {
        const y = parseInt(created.calendar_date.slice(0, 4), 10);
        recomputeMonthlyCache(db, [y]);
      }
      // daily_work_entries 변경 → workload_daily_cache 재계산
      if (table === 'daily_work_entries' && created.member_name && created.work_date) {
        workload.upsertCacheRow(db, created.member_name, created.work_date);
      }
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
      const updated = {
        ...before, ...body, id: before.id,
        ...(table === 'kb_documents' ? { version: nextVersion } : {}),
        updated_at: now(),
      };
      db[table][idx] = updated;
      if (table === 'business_days' && updated.calendar_date) {
        const y = parseInt(updated.calendar_date.slice(0, 4), 10);
        recomputeMonthlyCache(db, [y]);
      }
      if (table === 'daily_work_entries') {
        // 일자나 멤버가 바뀌었으면 양쪽 모두 재계산
        if (before.member_name && before.work_date) {
          workload.upsertCacheRow(db, before.member_name, before.work_date);
        }
        if (updated.member_name && updated.work_date) {
          workload.upsertCacheRow(db, updated.member_name, updated.work_date);
        }
      }
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
      if (table === 'daily_work_entries' && removed && removed.member_name && removed.work_date) {
        workload.upsertCacheRow(db, removed.member_name, removed.work_date);
      }
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
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
    fs.createReadStream(absPath).pipe(res);
  });
}

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PUT,PATCH,DELETE,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  const urlPath = req.url || '/';

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
});
