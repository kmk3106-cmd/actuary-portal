#!/usr/bin/env node
// 포탈 일일 자체점검 — 샌드박스 서버를 띄우고 모든 메뉴를 팀장·직원 두 역할로 열어 보고, 버튼을 눌러 보고,
// 모달 폼에 가상의 글을 넣어 저장까지 해 본다. 오류(JS 예외 · console.error · 4xx/5xx · 로그인 튕김 ·
// 실패 토스트 · 가로 스크롤 · 'undefined'/'NaN' 노출)를 모아 JSON + Markdown 으로 남긴다. (docs/QA_DAILY_CHECK.md)
//
//   node scripts/qa/qa_smoke.js --out tmp/qa_out [--port 8930] [--seed <db.json>] [--pages a.html,b.html]
//                               [--roles team_leader,employee] [--no-forms] [--max-clicks 40] [--keep-db]
//   종료코드: 0 = 결함 없음, 1 = 결함 있음, 2 = 실행 자체 실패
'use strict';
// Playwright 는 기본으로 Chromium 의 loopback 프록시 우회를 끄는데(<-loopback>), 그러면 127.0.0.1 샌드박스 요청까지
// 프록시로 가서 405 가 난다. 프록시는 외부 CDN 에만 쓰고 샌드박스는 직접 붙도록 그 동작을 끈다 (launch 전에 설정해야 한다)
process.env.PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK = '1';
const { spawn } = require('child_process');
const http = require('http'); const path = require('path'); const fs = require('fs');

const ROOT = path.resolve(__dirname, '..', '..');
const DEFAULTS = { port: 8930, out: path.join(ROOT, 'tmp', 'qa_out'), roles: 'team_leader,employee', maxClicks: 40, seed: '', pages: '' };
const PAGE_TIMEOUT = 25000;           // 한 페이지 로드 대기 (ms)
const SETTLE_MS = 400;                // 클릭 후 대기
const WIDTHS = { desktop: { width: 1400, height: 900 }, phone: { width: 390, height: 800 } };
const DANGER_RE = /삭제|로그아웃|초기화|수집 실행|전체 삭제|비우기|발송|보내기|전송|재시작|되돌리기|reset|logout|delete/i;
const SAVE_RE = /저장|등록|추가|확인|적용|제출|완료/;
const CANCEL_RE = /취소|닫기|close/i;
const IGNORE_CONSOLE_RE = /favicon|net::ERR_|fonts\.g|cdn\.|cdnjs|ERR_BLOCKED_BY_CLIENT|Failed to load resource/;   // 외부 CDN 차단은 환경 탓
const IGNORE_REQ_RE = /\/api\/kb\/download\/|\/reg\/collect|\/api\/bot|telegram|\/api\/auth\/logout/;             // 샌드박스에 없는 외부 연동

function parseArgs(argv) {
  const a = { ...DEFAULTS, forms: true, keepDb: false };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === '--no-forms') a.forms = false;
    else if (k === '--keep-db') a.keepDb = true;
    else if (k.startsWith('--')) { a[k.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = argv[++i]; }
  }
  a.port = parseInt(a.port, 10); a.maxClicks = parseInt(a.maxClicks, 10);
  return a;
}

function findPlaywright() {
  for (const p of [path.join(ROOT, 'node_modules', 'playwright-core'), path.join(ROOT, 'tmp', 'node_modules', 'playwright-core'), 'playwright-core']) {
    try { return require(p); } catch {}
  }
  throw new Error('playwright-core 가 없습니다: npm i --prefix tmp playwright-core');
}
function findChromium() {
  if (process.env.QA_CHROME && fs.existsSync(process.env.QA_CHROME)) return process.env.QA_CHROME;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH || '/opt/pw-browsers';
  if (fs.existsSync(base)) {
    for (const d of fs.readdirSync(base).filter(x => x.startsWith('chromium_headless_shell')).sort().reverse()) {
      const p = path.join(base, d, 'chrome-linux', 'headless_shell'); if (fs.existsSync(p)) return p;
    }
    for (const d of fs.readdirSync(base).filter(x => /^chromium-\d+/.test(x)).sort().reverse()) {
      const p = path.join(base, d, 'chrome-linux', 'chrome'); if (fs.existsSync(p)) return p;
    }
    if (fs.existsSync(path.join(base, 'chromium'))) return path.join(base, 'chromium');
  }
  return undefined;   // playwright 기본 탐색
}

// 메뉴 목록은 js/portal.js 의 NAV 가 SSOT — 여기서 읽는다 (규칙 11)
function navPages() {
  const src = fs.readFileSync(path.join(ROOT, 'js', 'portal.js'), 'utf8');
  const navSrc = src.slice(src.indexOf('const NAV = ['), src.indexOf('function buildSidebar'));
  const pages = [];
  for (const m of navSrc.matchAll(/\{\s*href:\s*'([^']+)'[^}]*label:\s*'([^']+)'([^}]*)\}/g)) {
    pages.push({ href: m[1], label: m[2], leaderOnly: /requiresLeader:\s*true/.test(m[3]), leaderOrChief: /leaderOrChief:\s*true/.test(m[3]) });
  }
  return pages;
}

const sessionFor = (role) => JSON.stringify({
  team_leader: { session_token: 'qa' + '0'.repeat(48), user_id: 'u_teamleader1', username: 'teamleader1', role: 'team_leader', full_name: '김팀장', department: '계리결산팀' },
  employee: { session_token: 'qa' + '1'.repeat(48), user_id: 'u_qa_emp', username: 'qa_emp', role: 'employee', full_name: 'QA직원', department: '계리결산팀' },
  section_chief: { session_token: 'qa' + '2'.repeat(48), user_id: 'u_sectionchief1', username: 'sectionchief1', role: 'section_chief', full_name: '이실장', department: '계리결산실' },
}[role] && { ...{ team_leader: { session_token: 'qa' + '0'.repeat(48), user_id: 'u_teamleader1', username: 'teamleader1', role: 'team_leader', full_name: '김팀장', department: '계리결산팀' }, employee: { session_token: 'qa' + '1'.repeat(48), user_id: 'u_qa_emp', username: 'qa_emp', role: 'employee', full_name: 'QA직원', department: '계리결산팀' }, section_chief: { session_token: 'qa' + '2'.repeat(48), user_id: 'u_sectionchief1', username: 'sectionchief1', role: 'section_chief', full_name: '이실장', department: '계리결산실' } }[role], expires_at: Date.now() + 6 * 3600 * 1000 });

function req(base, method, urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null;
    const r = http.request(base + urlPath, { method, headers: data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {} },
      res => { const ch = []; res.on('data', c => ch.push(c)); res.on('end', () => { let j = null; try { j = JSON.parse(Buffer.concat(ch).toString()); } catch {} resolve({ status: res.statusCode, body: j }); }); });
    r.on('error', reject); if (data) r.write(data); r.end();
  });
}
function waitServer(base, t = 30000) { const t0 = Date.now(); return new Promise((res, rej) => { (function p() { http.get(base + '/login.html', r => { r.destroy(); res(); }).on('error', () => (Date.now() - t0 > t) ? rej(new Error('서버 시작 시간 초과')) : setTimeout(p, 250)); })(); }); }

async function main() {
  const a = parseArgs(process.argv.slice(2));
  fs.mkdirSync(a.out, { recursive: true });
  const shots = path.join(a.out, 'shots'); fs.mkdirSync(shots, { recursive: true });
  const { chromium } = findPlaywright();
  const BASE = `http://127.0.0.1:${a.port}`;
  const dbPath = path.join(a.out, 'qa_db.json'); try { fs.unlinkSync(dbPath); } catch {}
  if (a.seed) fs.copyFileSync(a.seed, dbPath);
  const today = new Date(); const ymd = today.toISOString().slice(0, 10); const stamp = `QA 자동점검 ${ymd}`;
  const findings = [];   // { page, role, width, kind, detail, shot }
  const visited = [];
  const envNotes = [];   // 환경 탓(파이썬 모듈·CDN) — 결함으로 세지 않고 보고서에만 적는다
  const add = (f) => { findings.push(f); console.log(`  ❌ [${f.kind}] ${f.page} (${f.role}${f.width ? ',' + f.width : ''}) ${String(f.detail).slice(0, 160)}`); };

  const srv = spawn('node', ['server/server.js'], { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, PORT: String(a.port), DATA_PATH: dbPath, REG_COLLECT_ENABLED: '0', REG_SYNC_ENABLED: '0', TELEGRAM_BOT_TOKEN: '', BOT_ENABLED: '0' } });
  let srvLog = ''; srv.stdout.on('data', d => { srvLog += d; }); srv.stderr.on('data', d => { srvLog += d; });
  // 클라우드 샌드박스는 외부 CDN(ApexCharts·XLSX·marked)을 프록시로만 받을 수 있다 → 브라우저에 프록시를 넘긴다
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy || '';
  const browser = await chromium.launch({ executablePath: findChromium(), args: ['--no-sandbox'], ...(proxy ? { proxy: { server: proxy, bypass: '127.0.0.1,localhost' } } : {}) });
  let exitCode = 0;
  try {
    await waitServer(BASE);
    // 샌드박스 사용자: 직원 계정이 없으면 만든다 (팀장·실장은 초기 DB 에 있다)
    const users = await req(BASE, 'GET', '/tables/users?limit=200');
    if (!(users.body && (users.body.rows || users.body.data || []).some(u => u.username === 'qa_emp'))) {
      await req(BASE, 'POST', '/tables/users', { id: 'u_qa_emp', username: 'qa_emp', full_name: 'QA직원', role: 'employee', department: '계리결산팀', is_active: true, password_hash: 'x' });
    }
    const pagesAll = navPages();
    const want = a.pages ? a.pages.split(',').map(s => s.trim()) : null;
    const roles = a.roles.split(',').map(s => s.trim()).filter(Boolean);

    for (const role of roles) {
      const ctx = await browser.newContext({ viewport: WIDTHS.desktop, ignoreHTTPSErrors: !!proxy });
      await ctx.addInitScript(v => { try { sessionStorage.setItem('rbac_session', v); } catch (e) {} }, sessionFor(role));
      await ctx.route('**/*', r => /fonts\.googleapis|fonts\.gstatic/.test(r.request().url()) ? r.abort() : r.continue());   // 웹폰트만 생략 (속도)
      for (const pg of pagesAll) {
        if (want && !want.includes(pg.href)) continue;
        if (role === 'employee' && (pg.leaderOnly || pg.leaderOrChief)) continue;   // 직원은 메뉴 자체가 없다
        const page = await ctx.newPage();
        const errs = [], cons = [], bad = [];
        page.on('pageerror', e => errs.push(String(e.message || e)));
        page.on('console', m => { if (m.type() === 'error' && !IGNORE_CONSOLE_RE.test(m.text())) cons.push(m.text()); });
        page.on('response', async r => {
          const u = r.url();
          if (!u.startsWith(BASE) || r.status() < 400 || IGNORE_REQ_RE.test(u)) return;
          let note = '';
          try { const t = await r.text(); if (/ModuleNotFoundError|No module named/.test(t)) { envNotes.push(`${u.slice(BASE.length)} → 파이썬 모듈 없음 (${(t.match(/No module named '([^']+)'/) || [])[1] || '?'}) — 점검 환경에 pip install 필요, 코드 결함 아님`); return; } note = ' ' + t.slice(0, 120).replace(/\s+/g, ' '); } catch {}
          bad.push(`${r.status()} ${r.request().method()} ${u.slice(BASE.length)}${note}`);
        });
        const cdnFailed = [];
        page.on('requestfailed', r => { const u = r.url(); if (/cdn\.|cdnjs|unpkg/.test(u)) { cdnFailed.push(u); envNotes.push(`CDN 로드 실패 ${u.slice(0, 80)} (${r.failure() && r.failure().errorText}) — 네트워크 환경, 코드 결함 아님`); } });
        // CDN 스크립트(ApexCharts·XLSX·marked 등)를 못 받아서 난 'X is not defined' 는 코드 결함이 아니라 환경 문제다
        const isCdnMiss = msg => cdnFailed.length > 0 && /^(?:\w+ )?(\w+) is not defined/.test(String(msg).replace(/^.*?ReferenceError:\s*/, ''));
        page.on('dialog', d => d.accept());
        const tag = `${pg.href.replace('.html', '')}_${role}`;
        let loaded = false;
        try {   // 한 화면의 예외가 전체 점검을 멈추지 않게 (클릭 중 페이지 이동 등)
        try {
          await page.goto(`${BASE}/${pg.href}`, { waitUntil: 'domcontentloaded', timeout: PAGE_TIMEOUT });
          await page.waitForTimeout(1200);
          await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
          loaded = true;
        } catch (e) { add({ page: pg.href, role, kind: '로드 실패', detail: e.message }); }
        if (loaded) {
          if (/login\.html/.test(page.url())) add({ page: pg.href, role, kind: '로그인 튕김', detail: `세션이 있는데 ${page.url().slice(BASE.length)} 로 이동` });
          const body = await page.evaluate(() => ({ text: document.body.innerText || '', title: document.title, h: document.documentElement.scrollWidth, w: window.innerWidth, sidebar: !!document.querySelector('#sidebar .nav-item, #sidebar a, .sidebar a') }));
          const leak = body.text.match(/\b(undefined|NaN|\[object Object\])\b/g);
          if (leak) add({ page: pg.href, role, kind: '값 노출', detail: `본문에 ${[...new Set(leak)].join(', ')} 표시 (${leak.length}곳)` });
          if (!body.sidebar && !/login/.test(page.url())) add({ page: pg.href, role, kind: '사이드바 없음', detail: '메뉴가 그려지지 않음' });
          if (body.h > body.w + 1) add({ page: pg.href, role, width: 'desktop', kind: '가로 스크롤', detail: `scrollWidth ${body.h} > ${body.w}` });
          await page.screenshot({ path: path.join(shots, `${tag}.png`) }).catch(() => {});

          // 폰 폭
          await page.setViewportSize(WIDTHS.phone); await page.waitForTimeout(300);
          const ph = await page.evaluate(() => ({ h: document.documentElement.scrollWidth, w: window.innerWidth }));
          if (ph.h > ph.w + 1) { add({ page: pg.href, role, width: 'phone', kind: '가로 스크롤', detail: `scrollWidth ${ph.h} > ${ph.w}` }); await page.screenshot({ path: path.join(shots, `${tag}_phone.png`) }).catch(() => {}); }
          await page.setViewportSize(WIDTHS.desktop); await page.waitForTimeout(200);

          // 버튼·탭 클릭 + 모달 폼 입력 (팀장만 — 직원 권한 화면은 열람 위주)
          let clicks = 0, forms = 0;
          if (role === 'team_leader') {
            const seen = new Set();
            for (let round = 0; round < a.maxClicks; round++) {
              const target = await page.evaluate(({ seen, DANGER }) => {
                const danger = new RegExp(DANGER, 'i');
                const inModal = el => !!el.closest('.modal-overlay, .modal, [role=dialog]');
                const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
                const els = Array.from(document.querySelectorAll('button, .rh-tab, .tab, .tab-btn, [role=tab], a.btn, [onclick]'))
                  .filter(el => vis(el) && !inModal(el) && !el.disabled && !el.closest('#sidebar, .sidebar, .toast-container'));
                for (const el of els) {
                  const txt = (el.innerText || el.getAttribute('title') || el.getAttribute('aria-label') || '').trim().slice(0, 40);
                  const key = el.tagName + '|' + txt + '|' + (el.className || '') + '|' + (el.id || '');
                  if (seen.includes(key)) continue;
                  if (danger.test(txt) || danger.test(el.id || '') || danger.test(el.getAttribute('onclick') || '')) continue;
                  if (el.tagName === 'A' && el.getAttribute('href') && !/^#|^javascript/.test(el.getAttribute('href'))) continue;   // 페이지 이동 링크는 메뉴 순회로 대신
                  el.setAttribute('data-qa-target', '1');
                  return { key, txt };
                }
                return null;
              }, { seen: [...seen], DANGER: DANGER_RE.source });
              if (!target) break;
              seen.add(target.key); clicks++;
              const errBefore = errs.length + cons.length + bad.length;
              try {
                await page.click('[data-qa-target="1"]', { timeout: 3000, noWaitAfter: true });
              } catch (e) { /* 가려진 요소 등 — 결함 아님 */ }
              await page.evaluate(() => document.querySelectorAll('[data-qa-target]').forEach(el => el.removeAttribute('data-qa-target')));
              await page.waitForTimeout(SETTLE_MS);
              if (/login\.html/.test(page.url())) { add({ page: pg.href, role, kind: '로그인 튕김', detail: `"${target.txt}" 클릭 후 로그인 화면으로` }); break; }
              if (!page.url().startsWith(`${BASE}/${pg.href}`)) { await page.goBack({ waitUntil: 'domcontentloaded' }).catch(() => {}); await page.waitForTimeout(500); continue; }
              const newErrs = [...errs, ...cons, ...bad].slice(errBefore).filter(e => !isCdnMiss(e));
              if (newErrs.length) add({ page: pg.href, role, kind: '클릭 오류', detail: `"${target.txt}" 클릭 → ` + newErrs.join(' | ') , shot: `${tag}_click${clicks}.png` }) && await page.screenshot({ path: path.join(shots, `${tag}_click${clicks}.png`) }).catch(() => {});
              // 모달이 열렸으면 폼 입력 → 저장 → 오류 토스트 확인 → 닫기
              const modalOpen = await page.evaluate(() => { const m = Array.from(document.querySelectorAll('.modal-overlay')).find(x => getComputedStyle(x).opacity === '1' && getComputedStyle(x).visibility !== 'hidden'); return m ? (m.id || m.className) : null; });
              if (modalOpen) {
                if (a.forms) {
                  forms++;
                  const filled = await page.evaluate(({ stamp, ymd }) => {
                    const m = Array.from(document.querySelectorAll('.modal-overlay')).find(x => getComputedStyle(x).opacity === '1');
                    let n = 0;
                    const fire = el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); };
                    m.querySelectorAll('input, textarea, select').forEach(el => {
                      if (el.type === 'hidden' || el.type === 'file' || el.disabled || el.readOnly) return;
                      const r = el.getBoundingClientRect(); if (!r.width) return;
                      if (el.tagName === 'SELECT') { const o = Array.from(el.options).find(x => x.value); if (o && !el.value) { el.value = o.value; fire(el); n++; } return; }
                      if (el.type === 'checkbox' || el.type === 'radio') return;
                      if (el.value) return;
                      if (el.type === 'date') el.value = ymd; else if (el.type === 'month') el.value = ymd.slice(0, 7); else if (el.type === 'time') el.value = '09:00';
                      else if (el.type === 'number') el.value = el.min || '1'; else if (el.type === 'url') el.value = 'https://example.com/qa'; else if (el.type === 'email') el.value = 'qa@example.com';
                      else el.value = stamp + (el.placeholder ? ' · ' + el.placeholder.slice(0, 20) : '');
                      fire(el); n++;
                    });
                    return n;
                  }, { stamp, ymd });
                  const toastBefore = await page.evaluate(() => document.querySelectorAll('.toast.error').length);
                  const errBefore2 = errs.length + cons.length + bad.length;
                  const saved = await page.evaluate((SAVE) => {
                    const re = new RegExp(SAVE); const m = Array.from(document.querySelectorAll('.modal-overlay')).find(x => getComputedStyle(x).opacity === '1');
                    const btn = Array.from(m.querySelectorAll('button, a.btn')).filter(b => b.getBoundingClientRect().width > 0).find(b => re.test((b.innerText || '').trim()) && !/삭제|취소|닫기/.test(b.innerText));
                    if (btn) { btn.click(); return (btn.innerText || '').trim(); } return null;
                  }, SAVE_RE.source);
                  await page.waitForTimeout(900);
                  const toastErr = await page.evaluate(() => Array.from(document.querySelectorAll('.toast.error')).map(t => t.innerText.trim()));
                  if (saved && filled && toastErr.length > toastBefore) add({ page: pg.href, role, kind: '저장 실패 토스트', detail: `모달(${modalOpen}) "${saved}" → ${toastErr.join(' / ')}`, shot: `${tag}_form${forms}.png` }) && await page.screenshot({ path: path.join(shots, `${tag}_form${forms}.png`) }).catch(() => {});
                  if (errs.length + cons.length + bad.length > errBefore2) add({ page: pg.href, role, kind: '저장 중 오류', detail: `모달(${modalOpen}) "${saved}" → ` + [...errs, ...cons, ...bad].slice(errBefore2).join(' | ') });
                }
                // 닫기
                await page.evaluate((CANCEL) => {
                  const re = new RegExp(CANCEL, 'i');
                  for (const m of Array.from(document.querySelectorAll('.modal-overlay')).filter(x => getComputedStyle(x).opacity === '1')) {
                    const c = m.querySelector('.modal-close, .mc, [data-close], .close') || Array.from(m.querySelectorAll('button')).find(b => re.test(b.innerText));
                    if (c) c.click(); else m.classList.remove('show', 'open');
                  }
                }, CANCEL_RE.source);
                await page.waitForTimeout(300);
                await page.evaluate(() => document.querySelectorAll('.modal-overlay.show, .modal-overlay.open').forEach(m => m.classList.remove('show', 'open')));
              }
            }
          }
          const errsReal = errs.filter(e => !isCdnMiss(e)), consReal = cons.filter(e => !isCdnMiss(e));
          if (errs.length !== errsReal.length || cons.length !== consReal.length) envNotes.push(`${pg.href} (${role}): CDN 스크립트 미수신으로 인한 'X is not defined' ${errs.length - errsReal.length + cons.length - consReal.length}건 — 환경`);
          if (errsReal.length) add({ page: pg.href, role, kind: 'JS 예외', detail: [...new Set(errsReal)].join(' | ') });
          if (consReal.length) add({ page: pg.href, role, kind: 'console.error', detail: [...new Set(consReal)].slice(0, 5).join(' | ') });
          if (bad.length) add({ page: pg.href, role, kind: 'HTTP 오류 응답', detail: [...new Set(bad)].slice(0, 8).join(' | ') });
          visited.push({ page: pg.href, label: pg.label, role, clicks, forms, errs: errs.length, cons: cons.length, bad: bad.length });
          console.log(`  ✓ ${pg.href} (${role}) 클릭 ${clicks} · 폼 ${forms}`);
        }
        } catch (e) {
          if (/Execution context was destroyed|Target closed|navigation/i.test(String(e.message))) envNotes.push(`${pg.href} (${role}): 버튼 클릭이 페이지를 다시 불러옴(새로고침·이동) → 그 화면의 나머지 버튼은 건너뜀 (${page.url().slice(BASE.length)})`);
          else add({ page: pg.href, role, kind: '점검 스크립트 예외', detail: e.message.split('\n')[0] });
          visited.push({ page: pg.href, label: pg.label, role, clicks: -1, forms: -1, errs: errs.length, cons: cons.length, bad: bad.length });
        }
        await page.close().catch(() => {});
      }
      await ctx.close();
    }
    // 서버 로그의 스택 트레이스
    const stack = srvLog.split('\n').filter(l => /Error|TypeError|ReferenceError|at .*server\.js/.test(l)).slice(0, 10);
    if (stack.length) add({ page: 'server', role: '-', kind: '서버 로그 오류', detail: stack.join(' | ') });
  } catch (e) {
    exitCode = 2; add({ page: '-', role: '-', kind: '실행 실패', detail: e.stack || String(e) });
  } finally {
    await browser.close(); srv.kill('SIGTERM');
    if (!a.keepDb) { try { fs.unlinkSync(dbPath); } catch {} }
  }
  if (exitCode === 0 && findings.length) exitCode = 1;
  const env = [...new Set(envNotes)];
  const report = { date: ymd, ran_at: new Date().toISOString(), visited, findings, env_notes: env, summary: { pages: visited.length, findings: findings.length, kinds: findings.reduce((m, f) => (m[f.kind] = (m[f.kind] || 0) + 1, m), {}) } };
  fs.writeFileSync(path.join(a.out, 'report.json'), JSON.stringify(report, null, 2));
  const md = [`# 포탈 자체점검 ${ymd}`, '', `- 점검 화면: ${visited.length} (역할 ${a.roles})`, `- 결함: ${findings.length}` + (findings.length ? ' — ' + Object.entries(report.summary.kinds).map(([k, v]) => `${k} ${v}`).join(' · ') : ''),
    ...(env.length ? ['', '환경 메모 (결함 아님):', ...env.map(e => `- ${e}`)] : []), '',
    '| 화면 | 역할 | 종류 | 내용 |', '|---|---|---|---|', ...findings.map(f => `| ${f.page} | ${f.role}${f.width ? '/' + f.width : ''} | ${f.kind} | ${String(f.detail).replace(/\|/g, '／').slice(0, 300)} |`), '',
    '| 화면 | 역할 | 클릭 | 폼 |', '|---|---|---|---|', ...visited.map(v => `| ${v.page} ${v.label} | ${v.role} | ${v.clicks} | ${v.forms} |`)].join('\n');
  fs.writeFileSync(path.join(a.out, 'report.md'), md);
  console.log(`\n===== 자체점검: 화면 ${visited.length} · 결함 ${findings.length} → ${path.join(a.out, 'report.md')} =====`);
  process.exit(exitCode);
}
main().catch(e => { console.error(e); process.exit(2); });
