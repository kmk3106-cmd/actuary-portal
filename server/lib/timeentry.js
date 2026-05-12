'use strict';

/**
 * 시간대(time-range) 입력 모듈 — Phase 7
 *
 * 핵심 데이터 구조:
 *   time_entries: [
 *     { date: 'YYYY-MM-DD', start: 'HH:MM', end: 'HH:MM', minutes: int }
 *   ]
 *
 * 정책:
 *  - 30분 단위 (00, 30)
 *  - 자정 넘김 금지
 *  - 표준 업무시간: 09:00~12:00 + 13:00~18:00 (점심 1h 제외, 총 8h)
 *  - 분산 시 종료시각 18:00 기준으로 역산
 */

const bizday = require('./bizday');

const HOURS_PER_DAY = 8;
const DAY_MINUTES = HOURS_PER_DAY * 60;       // 480
const MORNING_MIN = 180;                       // 09~12 = 180분
const AFTERNOON_MIN = 300;                     // 13~18 = 300분
const MORNING_END_M = 12 * 60;                 // 720 (점심 시작)
const AFTERNOON_START_M = 13 * 60;             // 780 (점심 종료)
const AFTERNOON_END_M = 18 * 60;               // 1080
const MORNING_START_M = 9 * 60;                // 540

// ── 시간 헬퍼 ──
function timeToMin(hhmm) {
  const [h, m] = String(hhmm).split(':').map(Number);
  return h * 60 + m;
}

/**
 * [startMin, endMin) 구간과 점심(12:00~13:00) 의 겹침 분 반환.
 * 09:00~18:00 근무 기준, 점심 1h는 업무시간에서 제외.
 */
function lunchOverlap(startMin, endMin) {
  if (endMin <= startMin) return 0;
  return Math.max(0, Math.min(endMin, AFTERNOON_START_M) - Math.max(startMin, MORNING_END_M));
}

/**
 * [startMin, endMin) 의 순수 업무시간(분). 점심 자동 차감.
 */
function netMinutesInRange(startMin, endMin) {
  if (endMin <= startMin) return 0;
  return (endMin - startMin) - lunchOverlap(startMin, endMin);
}
function minToTime(min) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}
function isHalfHour(hhmm) {
  const m = timeToMin(hhmm);
  return m % 30 === 0;
}

/**
 * 한 영업일의 작업 분(minutes ≤ 480)을 09~12 + 13~18 패턴으로 시간대로 변환
 * 종료시각 18:00 기준 역산
 *
 *  ≥480: 09:00~12:00 + 13:00~18:00 (480분 풀)
 *  300<m<480: 점심 후 5h 가득 + 오전 (m-300)분 → 12:00에서 역산
 *  ≤300: 18:00에서 역산 (점심 후만)
 */
function buildDaySegments(dateStr, dayMin) {
  if (dayMin <= 0) return [];
  const segs = [];
  if (dayMin >= DAY_MINUTES) {
    segs.push({ date: dateStr, start: '09:00', end: '12:00', minutes: MORNING_MIN });
    segs.push({ date: dateStr, start: '13:00', end: '18:00', minutes: AFTERNOON_MIN });
    return segs;
  }
  if (dayMin > AFTERNOON_MIN) {
    const morningMin = dayMin - AFTERNOON_MIN;
    const morningStart = minToTime(MORNING_END_M - morningMin);
    segs.push({ date: dateStr, start: morningStart, end: '12:00', minutes: morningMin });
    segs.push({ date: dateStr, start: '13:00', end: '18:00', minutes: AFTERNOON_MIN });
    return segs;
  }
  // ≤300: 18:00에서 역산
  const startM = AFTERNOON_END_M - dayMin;
  // startM이 13:00 미만이면 (즉 dayMin > 300) 위 분기에서 처리됨. 안전 장치.
  const start = minToTime(Math.max(AFTERNOON_START_M, startM));
  segs.push({ date: dateStr, start, end: '18:00', minutes: dayMin });
  return segs;
}

/**
 * 총 분량을 종료일에서 역산하여 영업일별로 분산
 * @param {number} totalMin
 * @param {string} endDateStr 'YYYY-MM-DD'
 * @param {Map} bizMap business_days 인덱스
 * @param {object} opts { maxLookbackDays }
 * @returns time_entries 배열 (시간순 정렬)
 */
function spreadMinutesAcrossBusinessDays(totalMin, endDateStr, bizMap, opts) {
  const maxLookback = (opts && opts.maxLookbackDays) || 30;
  let remaining = Math.max(0, Math.round(totalMin / 30) * 30); // 30분 정렬
  if (remaining === 0) return [];

  const cur = new Date(endDateStr + 'T00:00:00');
  const accumulated = []; // [{date, segs}]
  let safety = 0;

  while (remaining > 0 && safety < maxLookback) {
    const ds = toIso(cur);
    if (bizday.isBusinessDay(ds, bizMap)) {
      const dayMin = Math.min(remaining, DAY_MINUTES);
      const segs = buildDaySegments(ds, dayMin);
      accumulated.push({ date: ds, segs });
      remaining -= dayMin;
    }
    if (remaining > 0) {
      cur.setDate(cur.getDate() - 1);
    }
    safety++;
  }
  // 시간순 정렬 (오래된 일자 → 최신)
  accumulated.sort((a, b) => a.date.localeCompare(b.date));
  const flat = [];
  for (const a of accumulated) flat.push(...a.segs);
  return flat;
}

/**
 * 사용자가 직접 from/to를 명시한 경우 균등 분산
 * (개인 업무 입력에서 시작일/종료일 + 시작시간~종료시간 직접 지정)
 *
 * @param {string} startDate 'YYYY-MM-DD'
 * @param {string} endDate 'YYYY-MM-DD'
 * @param {string} startTime 'HH:MM'
 * @param {string} endTime 'HH:MM'
 * @returns time_entries (단일 일자: 1개, 여러 일자: N개)
 *
 * 정책:
 *  - 단일일자(start==end): { date, start, end, minutes=end-start-lunch }
 *  - 여러일자: 각 일자에 동일한 startTime~endTime 적용 (사용자 입력 시간을 모든 날에 동일 적용).
 *    점심(12:00~13:00)은 자동 차감.
 */
function buildEntriesFromRange(startDate, endDate, startTime, endTime) {
  if (!startDate || !endDate || !startTime || !endTime) {
    throw new Error('startDate/endDate/startTime/endTime 필수');
  }
  if (!isHalfHour(startTime) || !isHalfHour(endTime)) {
    throw new Error('30분 단위만 허용 (예: 09:00, 09:30)');
  }
  const sM = timeToMin(startTime), eM = timeToMin(endTime);
  if (sM >= eM) throw new Error('시작시간 ≥ 종료시간');
  if (startDate > endDate) throw new Error('시작일이 종료일보다 늦음');
  const dailyMin = netMinutesInRange(sM, eM);
  if (startDate === endDate) {
    return [{ date: startDate, start: startTime, end: endTime, minutes: dailyMin }];
  }
  // 여러 일자: 각 날짜에 startTime~endTime 동일 적용
  const out = [];
  const cur = new Date(startDate + 'T00:00:00');
  const end = new Date(endDate + 'T00:00:00');
  while (cur <= end) {
    out.push({
      date: toIso(cur), start: startTime, end: endTime,
      minutes: dailyMin,
    });
    cur.setDate(cur.getDate() + 1);
  }
  return out;
}

/**
 * time_entries 1건 검증 (작업당 행)
 * 반환: { ok: bool, errors: [], warnings: [] }
 */
function validateEntry(e, bizMap) {
  const errors = [], warnings = [];
  if (!e || !e.date || !e.start || !e.end) {
    errors.push('date/start/end 필수');
    return { ok: false, errors, warnings };
  }
  if (!isHalfHour(e.start) || !isHalfHour(e.end)) {
    errors.push('30분 단위만 허용');
  }
  const sM = timeToMin(e.start), eM = timeToMin(e.end);
  if (sM >= eM) errors.push('시작 ≥ 종료');
  if (eM > 24 * 60) errors.push('자정 넘김 금지');
  // 영업일 외 입력
  if (bizMap && !bizday.isBusinessDay(e.date, bizMap)) {
    warnings.push('비영업일 입력 (주말/공휴일)');
  }
  // 업무시간 외
  if (sM < MORNING_START_M || eM > AFTERNOON_END_M) {
    warnings.push('업무시간(09:00~18:00) 외 입력');
  }
  return { ok: errors.length === 0, errors, warnings };
}

/**
 * time_entries 충돌 체크 (동일 사용자, 동일 일자, 시간대 겹침)
 * @returns 겹침 entries 배열
 */
function findOverlaps(db, memberName, candidates, excludeEntryId) {
  const conflicts = [];
  const all = db.daily_work_entries || [];
  for (const cand of candidates) {
    for (const dwe of all) {
      if (dwe.member_name !== memberName) continue;
      if (excludeEntryId && dwe.id === excludeEntryId) continue;
      const others = Array.isArray(dwe.time_entries) ? dwe.time_entries : [];
      for (const o of others) {
        if (o.date !== cand.date) continue;
        const oS = timeToMin(o.start), oE = timeToMin(o.end);
        const cS = timeToMin(cand.start), cE = timeToMin(cand.end);
        if (cS < oE && cE > oS) {
          conflicts.push({
            against_entry_id: dwe.id,
            against_label: dwe.task_label,
            date: cand.date,
            self: { start: cand.start, end: cand.end },
            other: { start: o.start, end: o.end },
          });
        }
      }
    }
  }
  return conflicts;
}

/**
 * time_entries로부터 total_minutes / start_date / end_date 자동 계산
 */
function summarize(timeEntries) {
  const arr = Array.isArray(timeEntries) ? timeEntries.filter(e => e && e.date) : [];
  if (!arr.length) return { total_minutes: 0, start_date: null, end_date: null, time_entry_mode: 'single' };
  const sorted = [...arr].sort((a, b) =>
    a.date.localeCompare(b.date) || timeToMin(a.start) - timeToMin(b.start)
  );
  const dates = new Set(arr.map(e => e.date));
  const total = arr.reduce((s, e) => s + (Number(e.minutes) || 0), 0);
  return {
    total_minutes: total,
    start_date: sorted[0].date,
    end_date: sorted[sorted.length - 1].date,
    time_entry_mode: dates.size === 1 ? 'single' : 'multi',
  };
}

function toIso(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

module.exports = {
  HOURS_PER_DAY,
  DAY_MINUTES,
  MORNING_MIN,
  AFTERNOON_MIN,
  buildDaySegments,
  spreadMinutesAcrossBusinessDays,
  buildEntriesFromRange,
  validateEntry,
  findOverlaps,
  summarize,
  timeToMin,
  minToTime,
  isHalfHour,
  lunchOverlap,
  netMinutesInRange,
};
