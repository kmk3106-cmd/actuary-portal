'use strict';
/**
 * 규정 개정 자동 수집 (docs/02_규정개정이력_구축지시서.md §6)
 *
 *  - 수집원 정의: config/reg_sources.json (선택자·키워드를 코드에 박지 않는다 — 규칙 2)
 *      type "law_api"  : 국가법령정보 공개 API (행정규칙 목록 조회)  — 인증키 env LAW_API_KEY
 *      type "html_list": 공고 목록 페이지 (정규식 선택자)          — robots/약관 확인 후 enabled
 *  - 결과는 reg_inbox 에 state:"신규" 로만 넣는다. reg_items 에 자동 등록하지 않는다.
 *  - 중복은 hash(source|url|title|date) 로 거른다. 무시(state:"무시")한 건도 다시 올라오지 않는다.
 *  - 실패는 조용히 넘어가지 않는다 → runs[].errors 에 남겨 수집함 상단에 표시.
 *
 *  외부 호출은 서버에서만 한다(브라우저 CORS). 타임아웃 기본 10초, 요청 간격 기본 2초.
 */
const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const crypto = require('crypto');

const DEFAULT_TIMEOUT_MS = 10000;
const DEFAULT_DELAY_MS = 2000;
const MAX_RUNS_KEPT = 30;
const MAX_REDIRECTS = 3;
const USER_AGENT = process.env.REG_COLLECT_UA || 'ActuaryPortal-RegCollector/1.0 (+portal.kkuks.com)';
const LAW_API_BASE = (process.env.LAW_API_BASE || 'https://www.law.go.kr').replace(/\/+$/, '');
const LAW_API_KEY = process.env.LAW_API_KEY || '';
const SOURCES_PATH = process.env.REG_SOURCES_PATH || path.join(__dirname, '..', '..', 'config', 'reg_sources.json');

// 파일 다운로드 허용 호스트 (SSRF 방지) — LAW_API_BASE 호스트는 테스트용으로 자동 포함
const ALLOWED_FILE_HOSTS = new Set(
  (process.env.REG_FILE_HOSTS || 'www.law.go.kr,law.go.kr,www.fss.or.kr,fss.or.kr,www.fsc.go.kr,fsc.go.kr,opinion.lawmaking.go.kr')
    .split(',').map(s => s.trim()).filter(Boolean)
);
try { ALLOWED_FILE_HOSTS.add(new URL(LAW_API_BASE).host); } catch (_) { /* ignore */ }

const sleep = ms => new Promise(r => setTimeout(r, ms));
const sha1 = s => 'sha1:' + crypto.createHash('sha1').update(String(s)).digest('hex');

function loadSources() {
  try {
    const raw = JSON.parse(fs.readFileSync(SOURCES_PATH, 'utf8'));
    return Object.entries(raw)
      .filter(([key, v]) => !key.startsWith('_') && v && typeof v === 'object')   // "_readme" 같은 설명 키 제외
      .map(([key, v]) => ({ key, ...v }));
  } catch (e) {
    return [];
  }
}

/** 수집원 상태 요약 (화면 표시용) */
function describeSources() {
  return loadSources().map(s => ({
    key: s.key, label: s.label || s.key, type: s.type, enabled: s.enabled !== false,
    ready: s.type === 'law_api' ? !!LAW_API_KEY : true,
    note: s.type === 'law_api' && !LAW_API_KEY ? 'LAW_API_KEY 환경변수 미설정 — open.law.go.kr 인증키 신청 후 설정' : '',
  }));
}

/** 소형 HTTP GET (리다이렉트 ≤3, 타임아웃). 응답 { status, headers, body(Buffer) } */
function httpGet(url, { timeoutMs = DEFAULT_TIMEOUT_MS, redirects = 0 } = {}) {
  return new Promise((resolve, reject) => {
    let u;
    try { u = new URL(url); } catch (e) { return reject(new Error('잘못된 URL: ' + url)); }
    const mod = u.protocol === 'https:' ? https : http;
    const req = mod.get(u, { headers: { 'User-Agent': USER_AGENT, 'Accept': '*/*' }, timeout: timeoutMs }, res => {
      const st = res.statusCode || 0;
      if ([301, 302, 303, 307, 308].includes(st) && res.headers.location && redirects < MAX_REDIRECTS) {
        res.resume();
        return resolve(httpGet(new URL(res.headers.location, u).toString(), { timeoutMs, redirects: redirects + 1 }));
      }
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: st, headers: res.headers, body: Buffer.concat(chunks) }));
      res.on('error', reject);
    });
    req.on('timeout', () => req.destroy(new Error('timeout ' + timeoutMs + 'ms')));
    req.on('error', reject);
  });
}

/** 응답 객체에서 "이름 필드가 있는 첫 배열" 을 찾는다 — API 응답 키가 바뀌어도 버티게 */
function findRecordArray(obj, depth = 0) {
  if (!obj || depth > 4) return null;
  if (Array.isArray(obj)) return obj.length && typeof obj[0] === 'object' ? obj : null;
  if (typeof obj !== 'object') return null;
  for (const v of Object.values(obj)) {
    const r = findRecordArray(v, depth + 1);
    if (r) return r;
  }
  return null;
}
const pick = (o, keys) => { for (const k of keys) { if (o && o[k] != null && String(o[k]).trim() !== '') return String(o[k]).trim(); } return ''; };
function normDate(s) {
  const d = String(s || '').replace(/[^\d]/g, '');
  return d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : (s || '');
}

/** A. 국가법령정보 공개 API — 행정규칙 목록 */
async function collectLawApi(src, log) {
  if (!LAW_API_KEY) throw new Error('LAW_API_KEY 미설정');
  const out = [];
  const queries = Array.isArray(src.queries) ? src.queries : [];
  const target = src.target || 'admrul';
  const display = Number(src.display) || 20;
  for (let i = 0; i < queries.length; i++) {
    const q = queries[i];
    const url = `${LAW_API_BASE}/DRF/lawSearch.do?OC=${encodeURIComponent(LAW_API_KEY)}&target=${encodeURIComponent(target)}&type=JSON&display=${display}&query=${encodeURIComponent(q)}`;
    const r = await httpGet(url, { timeoutMs: Number(src.timeout_ms) || DEFAULT_TIMEOUT_MS });
    if (r.status !== 200) throw new Error(`HTTP ${r.status} (query=${q})`);
    let json;
    try { json = JSON.parse(r.body.toString('utf8')); } catch (e) { throw new Error(`JSON 파싱 실패 (query=${q})`); }
    const rows = findRecordArray(json) || [];
    for (const row of rows) {
      const title = pick(row, ['행정규칙명', '법령명한글', '법령명', 'title']);
      if (!title) continue;
      const kind = pick(row, ['제개정구분명', '제개정구분']);
      const link = pick(row, ['행정규칙상세링크', '법령상세링크', 'link']);
      out.push({
        title: kind ? `${title} (${kind})` : title,
        url: link ? new URL(link, LAW_API_BASE).toString() : '',
        published_at: normDate(pick(row, ['발령일자', '공포일자', '생성일자'])),
        effective_at: normDate(pick(row, ['시행일자'])),
        reg_name: title,
        authority: pick(row, ['소관부처명', '소관부처']),
        serial: pick(row, ['행정규칙일련번호', '법령일련번호', '행정규칙ID', '법령ID']),
        raw: row,
      });
    }
    log(`law_api query="${q}" → ${rows.length}건`);
    if (i < queries.length - 1) await sleep(Number(src.delay_ms) || DEFAULT_DELAY_MS);
  }
  return out;
}

/** B. 공고 목록 페이지 — 정규식 선택자 (config 에서 정의) */
async function collectHtmlList(src, log) {
  if (!src.list_url || !src.row) throw new Error('list_url / row 선택자 필요');
  const r = await httpGet(src.list_url, { timeoutMs: Number(src.timeout_ms) || DEFAULT_TIMEOUT_MS });
  if (r.status !== 200) throw new Error(`HTTP ${r.status}`);
  const html = r.body.toString('utf8');
  const rowRe = new RegExp(src.row, 'gs');
  const titleRe = src.title ? new RegExp(src.title, 's') : null;
  const linkRe = src.link ? new RegExp(src.link, 's') : null;
  const dateRe = src.date ? new RegExp(src.date, 's') : null;
  const keywords = Array.isArray(src.keywords) ? src.keywords : [];
  const out = [];
  let m; let total = 0;
  while ((m = rowRe.exec(html)) !== null) {
    total++;
    const block = m[0];
    const title = titleRe ? ((block.match(titleRe) || [])[1] || '').replace(/<[^>]+>/g, '').trim() : '';
    if (!title) continue;
    if (keywords.length && !keywords.some(k => title.includes(k))) continue;
    const href = linkRe ? ((block.match(linkRe) || [])[1] || '') : '';
    const date = dateRe ? ((block.match(dateRe) || [])[1] || '') : '';
    out.push({ title, url: href ? new URL(href, src.list_url).toString() : '', published_at: normDate(date), raw: { block: block.slice(0, 2000) } });
  }
  if (total === 0) throw new Error('row 선택자에 걸린 행이 0건 — 사이트 개편 여부 확인');
  log(`html_list ${src.key} → ${total}행 중 ${out.length}건 키워드 일치`);
  return out;
}

/**
 * 전체 수집 실행. db 는 호출자가 readDb() 로 넘기고 결과를 writeDb 한다.
 * @returns {{ run: object, added: number }}
 */
async function runCollect(db, { trigger = 'manual' } = {}) {
  if (!Array.isArray(db.reg_inbox)) db.reg_inbox = [];
  if (!Array.isArray(db.reg_collect_runs)) db.reg_collect_runs = [];
  const existing = new Set(db.reg_inbox.map(x => x.hash));
  const logs = []; const errors = [];
  const log = s => logs.push(s);
  let added = 0, seen = 0;
  const sources = loadSources().filter(s => s.enabled !== false);
  if (!sources.length) errors.push({ source: '-', message: '활성화된 수집원이 없습니다 (config/reg_sources.json)' });

  for (let i = 0; i < sources.length; i++) {
    const src = sources[i];
    try {
      const items = src.type === 'law_api' ? await collectLawApi(src, log)
        : src.type === 'html_list' ? await collectHtmlList(src, log)
        : (() => { throw new Error('알 수 없는 type: ' + src.type); })();
      for (const it of items) {
        seen++;
        const hash = sha1(`${src.key}|${it.url || ''}|${it.title}|${it.published_at || ''}`);
        if (existing.has(hash)) continue;
        existing.add(hash);
        db.reg_inbox.push({
          id: 'rin_' + crypto.randomBytes(8).toString('hex'),
          source: src.key, source_label: src.label || src.key,
          fetched_at: Date.now(),
          title: it.title, url: it.url || '', published_at: it.published_at || '',
          effective_at: it.effective_at || '', reg_name: it.reg_name || '', authority: it.authority || '',
          serial: it.serial || '',
          raw: it.raw || {}, hash, state: '신규', linked_item_id: null,
          created_at: Date.now(), updated_at: Date.now(),
        });
        added++;
      }
    } catch (e) {
      errors.push({ source: src.key, label: src.label || src.key, message: String(e.message || e) });
    }
    if (i < sources.length - 1) await sleep(Number(src.delay_ms) || DEFAULT_DELAY_MS);
  }

  const run = { at: Date.now(), trigger, sources: sources.map(s => s.key), seen, added, errors, logs };
  db.reg_collect_runs.push(run);
  if (db.reg_collect_runs.length > MAX_RUNS_KEPT) db.reg_collect_runs = db.reg_collect_runs.slice(-MAX_RUNS_KEPT);
  return { run, added };
}

/** 외부 파일(별표 등) 다운로드 — 허용 호스트만. 저장 경로는 호출자가 넘긴다. */
async function downloadToFile(url, destDir, { timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const u = new URL(url);
  if (!ALLOWED_FILE_HOSTS.has(u.host)) throw new Error('허용되지 않은 호스트: ' + u.host);
  const r = await httpGet(url, { timeoutMs });
  if (r.status !== 200) throw new Error('HTTP ' + r.status);
  let name = '';
  const cd = String(r.headers['content-disposition'] || '');
  const m1 = cd.match(/filename\*=UTF-8''([^;]+)/i); const m2 = cd.match(/filename="?([^";]+)"?/i);
  if (m1) { try { name = decodeURIComponent(m1[1]); } catch (_) { name = m1[1]; } }
  else if (m2) name = m2[1];
  if (!name) name = path.basename(u.pathname) || 'download.bin';
  name = name.replace(/[\\/]/g, '_');
  let ext = path.extname(name).toLowerCase();
  if (!ext) {
    const ct = String(r.headers['content-type'] || '');
    ext = ct.includes('pdf') ? '.pdf' : ct.includes('html') ? '.html' : '.bin';
    name += ext;
  }
  fs.mkdirSync(destDir, { recursive: true });
  const stored = `${Date.now()}_${crypto.randomBytes(4).toString('hex')}${ext}`;
  fs.writeFileSync(path.join(destDir, stored), r.body);
  return { stored_name: stored, original_name: name, size: r.body.length, ext, url: `/api/kb/download/${encodeURIComponent(stored)}`, source_url: url };
}

module.exports = { loadSources, describeSources, runCollect, downloadToFile, httpGet, LAW_API_KEY_SET: !!LAW_API_KEY };
