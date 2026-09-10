# actuary-portal - 자동 git pull (10분 주기)
# 클라우드/다른 PC 에서 push 된 변경을 로컬 서비스가 자동 반영.
# fast-forward pull 만. server/*·ecosystem·bot/*.py 변경 시 서비스 자동 재시작.
# 사용자 팝업/에러 없음. 로그만.

$ErrorActionPreference = 'SilentlyContinue'
$LogPath = "$env:USERPROFILE\.pm2\auto-git-pull.log"
$Repo    = "C:\Users\USER\actuary potal"
$Stamp   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$G       = @('-C', $Repo)

function Log($msg) {
    Out-File -FilePath $LogPath -InputObject "$Stamp $msg" -Append -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $Repo)) { Log 'SKIP: repo missing'; exit 0 }

$before = (& git @G rev-parse HEAD).Trim()

# 로컬 변경 감지 (tracked 파일만) — untracked(??) 는 무시, actuarial.db 자연변동 제외
# fast-forward pull 은 untracked 파일과 충돌 없으므로 통과시켜도 안전.
$dirty = & git @G status --porcelain
$dirtyFiltered = @($dirty | Where-Object {
    $_ -and
    ($_ -notmatch '^\?\?') -and              # untracked 무시
    ($_ -notmatch 'actuarial\.db')           # 서버 자연변동 DB 무시
})
if ($dirtyFiltered.Count -gt 0) { Log "SKIP: dirty tracked ($($dirtyFiltered.Count))"; exit 0 }

# fast-forward pull
& git @G pull --ff-only origin master | Out-Null
$after = (& git @G rev-parse HEAD).Trim()

if ($before -eq $after) { Log 'OK'; exit 0 }

# 변경 파일 목록
$changed = @(& git @G diff --name-only $before $after)
$restartNode = @($changed | Where-Object { $_ -match '^(server/|ecosystem\.config\.js$)' }).Count -gt 0
$restartBot  = @($changed | Where-Object { $_ -match '^bot/.*\.py$' }).Count -gt 0

# ── 견고한 재시작: Windows 서비스 → PM2 → node 직접 재기동 순으로 폴백 ──
# (서비스가 설치돼 있어야만 재시작되던 과거 버전 때문에 server/*.js 변경이
#  반영 안 되던 문제 방지. 어느 실행 방식이든 코드 변경이 확실히 반영되도록.)
function Restart-Node {
    if (Get-Service -Name 'ActuaryPortalNode' -ErrorAction SilentlyContinue) {
        & net stop ActuaryPortalNode | Out-Null; Start-Sleep -Seconds 2; & net start ActuaryPortalNode | Out-Null
        return 'service:ActuaryPortalNode'
    }
    if (Get-Service -Name 'actuary-portal' -ErrorAction SilentlyContinue) {
        Restart-Service -Name 'actuary-portal' -Force
        return 'service:actuary-portal'
    }
    if (Get-Command pm2 -ErrorAction SilentlyContinue) {
        & pm2 restart actuary-portal 2>&1 | Out-Null
        return 'pm2'
    }
    # 최후: server/server.js 를 실행 중인 node 프로세스만 종료 후 숨김창으로 재기동
    Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'server[\\/]+server\.js' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
    $out = Join-Path $Repo 'server\server.log'
    Start-Process -WindowStyle Hidden -FilePath 'node' -ArgumentList 'server/server.js' `
        -WorkingDirectory $Repo -RedirectStandardOutput $out -RedirectStandardError ($out + '.err')
    return 'node-direct'
}
function Restart-Bot {
    if (Get-Service -Name 'ActuaryPortalBot' -ErrorAction SilentlyContinue) {
        & net stop ActuaryPortalBot | Out-Null; Start-Sleep -Seconds 2; & net start ActuaryPortalBot | Out-Null
        return 'service:ActuaryPortalBot'
    }
    if (Get-Service -Name 'actuary-portal-bot' -ErrorAction SilentlyContinue) {
        Restart-Service -Name 'actuary-portal-bot' -Force
        return 'service:actuary-portal-bot'
    }
    if (Get-Command pm2 -ErrorAction SilentlyContinue) {
        & pm2 restart actuary-bot 2>&1 | Out-Null
        return 'pm2'
    }
    return 'manual-needed'
}

$restarted = @()
if ($restartNode) { $restarted += 'Node(' + (Restart-Node) + ')' }
if ($restartBot)  { $restarted += 'Bot('  + (Restart-Bot)  + ')' }

# 재시작 후 헬스체크 (실패해도 로그만)
if ($restartNode) {
    Start-Sleep -Seconds 2
    try {
        $code = (Invoke-WebRequest -Uri 'http://127.0.0.1:8888/login.html' -UseBasicParsing -TimeoutSec 5).StatusCode
        Log "HEALTH after restart: HTTP $code"
    } catch { Log "HEALTH after restart: no-response ($($_.Exception.Message))" }
}

$shortBefore = $before.Substring(0, 7)
$shortAfter  = $after.Substring(0, 7)
$fileList    = ($changed | Select-Object -First 5) -join ','
$restartMsg  = if ($restarted.Count -gt 0) { "restarted:$($restarted -join ',')" } else { 'no-restart' }
Log "PULLED $shortBefore->$shortAfter $restartMsg files:$fileList"
