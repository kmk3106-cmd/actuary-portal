# ═══════════════════════════════════════════════════════════════════
# 계리결산팀 포탈 - 로컬 PC 자동 git pull + 스마트 재시작
# ═══════════════════════════════════════════════════════════════════
# 실행 조건:
#   1) 저장소에 새 커밋이 있으면 pull
#   2) 변경 파일 종류에 따라 필요한 서비스만 재시작
#      - server/**/*.js        → node 서버 재시작
#      - bot/**/*.py           → python 봇 재시작
#      - *.html, *.css, *.png  → 재시작 불필요 (서버가 디스크에서 서빙)
#
# 로그: <저장소>\logs\auto-pull.log
# ═══════════════════════════════════════════════════════════════════

param(
    [string]$RepoDir = "C:\Users\USER\actuary potal",
    [string]$Branch  = "",   # 비우면 현재 체크아웃된 브랜치 사용
    [switch]$Force,          # 로컬 변경 무시하고 강제 pull (주의)
    [switch]$DryRun          # 실제 pull/재시작 안 하고 시뮬레이션만
)

$ErrorActionPreference = "Stop"
$LogDir  = Join-Path $RepoDir "logs"
$LogFile = Join-Path $LogDir "auto-pull.log"

function Write-Log {
    param([string]$Level, [string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Level] $Msg"
    Write-Host $line
    try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 } catch { }
}

function Restart-NodeServer {
    Write-Log "INFO" "Node 서버 재시작 시도..."
    if ($DryRun) { Write-Log "DRY" "  (dry-run) node.exe kill + node server\server.js"; return }
    # nssm 서비스 우선 시도
    $svc = Get-Service -Name "actuary-portal" -ErrorAction SilentlyContinue
    if ($svc) {
        Restart-Service -Name "actuary-portal" -Force
        Write-Log "OK"   "  Windows Service 재시작 완료"
        return
    }
    # PM2 시도
    $pm2 = Get-Command pm2 -ErrorAction SilentlyContinue
    if ($pm2) {
        pm2 restart actuary-portal 2>&1 | Out-Null
        Write-Log "OK"   "  PM2 재시작 완료"
        return
    }
    # 최후: taskkill + start
    taskkill /F /IM node.exe 2>$null | Out-Null
    Start-Sleep -Seconds 1
    $logOut = Join-Path $RepoDir "server\server.log"
    Start-Process -WindowStyle Hidden -FilePath "node" `
        -ArgumentList "server\server.js" `
        -WorkingDirectory $RepoDir `
        -RedirectStandardOutput $logOut `
        -RedirectStandardError  ($logOut + ".err")
    Write-Log "OK" "  node 프로세스 직접 재기동"
}

function Restart-PythonBot {
    Write-Log "INFO" "Python 봇 재시작 시도..."
    if ($DryRun) { Write-Log "DRY" "  (dry-run) python bot 재시작"; return }
    $svc = Get-Service -Name "actuary-portal-bot" -ErrorAction SilentlyContinue
    if ($svc) {
        Restart-Service -Name "actuary-portal-bot" -Force
        Write-Log "OK" "  Windows Service 재시작 완료"
        return
    }
    $pm2 = Get-Command pm2 -ErrorAction SilentlyContinue
    if ($pm2) {
        pm2 restart actuary-bot 2>&1 | Out-Null
        Write-Log "OK" "  PM2 재시작 완료"
        return
    }
    # deploy.bat 참고: python.exe 통째로 kill 은 위험. 봇만 kill 하려면 PID 필요.
    Write-Log "WARN" "  서비스/PM2 미등록 - 수동으로 봇 재시작 필요"
}

# ─── 시작 ─────────────────────────────────────────
try {
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
} catch { }

if (-not (Test-Path $RepoDir)) {
    Write-Log "FAIL" "저장소 경로 없음: $RepoDir"
    exit 2
}

Push-Location $RepoDir
try {
    # git 상태 확인
    $currentBranch = (git rev-parse --abbrev-ref HEAD 2>&1).Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Log "FAIL" "git 저장소 아님: $RepoDir"
        exit 3
    }
    if (-not $Branch) { $Branch = $currentBranch }

    Write-Log "INFO" "==== auto-pull 시작 (branch=$Branch, dryRun=$DryRun) ===="

    # 로컬 변경 감지
    $dirty = (git status --porcelain 2>&1)
    if ($dirty -and -not $Force) {
        Write-Log "WARN" "로컬에 커밋 안 된 변경 있음 - pull 스킵 (-Force 옵션으로 강제 가능)"
        Write-Log "WARN" ($dirty -join "`n")
        exit 0
    }

    # fetch
    git fetch origin $Branch 2>&1 | ForEach-Object { Write-Log "GIT" $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "FAIL" "git fetch 실패"
        exit 4
    }

    # ahead/behind 계산
    $localSha  = (git rev-parse HEAD).Trim()
    $remoteSha = (git rev-parse "origin/$Branch").Trim()
    if ($localSha -eq $remoteSha) {
        Write-Log "INFO" "변경 없음 (local=$($localSha.Substring(0,7)))"
        exit 0
    }

    Write-Log "INFO" "새 커밋 감지: $($localSha.Substring(0,7)) → $($remoteSha.Substring(0,7))"

    # 변경된 파일 목록 (재시작 판단용)
    $changed = @(git diff --name-only HEAD "origin/$Branch" 2>&1)
    Write-Log "INFO" "변경 파일 수: $($changed.Count)"

    # pull
    if ($DryRun) {
        Write-Log "DRY" "(dry-run) git pull --ff-only origin $Branch"
    } else {
        git pull --ff-only origin $Branch 2>&1 | ForEach-Object { Write-Log "GIT" $_ }
        if ($LASTEXITCODE -ne 0) {
            Write-Log "FAIL" "git pull 실패 - fast-forward 아님. -Force 로 재시도하거나 수동 병합 필요."
            exit 5
        }
    }

    # npm 의존성 변경?
    if ($changed -match "package\.json|package-lock\.json") {
        Write-Log "INFO" "package.json 변경 감지 → npm install"
        if (-not $DryRun) {
            npm install --omit=dev 2>&1 | ForEach-Object { Write-Log "NPM" $_ }
        }
    }
    # pip 의존성 변경?
    if ($changed -match "bot/requirements\.txt") {
        Write-Log "INFO" "requirements.txt 변경 감지 → pip install"
        if (-not $DryRun) {
            pip install -r "bot\requirements.txt" 2>&1 | ForEach-Object { Write-Log "PIP" $_ }
        }
    }

    # 재시작 필요성 판단
    $needsServerRestart = $changed | Where-Object { $_ -match "^server/.*\.(js|json)$" -or $_ -match "^ecosystem\.config\.js$" -or $_ -match "^package.*\.json$" }
    $needsBotRestart    = $changed | Where-Object { $_ -match "^bot/.*\.py$" -or $_ -match "^bot/requirements\.txt$" }

    if ($needsServerRestart) {
        Restart-NodeServer
    } else {
        Write-Log "INFO" "정적 파일만 변경 - 서버 재시작 불필요"
    }

    if ($needsBotRestart) {
        Restart-PythonBot
    }

    # 헬스체크
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8888/" -UseBasicParsing -TimeoutSec 5
        Write-Log "OK" "포탈 응답 정상 (HTTP $($resp.StatusCode))"
    } catch {
        Write-Log "WARN" "포탈 응답 없음: $($_.Exception.Message)"
    }

    Write-Log "OK" "==== auto-pull 완료 ===="
    exit 0
}
catch {
    Write-Log "FAIL" "예외 발생: $($_.Exception.Message)"
    Write-Log "FAIL" $_.ScriptStackTrace
    exit 1
}
finally {
    Pop-Location
}
