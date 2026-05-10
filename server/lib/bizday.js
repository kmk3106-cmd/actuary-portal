'use strict';

/**
 * 영업일 유틸 모듈
 *
 * 정책:
 *  - 기본: 토/일은 비영업일, 평일은 영업일
 *  - 예외: business_days 테이블의 항목이 우선
 *      is_business_day=false (휴일) — 예: 공휴일, 회사휴무
 *      is_business_day=true (영업일 강제) — 예: 토요근무
 *  - business_days 미등록 평일은 영업일
 */

const HOURS_PER_DAY = 8;

function isWeekend(dateStr) {
  const d = new Date(dateStr + 'T00:00:00');
  const dow = d.getDay();
  return dow === 0 || dow === 6;
}

/**
 * @param {string} dateStr 'YYYY-MM-DD'
 * @param {Map<string, {is_business_day:boolean}>} bizMap business_days 인덱스 (date → row)
 */
function isBusinessDay(dateStr, bizMap) {
  const override = bizMap && bizMap.get(dateStr);
  if (override && typeof override.is_business_day === 'boolean') {
    return override.is_business_day;
  }
  return !isWeekend(dateStr);
}

function pad2(n) { return String(n).padStart(2, '0'); }

function fmtDate(year, month, day) {
  return `${year}-${pad2(month)}-${pad2(day)}`;
}

function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

/**
 * 'YYYY-MM' 문자열의 영업일 수
 */
function getBusinessDaysInMonth(yearMonth, bizMap) {
  const [yStr, mStr] = yearMonth.split('-');
  const year = +yStr, month = +mStr;
  const total = daysInMonth(year, month);
  let count = 0;
  for (let d = 1; d <= total; d++) {
    if (isBusinessDay(fmtDate(year, month, d), bizMap)) count++;
  }
  return count;
}

/**
 * 'YYYY-MM' 문자열의 표준 근무시간 (영업일 × HOURS_PER_DAY)
 */
function getStandardHoursForMonth(yearMonth, bizMap) {
  return getBusinessDaysInMonth(yearMonth, bizMap) * HOURS_PER_DAY;
}

/**
 * 시작일부터 N영업일을 찾아 반환 (N=1이면 첫 영업일)
 */
function getNthBizDayOfMonth(year, month, n, bizMap) {
  const total = daysInMonth(year, month);
  let count = 0;
  for (let d = 1; d <= total; d++) {
    const ds = fmtDate(year, month, d);
    if (isBusinessDay(ds, bizMap) && ++count === n) return ds;
  }
  return null;
}

/**
 * 두 영업일 사이의 영업일 수 (시작일·종료일 양 끝 포함)
 */
function countBusinessDaysBetween(fromStr, toStr, bizMap) {
  const from = new Date(fromStr + 'T00:00:00');
  const to = new Date(toStr + 'T00:00:00');
  if (from > to) return 0;
  let count = 0;
  const cur = new Date(from);
  while (cur <= to) {
    const y = cur.getFullYear();
    const m = cur.getMonth() + 1;
    const d = cur.getDate();
    if (isBusinessDay(fmtDate(y, m, d), bizMap)) count++;
    cur.setDate(cur.getDate() + 1);
  }
  return count;
}

/**
 * 특정 일자에서 N영업일 전/후 (음수=전, 양수=후, 0=자기 자신이 영업일이면 그대로)
 * 자기 자신이 비영업일이면 다음 영업일로 보정 (양수 방향) 또는 이전 영업일 (음수 방향)
 */
function offsetBusinessDays(dateStr, offset, bizMap) {
  const d = new Date(dateStr + 'T00:00:00');
  if (offset === 0) {
    while (!isBusinessDay(toIso(d), bizMap)) d.setDate(d.getDate() + 1);
    return toIso(d);
  }
  const step = offset > 0 ? 1 : -1;
  let remaining = Math.abs(offset);
  while (remaining > 0) {
    d.setDate(d.getDate() + step);
    if (isBusinessDay(toIso(d), bizMap)) remaining--;
  }
  return toIso(d);
}

function toIso(d) {
  return fmtDate(d.getFullYear(), d.getMonth() + 1, d.getDate());
}

/**
 * (year_month) 캐시 행 생성
 */
function buildMonthlyCacheRow(yearMonth, bizMap) {
  const days = getBusinessDaysInMonth(yearMonth, bizMap);
  return {
    id: yearMonth,
    year_month: yearMonth,
    business_day_count: days,
    standard_hours: days * HOURS_PER_DAY,
    computed_at: Date.now(),
  };
}

/**
 * 주어진 연도 범위의 모든 'YYYY-MM' 캐시 행 일괄 생성
 */
function buildMonthlyCacheRange(yearFrom, yearTo, bizMap) {
  const out = [];
  for (let y = yearFrom; y <= yearTo; y++) {
    for (let m = 1; m <= 12; m++) {
      out.push(buildMonthlyCacheRow(`${y}-${pad2(m)}`, bizMap));
    }
  }
  return out;
}

/**
 * business_days 배열을 date → row Map 으로 인덱싱
 */
function indexBusinessDays(rows) {
  const m = new Map();
  for (const r of rows || []) {
    if (r && r.calendar_date) m.set(r.calendar_date, r);
  }
  return m;
}

module.exports = {
  HOURS_PER_DAY,
  isWeekend,
  isBusinessDay,
  getBusinessDaysInMonth,
  getStandardHoursForMonth,
  getNthBizDayOfMonth,
  countBusinessDaysBetween,
  offsetBusinessDays,
  buildMonthlyCacheRow,
  buildMonthlyCacheRange,
  indexBusinessDays,
  fmtDate,
  pad2,
};
