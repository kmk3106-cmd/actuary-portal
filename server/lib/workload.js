'use strict';

/**
 * 업무량(부하율) 계산 모듈
 *
 * 입력 데이터: db.daily_work_entries — { member_name, work_date, duration_minutes, ... }
 * 산출:
 *  - 일 부하율 (load_ratio) = total_min / (HOURS_PER_DAY × 60)
 *  - 월 부하율 = 누적 분 / (월 영업일 × HOURS_PER_DAY × 60)
 *  - status: empty / idle / normal / overload (임계값은 workload_thresholds 기반)
 *  - 과중/유휴 연속 영업일 카운트
 */

const bizday = require('./bizday');

function getThresholds(db) {
  const t = (db.workload_thresholds || [])[0] || {};
  return {
    hoursPerDay: t.hours_per_day ?? bizday.HOURS_PER_DAY,
    overloadPct: t.overload_pct ?? 120,
    idlePct: t.idle_pct ?? 70,
    overloadConsecDays: t.overload_consec_days ?? 3,
    idleConsecDays: t.idle_consec_days ?? 5,
  };
}

function classifyStatus(loadPct, thr) {
  if (loadPct === 0) return 'empty';
  if (loadPct >= thr.overloadPct) return 'overload';
  if (loadPct < thr.idlePct) return 'idle';
  return 'normal';
}

/**
 * 특정 (member, date)의 일별 부하율 계산
 * 결과: { member_name, work_date, total_minutes, load_pct, status, is_business_day, holiday_name }
 */
function computeDayLoad(db, memberName, dateStr, thr, bizMap) {
  // Phase 7-1: time_entries 우선, 없으면 legacy work_date+duration_minutes 사용
  let total_minutes = 0;
  for (const e of (db.daily_work_entries || [])) {
    if (e.member_name !== memberName) continue;
    if (Array.isArray(e.time_entries) && e.time_entries.length > 0) {
      for (const te of e.time_entries) {
        if (te && te.date === dateStr) total_minutes += (Number(te.minutes) || 0);
      }
    } else if (e.work_date === dateStr) {
      total_minutes += (Number(e.duration_minutes) || 0);
    }
  }
  const dailyMin = thr.hoursPerDay * 60;
  const load_pct = dailyMin > 0 ? (total_minutes / dailyMin) * 100 : 0;
  const isBiz = bizday.isBusinessDay(dateStr, bizMap);
  const bd = bizMap.get(dateStr);
  return {
    member_name: memberName,
    work_date: dateStr,
    total_minutes,
    load_pct: Math.round(load_pct * 10) / 10,
    status: classifyStatus(load_pct, thr),
    is_business_day: isBiz,
    holiday_name: bd ? (bd.holiday_name || '') : '',
    day_type: bd ? bd.day_type : (bizday.isWeekend(dateStr) ? 'weekend' : 'workday'),
  };
}

/**
 * 기간 내 (member, date) 매트릭스 — 팀 히트맵용
 * 결과: { dates: [...], members: [...], cells: { [memberName]: { [date]: cellObj } } }
 */
function computeRange(db, memberNames, fromStr, toStr) {
  const thr = getThresholds(db);
  const bizMap = bizday.indexBusinessDays(db.business_days);
  const dates = [];
  const cur = new Date(fromStr + 'T00:00:00');
  const end = new Date(toStr + 'T00:00:00');
  while (cur <= end) {
    dates.push(toIso(cur));
    cur.setDate(cur.getDate() + 1);
  }
  const cells = {};
  for (const m of memberNames) {
    cells[m] = {};
    for (const d of dates) {
      cells[m][d] = computeDayLoad(db, m, d, thr, bizMap);
    }
  }
  return { dates, members: memberNames, cells };
}

/**
 * 한 사람의 시계열
 */
function computeUserSeries(db, memberName, fromStr, toStr) {
  const thr = getThresholds(db);
  const bizMap = bizday.indexBusinessDays(db.business_days);
  const series = [];
  const cur = new Date(fromStr + 'T00:00:00');
  const end = new Date(toStr + 'T00:00:00');
  while (cur <= end) {
    series.push(computeDayLoad(db, memberName, toIso(cur), thr, bizMap));
    cur.setDate(cur.getDate() + 1);
  }
  return series;
}

/**
 * 월별 누적 부하율 (MM 환산 포함)
 */
function computeMonthlyForUser(db, memberName, yearMonth) {
  const thr = getThresholds(db);
  const bizMap = bizday.indexBusinessDays(db.business_days);
  const [yStr, mStr] = yearMonth.split('-');
  const y = +yStr, m = +mStr;
  const total = bizday.fmtDate ? null : null; // unused, remove
  const days = bizday.getBusinessDaysInMonth(yearMonth, bizMap);
  const stdHours = days * thr.hoursPerDay;
  const stdMin = stdHours * 60;

  const monthFrom = `${yearMonth}-01`;
  const lastDay = new Date(y, m, 0).getDate();
  const monthTo = `${yearMonth}-${String(lastDay).padStart(2, '0')}`;
  // Phase 7-1: time_entries 우선
  let total_minutes = 0;
  for (const e of (db.daily_work_entries || [])) {
    if (e.member_name !== memberName) continue;
    if (Array.isArray(e.time_entries) && e.time_entries.length > 0) {
      for (const te of e.time_entries) {
        if (te && te.date >= monthFrom && te.date <= monthTo) total_minutes += (Number(te.minutes) || 0);
      }
    } else if (e.work_date >= monthFrom && e.work_date <= monthTo) {
      total_minutes += (Number(e.duration_minutes) || 0);
    }
  }

  // 지나간 영업일까지의 부분 표준시간 (현재까지 페이스 계산용)
  const today = toIso(new Date());
  const todayInMonth = today >= monthFrom && today <= monthTo;
  let elapsedBizDays = 0;
  if (todayInMonth) {
    for (let d = 1; d <= Math.min(lastDay, parseInt(today.slice(8, 10), 10)); d++) {
      if (bizday.isBusinessDay(`${yearMonth}-${String(d).padStart(2, '0')}`, bizMap)) elapsedBizDays++;
    }
  } else if (today > monthTo) {
    elapsedBizDays = days;
  }

  const expectedSoFarMin = elapsedBizDays * thr.hoursPerDay * 60;
  const paceMM = expectedSoFarMin > 0
    ? (total_minutes / expectedSoFarMin) // 1.0이면 표준 페이스
    : null;

  return {
    member_name: memberName,
    year_month: yearMonth,
    business_days: days,
    standard_hours: stdHours,
    elapsed_business_days: elapsedBizDays,
    total_minutes,
    total_hours: Math.round((total_minutes / 60) * 10) / 10,
    mm: stdMin > 0 ? Math.round((total_minutes / stdMin) * 100) / 100 : 0,
    load_pct: stdMin > 0 ? Math.round((total_minutes / stdMin) * 1000) / 10 : 0,
    pace_mm: paceMM != null ? Math.round(paceMM * 100) / 100 : null,
  };
}

/**
 * 업무 유형별 분포 (도넛 차트용)
 */
function computeByType(db, opts) {
  const { fromStr, toStr, memberName } = opts || {};
  const cats = {};
  for (const c of (db.task_categories || [])) cats[c.id] = c.label;
  const bucket = {};
  for (const e of (db.daily_work_entries || [])) {
    if (memberName && e.member_name !== memberName) continue;
    const key = e.task_category_id || 'uncategorized';
    const label = cats[key] || e.task_label || '미분류';
    // Phase 7-1: time_entries 기반 일자별 분리 합산
    if (Array.isArray(e.time_entries) && e.time_entries.length > 0) {
      for (const te of e.time_entries) {
        if (!te || !te.date) continue;
        if (fromStr && te.date < fromStr) continue;
        if (toStr && te.date > toStr) continue;
        if (!bucket[label]) bucket[label] = 0;
        bucket[label] += Number(te.minutes) || 0;
      }
    } else {
      if (fromStr && e.work_date < fromStr) continue;
      if (toStr && e.work_date > toStr) continue;
      if (!bucket[label]) bucket[label] = 0;
      bucket[label] += Number(e.duration_minutes) || 0;
    }
  }
  return Object.entries(bucket)
    .map(([label, minutes]) => ({ label, minutes, hours: Math.round((minutes / 60) * 10) / 10 }))
    .sort((a, b) => b.minutes - a.minutes);
}

/**
 * 현재 활성 알림: 과중/유휴 연속, 어제 미입력
 */
function computeAlerts(db, memberNames) {
  const thr = getThresholds(db);
  const bizMap = bizday.indexBusinessDays(db.business_days);
  const today = new Date();
  const alerts = { overload: [], idle: [], empty_yesterday: [] };

  // 어제 영업일 찾기
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  while (!bizday.isBusinessDay(toIso(yesterday), bizMap)) {
    yesterday.setDate(yesterday.getDate() - 1);
  }
  const yesterdayStr = toIso(yesterday);

  // 최근 N영업일 슬라이스 만들기 (가장 큰 연속 카운트만큼)
  const lookback = Math.max(thr.overloadConsecDays, thr.idleConsecDays) + 5;
  const recentBizDays = [];
  const cur = new Date(today);
  while (recentBizDays.length < lookback) {
    if (bizday.isBusinessDay(toIso(cur), bizMap)) recentBizDays.push(toIso(cur));
    cur.setDate(cur.getDate() - 1);
  }
  recentBizDays.reverse(); // 오래된→최신

  for (const m of memberNames) {
    // 어제 미입력
    const ydEntries = (db.daily_work_entries || []).filter(
      e => e.member_name === m && e.work_date === yesterdayStr
    );
    if (ydEntries.length === 0) {
      alerts.empty_yesterday.push({ member_name: m, date: yesterdayStr });
    }
    // 영업일 연속 과중/유휴
    const dayLoads = recentBizDays.map(d => computeDayLoad(db, m, d, thr, bizMap));
    let overloadStreak = 0, idleStreak = 0;
    for (let i = dayLoads.length - 1; i >= 0; i--) {
      const s = dayLoads[i].status;
      if (s === 'overload') { overloadStreak++; }
      else break;
    }
    for (let i = dayLoads.length - 1; i >= 0; i--) {
      const s = dayLoads[i].status;
      if (s === 'idle') { idleStreak++; }
      else break;
    }
    if (overloadStreak >= thr.overloadConsecDays) {
      alerts.overload.push({ member_name: m, days: overloadStreak });
    }
    if (idleStreak >= thr.idleConsecDays) {
      alerts.idle.push({ member_name: m, days: idleStreak });
    }
  }
  return alerts;
}

/**
 * 상단 KPI 카드 (이번 주 표준대비 / 과중·유휴·미입력 인원수)
 */
function computeSummary(db, memberNames, dateStr) {
  const thr = getThresholds(db);
  const bizMap = bizday.indexBusinessDays(db.business_days);
  // 이번 주: 월요일 ~ 일요일
  const today = dateStr ? new Date(dateStr + 'T00:00:00') : new Date();
  const dow = today.getDay() === 0 ? 7 : today.getDay(); // Sun=7, Mon=1
  const monday = new Date(today);
  monday.setDate(today.getDate() - (dow - 1));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);

  // 이번 주 팀 누적
  let weekTeamMin = 0;
  let weekStdMin = 0;
  for (const m of memberNames) {
    const cur = new Date(monday);
    while (cur <= sunday) {
      const ds = toIso(cur);
      if (bizday.isBusinessDay(ds, bizMap)) {
        weekStdMin += thr.hoursPerDay * 60;
        const entries = (db.daily_work_entries || []).filter(
          e => e.member_name === m && e.work_date === ds
        );
        weekTeamMin += entries.reduce((s, e) => s + (Number(e.duration_minutes) || 0), 0);
      }
      cur.setDate(cur.getDate() + 1);
    }
  }

  const alerts = computeAlerts(db, memberNames);
  return {
    week: {
      from: toIso(monday),
      to: toIso(sunday),
      team_total_minutes: weekTeamMin,
      team_total_hours: Math.round((weekTeamMin / 60) * 10) / 10,
      team_standard_minutes: weekStdMin,
      team_standard_hours: Math.round((weekStdMin / 60) * 10) / 10,
      load_pct: weekStdMin > 0 ? Math.round((weekTeamMin / weekStdMin) * 1000) / 10 : 0,
    },
    overload_count: alerts.overload.length,
    idle_count: alerts.idle.length,
    empty_yesterday_count: alerts.empty_yesterday.length,
  };
}

/**
 * workload_daily_cache 업데이트 (단일 user-date 또는 전체)
 */
function upsertCacheRow(db, memberName, dateStr) {
  const thr = getThresholds(db);
  const bizMap = bizday.indexBusinessDays(db.business_days);
  const result = computeDayLoad(db, memberName, dateStr, thr, bizMap);
  const id = `wlc_${memberName}_${dateStr}`;
  const idx = (db.workload_daily_cache || []).findIndex(r => r.id === id);
  const row = {
    id,
    member_name: memberName,
    work_date: dateStr,
    total_minutes: result.total_minutes,
    load_pct: result.load_pct,
    status: result.status,
    computed_at: Date.now(),
  };
  if (idx >= 0) db.workload_daily_cache[idx] = { ...db.workload_daily_cache[idx], ...row };
  else db.workload_daily_cache.push(row);
  return row;
}

function recomputeAllCache(db, memberNames) {
  // 모든 daily_work_entries에 대해 (member, date) 캐시 재생성
  const seen = new Set();
  for (const e of (db.daily_work_entries || [])) {
    const key = `${e.member_name}|${e.work_date}`;
    if (seen.has(key)) continue;
    seen.add(key);
    upsertCacheRow(db, e.member_name, e.work_date);
  }
  // 팀원 목록 기준 비어있는 데이터도 처리할 필요는 X (조회 시 동적 계산됨)
  return { cached: seen.size };
}

// ── helpers ──
function toIso(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

module.exports = {
  getThresholds,
  classifyStatus,
  computeDayLoad,
  computeRange,
  computeUserSeries,
  computeMonthlyForUser,
  computeByType,
  computeAlerts,
  computeSummary,
  upsertCacheRow,
  recomputeAllCache,
};
