#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# 계리결산팀 포탈 - VPS 배포/업데이트 스크립트
# ═══════════════════════════════════════════════════════════════════
# git pull → 이미지 재빌드 → 무중단 재시작
# 사용: bash scripts/vps-deploy.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

cd "$(dirname "$0")/.."
BRANCH="${BRANCH:-master}"

echo "[1/4] git pull ..."
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "[2/4] Docker 이미지 재빌드 ..."
docker compose build --pull

echo "[3/4] 컨테이너 재시작 (recreate) ..."
docker compose up -d --remove-orphans

echo "[4/4] 헬스체크 대기 ..."
for i in {1..30}; do
    if curl -fsS http://127.0.0.1:8888/ -o /dev/null 2>&1; then
        echo "  ✅ 서버 정상 응답 (${i}s)"
        break
    fi
    sleep 1
done

echo
echo "=== 상태 ==="
docker compose ps
echo
echo "=== 최근 로그 (server) ==="
docker compose logs --tail 20 server
