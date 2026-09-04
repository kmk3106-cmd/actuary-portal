#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# 계리결산팀 포탈 - 헬스체크 + 자동복구 (cron 5분 주기 권장)
# ═══════════════════════════════════════════════════════════════════
# Docker container 가 죽거나 응답 없을 때 자동으로 재시작 시도
# ═══════════════════════════════════════════════════════════════════
set -uo pipefail

cd "$(dirname "$0")/.."

LOG_FILE="logs/healthcheck.log"
mkdir -p logs

log() { echo "[$(date -Is)] $*" | tee -a "$LOG_FILE"; }

restart_needed=false

# 1) 서버 응답 체크
if ! curl -fsS -m 5 http://127.0.0.1:8888/ -o /dev/null 2>&1; then
    log "❌ server 응답 없음"
    restart_needed=true
fi

# 2) 컨테이너 살아있는지
for svc in server bot cloudflared; do
    state=$(docker compose ps -q "$svc" 2>/dev/null | xargs -r docker inspect -f '{{.State.Status}}' 2>/dev/null || echo "missing")
    if [[ "$state" != "running" ]]; then
        log "❌ $svc 상태: $state"
        restart_needed=true
    fi
done

# 3) 봇 heartbeat 신선도 (10분 이상이면 이상)
if [[ -f server/data/bot-heartbeat.json ]]; then
    age=$(( $(date +%s) - $(stat -c %Y server/data/bot-heartbeat.json 2>/dev/null || echo 0) ))
    if (( age > 600 )); then
        log "⚠️  bot heartbeat 오래됨: ${age}s"
        # 봇만 재시작
        docker compose restart bot >>"$LOG_FILE" 2>&1
    fi
fi

if $restart_needed; then
    log "▶ docker compose up -d --remove-orphans 실행"
    docker compose up -d --remove-orphans >>"$LOG_FILE" 2>&1
    sleep 10
    if curl -fsS -m 5 http://127.0.0.1:8888/ -o /dev/null; then
        log "✅ 복구 성공"
    else
        log "🚨 복구 실패 - 수동 확인 필요"
        exit 1
    fi
fi
