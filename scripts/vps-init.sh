#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# 계리결산팀 포탈 - Oracle Cloud VPS 초기 세팅 스크립트
# ═══════════════════════════════════════════════════════════════════
# Ubuntu 22.04 (ARM64 또는 x86_64) 신규 인스턴스에서 최초 1회 실행
# 사용: bash scripts/vps-init.sh [저장소_URL]
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

REPO_URL="${1:-https://github.com/kmk3106-cmd/actuary-portal.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/actuary-portal}"
BRANCH="${BRANCH:-master}"

log()  { printf "\033[1;34m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
warn() { printf "\033[1;33m[%s WARN]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
die()  { printf "\033[1;31m[%s FAIL]\033[0m %s\n" "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

# ─── 0. 사전 확인 ─────────────────────────────────
[[ $EUID -eq 0 ]] && die "root 로 실행 금지. ubuntu 유저로 실행하세요 (sudo 는 스크립트가 알아서 사용)."
command -v apt-get >/dev/null || die "Debian/Ubuntu 계열 아님."

log "== 계리결산팀 포탈 VPS 초기 세팅 시작 =="
log "저장소: $REPO_URL"
log "설치 위치: $INSTALL_DIR"
log "브랜치: $BRANCH"

# ─── 1. 시스템 업데이트 & 기본 패키지 ────────────
log "[1/7] 시스템 업데이트 + 기본 패키지 설치 ..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
sudo apt-get install -y -qq \
    git curl ca-certificates gnupg lsb-release \
    ufw fail2ban tzdata unzip jq

# ─── 2. 타임존 ──────────────────────────────────
log "[2/7] 타임존 Asia/Seoul 설정 ..."
sudo timedatectl set-timezone Asia/Seoul

# ─── 3. Docker + Compose 플러그인 설치 ────────────
if ! command -v docker >/dev/null; then
    log "[3/7] Docker 설치 ..."
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
          https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER"
    log "Docker 설치 완료. 그룹 반영 위해 재로그인 필요."
else
    log "[3/7] Docker 이미 설치됨 - 건너뜀."
fi

# ─── 4. 방화벽 (Oracle Cloud 는 별도 Ingress 도 필요) ─
log "[4/7] UFW 방화벽 설정 ..."
sudo ufw --force reset >/dev/null
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
# cloudflared 는 outbound 만 쓰므로 8888 외부 오픈 불필요.
# (내부 debug 필요 시 sudo ufw allow from <내 IP> to any port 8888 로 임시 개방)
sudo ufw --force enable
log "UFW: SSH 만 허용. 포탈은 cloudflared 를 통해서만 접근."

# ─── 5. 저장소 clone (혹은 pull) ────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "[5/7] 저장소 이미 존재 - git pull 실행 ..."
    git -C "$INSTALL_DIR" fetch origin
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
else
    log "[5/7] 저장소 clone 중 ..."
    git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

# ─── 6. .env 초기 파일 ────────────────────────────
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    log "[6/7] .env 파일 생성 (템플릿에서 복사) ..."
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    warn "  → nano $INSTALL_DIR/.env 로 TELEGRAM_BOT_TOKEN, CLOUDFLARE_TUNNEL_TOKEN 등 채우기 필수!"
else
    log "[6/7] .env 이미 존재 - 건너뜀."
fi

# ─── 7. systemd 서비스 등록 (부팅 자동시작) ──────
log "[7/7] systemd 서비스 등록 ..."
sudo tee /etc/systemd/system/actuary-portal.service >/dev/null <<EOF
[Unit]
Description=계리결산팀 포탈 (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
User=$USER
Group=$USER
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable actuary-portal.service
log "  systemctl 등록 완료. 부팅 시 자동 시작."

# ─── 백업 크론 ────────────────────────────────────
log "일일 DB 백업 cron 등록 (매일 03:00) ..."
CRON_LINE="0 3 * * * cd $INSTALL_DIR && bash scripts/vps-backup.sh >> logs/backup.log 2>&1"
( crontab -l 2>/dev/null | grep -Fv "vps-backup.sh" ; echo "$CRON_LINE" ) | crontab -

# ─── 완료 안내 ────────────────────────────────────
cat <<EOF

═══════════════════════════════════════════════════════════════════
  ✅ VPS 초기 세팅 완료!
═══════════════════════════════════════════════════════════════════

⚠️  Docker 그룹 반영을 위해 반드시 재로그인 필요:
    exit
    ssh ubuntu@<이 서버 IP> 로 다시 접속

🎯 다음 단계:
  1) .env 값 채우기:
       nano $INSTALL_DIR/.env
       → TELEGRAM_BOT_TOKEN
       → CLOUDFLARE_TUNNEL_TOKEN  (Zero Trust 대시보드에서 발급)
       → ALLOWED_USER_IDS

  2) 기존 PC 에서 DB 파일 이관:
       scp -r ./server/data/actuarial.db ubuntu@<서버 IP>:$INSTALL_DIR/server/data/
       scp    ./server/data/portal-db.json ubuntu@<서버 IP>:$INSTALL_DIR/server/data/

  3) 서비스 시작:
       cd $INSTALL_DIR
       sudo systemctl start actuary-portal
       docker compose logs -f

  4) 상태 확인:
       docker compose ps
       curl http://127.0.0.1:8888/

  5) Cloudflare DNS 는 이미 portal.kkuks.com 사용 중이면
     Zero Trust 대시보드에서 새 터널로 Route 만 옮기면 즉시 반영.

═══════════════════════════════════════════════════════════════════
EOF
