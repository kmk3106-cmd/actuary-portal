# GitHub Actions 자동 배포 세팅 가이드 (VPS 이관 후)

> **목적**: VPS로 이관 완료 후, `master` 브랜치에 push 하면 자동으로 서버에 SSH 접속해서 배포.

**전제**: `docs/DEPLOY_ORACLE_VPS.md` 를 이미 완료해서 VPS 가 정상 가동 중.

---

## 1. Deploy Key 생성 (VPS 에서)

VPS 에 SSH 접속한 상태에서:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/gh_deploy -N "" -C "github-actions-deploy"
cat ~/.ssh/gh_deploy.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
cat ~/.ssh/gh_deploy   # 프라이빗 키 표시 (다음 단계에서 복사)
```

출력된 프라이빗 키 전체 (`-----BEGIN OPENSSH PRIVATE KEY-----` 부터 `-----END OPENSSH PRIVATE KEY-----` 까지) 복사.

---

## 2. GitHub Secrets 등록

브라우저에서:
1. `https://github.com/kmk3106-cmd/actuary-portal/settings/secrets/actions`
2. **New repository secret** 클릭하여 아래 항목들 추가:

| Secret 이름 | 값 |
|------------|-----|
| `VPS_HOST` | Oracle Cloud VM 의 Public IP (예: `129.xxx.xxx.xxx`) |
| `VPS_USER` | `ubuntu` |
| `VPS_SSH_KEY` | 1번에서 복사한 프라이빗 키 **전체** |
| `VPS_PORT` | (선택) 기본 22. 변경했으면 지정 |
| `VPS_INSTALL_DIR` | (선택) 기본 `/home/ubuntu/actuary-portal` |

---

## 3. 로컬 auto-pull 해제

VPS 이관 후에는 로컬 auto-pull 태스크가 필요 없습니다 (충돌 방지):

```powershell
# Windows PC 에서 (관리자 권한)
cd "C:\Users\USER\actuary potal\scripts\local"
.\uninstall-autopull-task.ps1
```

또한 로컬 Windows Services (`nssm` 로 등록한 것들) 중지 + disable:
```powershell
sc stop actuary-portal
sc config actuary-portal start=disabled
sc stop cloudflared
sc config cloudflared start=disabled
```

---

## 4. 테스트

작은 변경 (예: README 수정) 해서 master 에 push:

```bash
echo "" >> README.md
git commit -am "test: CI deploy trigger"
git push origin master
```

브라우저에서 확인:
`https://github.com/kmk3106-cmd/actuary-portal/actions`

`Deploy to Oracle Cloud VPS` 워크플로우가 자동 실행되고, 성공 시 초록 체크. 실패하면 로그 확인.

---

## 5. 배포 흐름

```
   [로컬/클라우드에서 git push origin master]
                    ↓
      [GitHub Actions 워크플로우 자동 트리거]
                    ↓
        SSH 접속 (deploy_key + VPS_HOST)
                    ↓
    ssh ubuntu@VPS "cd ~/actuary-portal && bash scripts/vps-deploy.sh"
                    ↓
       vps-deploy.sh 가 실행:
         1. git pull --ff-only
         2. docker compose build --pull
         3. docker compose up -d --remove-orphans
         4. 헬스체크 대기
                    ↓
        GitHub Actions 에서 curl http://127.0.0.1:8888/ 로
        정상 응답 확인 (2번 헬스체크)
                    ↓
                  완료 ✅
```

---

## 6. 트러블슈팅

### Q. Workflow 가 "Skip" 됨
→ Secrets 미등록. Repo Settings > Secrets 확인.

### Q. `Permission denied (publickey)`
→ `VPS_SSH_KEY` 값에 `-----BEGIN...` `-----END...` 헤더/푸터 포함되었는지 확인.
→ VPS 의 `~/.ssh/authorized_keys` 에 등록되었는지 확인.

### Q. `Host key verification failed`
→ 워크플로우가 자동으로 `ssh-keyscan` 하지만, VPS 가 SSH 재설정된 경우 실패 가능.
→ VPS 에서 `sudo systemctl restart ssh` 후 재시도.

### Q. `docker compose: command not found`
→ VPS 초기 세팅 스크립트 (`vps-init.sh`) 미실행. Docker Compose plugin 확인:
`docker compose version` (VPS 에서)

### Q. 헬스체크 실패
→ `.env` 파일에 필수 값 (TELEGRAM_BOT_TOKEN, CLOUDFLARE_TUNNEL_TOKEN) 누락 가능.
→ VPS 에서 `docker compose logs server` 확인.

### Q. 배포는 성공했는데 사이트 접속 안 됨
→ cloudflared 컨테이너 상태 확인:
`docker compose ps cloudflared`
→ Cloudflare Zero Trust > Networks > Tunnels 에서 상태 확인.

---

## 7. 롤백

문제가 생기면 이전 커밋으로 롤백:

```bash
# 로컬에서
git revert HEAD
git push origin master
# → Actions 가 자동으로 이전 상태 배포
```

또는 VPS 에 직접 SSH:
```bash
ssh ubuntu@<VPS-IP>
cd ~/actuary-portal
git log --oneline -5
git reset --hard <원하는_커밋_해시>
bash scripts/vps-deploy.sh
```

---

## 8. 브랜치 전략

기본 워크플로우는 `master` 만 배포. 다른 브랜치도 배포하려면 `.github/workflows/deploy-vps.yml` 의 `on.push.branches` 수정.

Claude Code 세션에서 `claude/*` 브랜치로 작업 → 검토 후 `master` 로 병합 → 자동 배포. 이 흐름이 안전합니다.
