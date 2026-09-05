# 로컬 PC 자동 git pull 세팅 가이드

> **목적**: 클라우드 세션에서 `git push` 하면 로컬 PC 가 스스로 5분 안에 pull + 필요한 서비스만 재시작.

**소요시간**: 5분
**전제조건**: Windows PC, git 설치, 저장소 이미 clone 되어 있음, 관리자 권한

---

## 왜 필요한가

- Claude Code 클라우드 세션에서 편집 → git push
- 로컬 PC 는 여전히 옛 코드로 서비스 중 → **수동으로 `git pull` 안 하면 반영 안 됨**
- 이 태스크를 스케줄러에 등록하면 자동 반영

**⚠️ 이건 "PC 켜져 있는 상태에서 반영 편해지는 것" 이지, "24시간 상시 가동" 을 해결하는 건 아닙니다.**
완전 무인 운영은 `docs/DEPLOY_ORACLE_VPS.md` 참조.

---

## 설치 (한 번만)

1. **PowerShell을 관리자 권한으로 실행**
   - 시작 메뉴 → PowerShell 검색 → 우클릭 → "관리자 권한으로 실행"

2. **저장소로 이동 + ExecutionPolicy 완화 (현 세션만)**
   ```powershell
   cd "C:\Users\USER\actuary potal\scripts\local"
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```

3. **태스크 등록 (5분 주기 기본값)**
   ```powershell
   .\install-autopull-task.ps1
   ```

   경로가 다르면:
   ```powershell
   .\install-autopull-task.ps1 -RepoDir "D:\repos\actuary-portal" -IntervalMinutes 3
   ```

   특정 브랜치만 추적하려면:
   ```powershell
   .\install-autopull-task.ps1 -Branch "master"
   ```

4. **즉시 1회 실행 테스트**
   ```powershell
   Start-ScheduledTask -TaskName "ActuaryPortal-AutoPull"
   Get-Content "C:\Users\USER\actuary potal\logs\auto-pull.log" -Tail 20
   ```

---

## 동작 방식

```
[Task Scheduler 5분 주기]
       ↓
scripts\local\auto-pull.ps1
       ↓
  git fetch origin <현재 브랜치>
       ↓
  새 커밋 있음?
    ├─ 없음 → 종료 (로그만)
    └─ 있음 → git pull --ff-only
              ↓
        변경된 파일 종류 분석
              ├─ server/*.js         → Node 서버 재시작 (nssm/pm2/직접)
              ├─ bot/*.py            → Python 봇 재시작
              ├─ package.json        → npm install
              ├─ requirements.txt    → pip install
              └─ *.html, *.css 만    → 재시작 불필요
              ↓
        HTTP 200 헬스체크
              ↓
        로그 기록 → 종료
```

---

## 재시작 방식 자동 감지

스크립트가 다음 순서로 시도:

1. **Windows Service (nssm 등록된 경우)** — `actuary-portal`, `actuary-portal-bot` 서비스가 있으면 그것을 재시작
2. **PM2** — `pm2` 커맨드가 있으면 `pm2 restart <name>`
3. **직접 프로세스** — 위 둘 다 없으면 `taskkill /F /IM node.exe` 후 새로 기동

기존 세팅이 nssm이든 PM2든 그대로 두면 됩니다.

---

## 로그 확인

```powershell
# 실시간 tail
Get-Content "C:\Users\USER\actuary potal\logs\auto-pull.log" -Wait -Tail 20

# 지난 실행 결과
Get-ScheduledTaskInfo -TaskName "ActuaryPortal-AutoPull"
```

로그 예시:
```
[2026-09-05 09:00:00] [INFO] ==== auto-pull 시작 (branch=master, dryRun=False) ====
[2026-09-05 09:00:01] [GIT]  From https://github.com/kmk3106-cmd/actuary-portal
[2026-09-05 09:00:01] [GIT]     7654cc8..2b4b56c  master     -> origin/master
[2026-09-05 09:00:01] [INFO] 새 커밋 감지: 7654cc8 → 2b4b56c
[2026-09-05 09:00:01] [INFO] 변경 파일 수: 11
[2026-09-05 09:00:02] [GIT]  Updating 7654cc8..2b4b56c
[2026-09-05 09:00:02] [INFO] 정적 파일만 변경 - 서버 재시작 불필요
[2026-09-05 09:00:04] [OK]   포탈 응답 정상 (HTTP 200)
[2026-09-05 09:00:04] [OK]   ==== auto-pull 완료 ====
```

---

## 옵션 & 트러블슈팅

### 옵션

| 스위치 | 설명 |
|-------|-----|
| `-DryRun` | 실제 pull/재시작 없이 시뮬레이션만 (로그로 확인) |
| `-Force` | 로컬에 커밋 안 된 변경 있어도 강제 pull (**주의**) |
| `-Branch <이름>` | 현재 체크아웃과 상관없이 특정 브랜치 추적 |

### 자주 하는 실수

**Q. 로컬 변경 있어서 pull 안 됨** → 커밋하거나 stash 하고 재시도.
```powershell
git stash push -m "auto-pull 전 임시 저장"
```

**Q. "This script cannot be loaded" 에러**
→ ExecutionPolicy 미완화. 위 2번 명령 재실행.

**Q. 태스크는 등록됐는데 실행 안 됨**
→ SYSTEM 계정으로 실행되므로 저장소 폴더 권한 확인.
`icacls "C:\Users\USER\actuary potal" /grant "SYSTEM:(OI)(CI)F"`

**Q. 재시작이 계속 실패**
→ 서비스가 nssm 등록되어 있으면 서비스 이름 확인:
`Get-Service *actuary*`
스크립트 상단의 서비스명 (`actuary-portal`, `actuary-portal-bot`)과 다르면 수정.

**Q. Fast-forward 아님 에러**
→ 로컬에서 커밋을 만들었거나 다른 브랜치와 이력이 갈라짐. 수동으로 정리 필요.

---

## 해제

```powershell
cd "C:\Users\USER\actuary potal\scripts\local"
.\uninstall-autopull-task.ps1
```

---

## VPS 이관 후에는 어떻게?

VPS 로 이관하고 나면:
1. 로컬 auto-pull 태스크는 **해제** (충돌 방지)
2. 대신 GitHub Actions (`.github/workflows/deploy-vps.yml`) 활성화
3. `docs/CI_DEPLOY.md` 참조

이관 후에는 git push → GitHub → SSH로 VPS → docker compose 재시작 이 **전자동**으로 흐릅니다.
