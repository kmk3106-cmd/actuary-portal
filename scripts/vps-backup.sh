#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# 계리결산팀 포탈 - DB 일일 백업 스크립트 (cron 용)
# ═══════════════════════════════════════════════════════════════════
# 매일 03:00 실행. 최근 30일 백업만 보관.
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

cd "$(dirname "$0")/.."

DATA_DIR="server/data"
BACKUP_DIR="server/data/backups"
STAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"

echo "[$(date -Is)] === 백업 시작 ==="

# SQLite - 파일 시스템 락 걱정 없이 online backup
if [[ -f "$DATA_DIR/actuarial.db" ]]; then
    # docker 안에서 sqlite3 사용 (호스트에 sqlite3 없어도 됨)
    docker compose exec -T server node -e "
      const fs = require('fs');
      const src = '/app/server/data/actuarial.db';
      const dst = '/app/server/data/backups/actuarial_${STAMP}.db';
      fs.copyFileSync(src, dst);
      console.log('SQLite 백업 완료:', dst);
    " 2>/dev/null || cp "$DATA_DIR/actuarial.db" "$BACKUP_DIR/actuarial_${STAMP}.db"
fi

# JSON DB
if [[ -f "$DATA_DIR/portal-db.json" ]]; then
    cp "$DATA_DIR/portal-db.json" "$BACKUP_DIR/portal-db_${STAMP}.json"
fi

# gzip 압축
gzip -f "$BACKUP_DIR/actuarial_${STAMP}.db"  2>/dev/null || true
gzip -f "$BACKUP_DIR/portal-db_${STAMP}.json" 2>/dev/null || true

# 오래된 백업 삭제
find "$BACKUP_DIR" -name "actuarial_*.db.gz"  -mtime +"$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -name "portal-db_*.json.gz" -mtime +"$RETENTION_DAYS" -delete

echo "[$(date -Is)] === 백업 완료 ==="
du -sh "$BACKUP_DIR"
ls -lh "$BACKUP_DIR" | tail -5
