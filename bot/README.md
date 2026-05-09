# 텔레그램 결산조회봇 운영 가이드

## 구조

```
bot/
  app.py          # 봇 메인 (진입점)
  settings.py     # 환경변수 / 경로 설정
  db.py           # SQLite 쿼리 로그
  query_engine.py # DB 조회 로직
  parser.py       # 자연어 파싱
  formatters.py   # 응답 포맷
  .env            # 토큰·허용 ID (git 제외)
  logs/           # 일별 로그 (bot.log, bot_YYYYMMDD.log)
```

---

## 시작 / 중지 / 재시작 (PM2)

프로젝트 루트에 `ecosystem.config.js` 가 있습니다.

```bash
# 처음 등록 및 시작
pm2 start ecosystem.config.js

# 개별 재시작
pm2 restart actuary-bot
pm2 restart actuary-portal

# 전체 중지
pm2 stop all

# 전체 삭제 (등록 해제)
pm2 delete all

# 서버 재부팅 후 자동 시작 등록
pm2 startup
pm2 save
```

---

## 직접 실행 (PM2 없이)

```bash
# Windows
cd "C:\Users\USER\actuary potal\bot"
python app.py

# 백그라운드 실행 (PowerShell)
Start-Process python -ArgumentList "app.py" -WorkingDirectory "." -WindowStyle Hidden
```

---

## 로그 확인

### PM2 로그
```bash
pm2 logs actuary-bot          # 실시간
pm2 logs actuary-bot --lines 200
```

### 일별 로그 파일
```
bot/logs/bot.log              # 오늘 로그 (실시간 기록 중)
bot/logs/bot_20260508.log     # 어제 로그
bot/logs/bot_20260507.log     # 그제 로그
```

```bash
# Windows PowerShell
Get-Content "bot\logs\bot.log" -Tail 50
Get-Content "bot\logs\bot.log" -Wait      # tail -f 효과
```

---

## 헬스체크

포탈에서 **봇 상태 모니터링** 메뉴 → `bot-status.html`

또는 직접 API 호출:
```bash
curl http://localhost:8888/api/bot-heartbeat
# {"last_alive":"2026-05-09T10:00:00Z","status":"running","pid":12345}
```

- `last_alive` 가 1시간 이상 갱신 안 되면 봇이 죽은 것으로 판단
- 포탈 화면에서 빨간 경고 배너 표시

---

## 트러블슈팅

### 봇이 응답하지 않을 때
1. `pm2 status` 로 `actuary-bot` 상태 확인
2. `online` 이면 로그에서 오류 확인: `pm2 logs actuary-bot --lines 100`
3. `stopped` / `errored` 이면 `pm2 restart actuary-bot`
4. 재시작 후에도 계속 죽으면 로그 파일에서 traceback 확인

### `TELEGRAM_BOT_TOKEN` 오류
```
RuntimeError: TELEGRAM_BOT_TOKEN 환경변수가 비어 있습니다.
```
→ `bot/.env` 파일에 토큰이 있는지 확인:
```
TELEGRAM_BOT_TOKEN=<your token here>
```

### DB 없음 오류
```
[WinError 2] 파일을 찾을 수 없습니다: actuarial.db
```
→ `scripts/load_bot_db.py --input <엑셀> --ym <YYYYMM>` 으로 데이터 적재 필요

### 권한 오류 (특정 사용자만 허용)
`bot/.env` 의 `ALLOWED_USER_IDS` 에 텔레그램 user_id 추가:
```
ALLOWED_USER_IDS=123456789,987654321
```
빈 값이면 누구나 조회 가능.

---

## 환경변수 (.env)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `TELEGRAM_BOT_TOKEN` | (필수) | BotFather 에서 발급 |
| `ALLOWED_USER_IDS` | 비어있으면 전체 허용 | 쉼표 구분 |
| `DB_PATH` | `server/data/actuarial.db` | SQLite DB 경로 |
| `LOG_DIR` | `bot/logs` | 일별 로그 디렉토리 |
| `HEARTBEAT_PATH` | `server/data/bot-heartbeat.json` | 헬스체크 파일 경로 |
| `PORTAL_URL` | `http://127.0.0.1:8888` | 포탈 서버 URL |
