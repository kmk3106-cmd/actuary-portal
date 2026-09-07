# Oracle Cloud VPS 배포 가이드 — 계리결산팀 포탈 24/7 운영

> **목표**: 개인 PC를 끄더라도 `https://portal.kkuks.com` 이 항상 살아있도록 Oracle Cloud Free Tier VM에 이관.

**총 소요시간**: 1~2시간 (VM 생성 대기 포함)
**비용**: **평생 무료** (Oracle Cloud Free Tier ARM Ampere 사양 이내)

---

## 1. Oracle Cloud 계정 생성 & VM 인스턴스 만들기

### 1-1. 가입
1. https://www.oracle.com/cloud/free/ 접속 → "Start for free"
2. 이메일 인증 후 회원가입
3. **결제 카드 등록** (인증용, 자동과금 절대 안 됨 — Free Tier 유지 시)
4. 홈 리전(Home Region) 선택: **Seoul 또는 Chuncheon** (가까울수록 빠름)

### 1-2. Compute Instance 생성
1. 좌측 햄버거 메뉴 → **Compute → Instances → Create Instance**
2. 설정:
   - **Name**: `actuary-portal-vm`
   - **Image**: `Canonical Ubuntu 22.04`
   - **Shape**: **"Change shape" 클릭**
     - Shape series: **Ampere** ← 반드시 이것
     - Shape name: **VM.Standard.A1.Flex**
     - **OCPU 4 / Memory 24GB** ← Free Tier 최대치, 무료
   - **Networking**: 기본값 유지 (public IPv4 자동 할당)
   - **SSH keys**:
     - **"Generate a key pair for me"** 선택 → **Private key 다운로드 필수** (분실 시 접속 불가!)
     - 다운받은 `ssh-key-YYYY-MM-DD.key` 파일을 안전한 곳에 보관 (예: `C:\Users\USER\.ssh\oracle_key.pem`)
3. **Create** 클릭. 1~3분 후 STATUS=RUNNING.

### 1-3. Ingress Rules (방화벽) 확인
Oracle Cloud는 VM 방화벽과는 별도로 **Virtual Cloud Network (VCN) 방화벽**이 있음. 하지만 이번 구성에서는 cloudflared가 outbound만 쓰므로 **기본 상태 그대로 두면 됨** (SSH 22번만 열려 있으면 충분).

---

## 2. SSH 접속

### Windows PowerShell
```powershell
# 키 파일 권한 설정 (반드시 한 번)
icacls "C:\Users\USER\.ssh\oracle_key.pem" /inheritance:r
icacls "C:\Users\USER\.ssh\oracle_key.pem" /grant:r "$($env:USERNAME):(R)"

# 접속
ssh -i "C:\Users\USER\.ssh\oracle_key.pem" ubuntu@<VM Public IP>
```

VM Public IP는 Oracle Cloud Instance 상세 페이지 상단에 표시됨.

접속 성공 시 프롬프트: `ubuntu@actuary-portal-vm:~$`

---

## 3. 자동 세팅 스크립트 실행 (한 줄)

VM에 접속한 상태에서:

```bash
curl -fsSL https://raw.githubusercontent.com/kmk3106-cmd/actuary-portal/claude/great-shaw-4acfad-31ua6t/scripts/vps-init.sh \
  | bash -s -- https://github.com/kmk3106-cmd/actuary-portal.git
```

또는 clone 먼저:

```bash
git clone -b claude/great-shaw-4acfad-31ua6t https://github.com/kmk3106-cmd/actuary-portal.git
cd actuary-portal
bash scripts/vps-init.sh
```

**스크립트가 자동으로 수행**:
- ✅ 시스템 업데이트 + 필수 패키지 (git, curl, ufw, fail2ban 등)
- ✅ 타임존 Asia/Seoul
- ✅ Docker Engine + Compose 플러그인 설치
- ✅ UFW 방화벽 (SSH만 허용)
- ✅ 저장소 clone
- ✅ `.env` 템플릿 복사
- ✅ systemd 서비스 등록 (부팅 자동시작)
- ✅ 일일 백업 cron (매일 03:00)

**완료 후 반드시 재로그인**: `exit` → 다시 SSH 접속 (docker 그룹 반영).

---

## 4. Cloudflare Tunnel 토큰 발급

기존 PC의 `cloudflared` 자격증명 파일을 옮기는 대신, **새 토큰을 발급받는 것이 훨씬 간단**합니다.

### 4-1. Zero Trust 대시보드
1. https://one.dash.cloudflare.com/ 접속
2. 좌측 **Networks → Tunnels**
3. 기존 `actuary-portal` 터널이 있으면 **삭제** (또는 그대로 두고 새로 생성)
4. **Create a tunnel** → Cloudflared 선택 → 이름: `actuary-portal-vps`

### 4-2. 토큰 복사
"Install and run a connector" 화면에서 **Docker 탭** 선택:
```
docker run cloudflare/cloudflared:latest tunnel --no-autoupdate run \
  --token eyJhIjoiY.......(긴 문자열)
```
**`--token` 뒤의 긴 문자열만 복사**.

### 4-3. Public Hostname 설정
같은 페이지에서 **Public Hostname** 탭 → **Add a public hostname**:
- Subdomain: `portal`
- Domain: `kkuks.com`
- Service Type: `HTTP`
- URL: `server:8888` ← Docker 서비스 이름

Save 클릭.

---

## 5. `.env` 파일 채우기

VM에서:
```bash
cd ~/actuary-portal
nano .env
```

필수 항목:
```env
TELEGRAM_BOT_TOKEN=<BotFather 토큰>
ALLOWED_USER_IDS=<본인 텔레그램 user ID, 쉼표 구분>
CLOUDFLARE_TUNNEL_TOKEN=<4-2에서 복사한 토큰>
DEFAULT_PERIOD=202609
CURRENT_PERIODS=202609
```

저장: `Ctrl+O` → `Enter` → `Ctrl+X`

---

## 6. 기존 PC의 DB 파일 이관

**⚠️ 이 단계가 데이터 손실 방지의 핵심입니다.**

### Windows PC (PowerShell) 에서 VM으로 SCP:
```powershell
# SQLite DB
scp -i "C:\Users\USER\.ssh\oracle_key.pem" `
    "C:\Users\USER\actuary potal\server\data\actuarial.db" `
    ubuntu@<VM Public IP>:~/actuary-portal/server/data/

# JSON DB (선택 - 있으면)
scp -i "C:\Users\USER\.ssh\oracle_key.pem" `
    "C:\Users\USER\actuary potal\server\data\portal-db.json" `
    ubuntu@<VM Public IP>:~/actuary-portal/server/data/
```

VM에서 확인:
```bash
ls -lh ~/actuary-portal/server/data/
# actuarial.db 가 실제 크기(수MB) 로 있는지 확인
```

---

## 7. 서비스 시작

```bash
cd ~/actuary-portal
sudo systemctl start actuary-portal
docker compose logs -f
```

정상 기동 확인 사인:
- `server` 컨테이너 로그에 `Portal listening on 0.0.0.0:8888` 표시
- `bot` 로그에 `Application started` 표시
- `cloudflared` 로그에 `Registered tunnel connection` 표시

`Ctrl+C` 로 로그 뷰 종료.

### 상태 확인 명령
```bash
docker compose ps                  # 컨테이너 상태 (running / healthy)
curl http://127.0.0.1:8888/         # 내부 응답
curl https://portal.kkuks.com/      # 외부 응답
```

---

## 8. 검증 — 사용자 PC 꺼도 서비스 살아있나?

1. VM에서 위 3개 컨테이너가 모두 `running (healthy)` 상태
2. `https://portal.kkuks.com` 브라우저 접속 → 로그인 화면 표시
3. 태블릿에서도 동일한 URL 접속 성공
4. **사용자 PC 셧다운**
5. 5분 후 다시 https://portal.kkuks.com 접속 → 여전히 정상 → **✅ 이관 성공**

---

## 9. 이관 완료 후 정리

### 9-1. 기존 PC 처리
- `cloudflared` Windows 서비스는 **중지** (충돌 방지):
  ```powershell
  sc stop cloudflared
  sc config cloudflared start=disabled
  ```
- 로컬 개발/테스트용으로만 남기고, 실제 데이터 입력은 VM 인스턴스로만.

### 9-2. 사용자에게 안내
- **팀 전체 공지**: 이제 portal.kkuks.com 은 클라우드에서 상시 가동. PC 켜져 있을 필요 없음.
- 태블릿/스마트폰 홈 화면에 아이콘 등록 안내.

---

## 10. 운영 명령 치트시트

| 목적 | 명령 |
|-----|-----|
| 배포/업데이트 | `bash scripts/vps-deploy.sh` |
| 서비스 상태 | `docker compose ps` |
| 로그 실시간 | `docker compose logs -f server` |
| 서버만 재시작 | `docker compose restart server` |
| 전체 재시작 | `sudo systemctl restart actuary-portal` |
| 수동 백업 | `bash scripts/vps-backup.sh` |
| 헬스체크 | `bash scripts/vps-healthcheck.sh` |
| DB 접속 | `docker compose exec server sqlite3 /app/server/data/actuarial.db` |
| 디스크 사용 | `df -h /` + `du -sh server/data/backups` |
| 컨테이너 쉘 | `docker compose exec server sh` |

---

## 11. 자동복구 (선택)

`vps-healthcheck.sh` 를 5분마다 자동 실행하려면:

```bash
crontab -e
```

맨 아래 추가:
```
*/5 * * * * cd /home/ubuntu/actuary-portal && bash scripts/vps-healthcheck.sh
```

컨테이너 death, port 응답 없음, 봇 heartbeat 노화 시 자동 재시작.

---

## 12. 문제 해결 (FAQ)

### Q. `docker: permission denied` 에러
→ `newgrp docker` 실행 또는 재로그인.

### Q. cloudflared 컨테이너가 계속 restart
→ `docker compose logs cloudflared` 확인.
- 토큰 오타 시: `.env` 의 `CLOUDFLARE_TUNNEL_TOKEN` 재확인
- Zero Trust 대시보드에서 터널 상태 확인 (DOWN이면 토큰 재발급)

### Q. 브라우저에서 502 Bad Gateway
→ Zero Trust > Public Hostname 설정에서 URL이 `server:8888` (docker service name)이 맞는지 확인.
`localhost:8888` 또는 `127.0.0.1:8888` 이면 cloudflared 컨테이너에서 접근 불가.

### Q. 디스크 부족 (`no space left`)
```bash
docker system prune -af          # 오래된 이미지 정리
find server/data/backups -mtime +7 -delete  # 오래된 백업 정리
```

### Q. 메모리 부족 (OOM Kill)
Oracle A1.Flex 24GB면 여유 있음. `docker stats` 로 컨테이너별 사용량 확인.

---

## 13. 백업 & 복구

### 로컬로 다운로드 (수시)
```powershell
scp -i "C:\Users\USER\.ssh\oracle_key.pem" `
    "ubuntu@<VM IP>:~/actuary-portal/server/data/actuarial.db" `
    "C:\Users\USER\Downloads\actuarial_$(Get-Date -f yyyyMMdd).db"
```

### VM 재해 발생 시 복구
1. 새 VM 만들고 위 순서대로 재세팅
2. 로컬 백업 파일을 SCP로 업로드
3. `docker compose up -d`

---

**작성일**: 2026-09-04
**작성자**: Claude Code (Anthropic) via kmk3106@gmail.com
**리포지토리**: https://github.com/kmk3106-cmd/actuary-portal
