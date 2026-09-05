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

# 로컬 변경 감지 (actuarial.db 자연변동 제외)
$dirty = & git @G status --porcelain
$dirtyFiltered = @($dirty | Where-Object { $_ -and ($_ -notmatch 'actuarial\.db') })
if ($dirtyFiltered.Count -gt 0) { Log 'SKIP: dirty (user editing)'; exit 0 }

# fast-forward pull
& git @G pull --ff-only origin master | Out-Null
$after = (& git @G rev-parse HEAD).Trim()

if ($before -eq $after) { Log 'OK'; exit 0 }

# 변경 파일 목록
$changed = @(& git @G diff --name-only $before $after)
$restartNode = @($changed | Where-Object { $_ -match '^(server/|ecosystem\.config\.js$)' }).Count -gt 0
$restartBot  = @($changed | Where-Object { $_ -match '^bot/.*\.py$' }).Count -gt 0

$restarted = @()
if ($restartNode) {
    & net stop ActuaryPortalNode | Out-Null
    Start-Sleep -Seconds 2
    & net start ActuaryPortalNode | Out-Null
    $restarted += 'Node'
}
if ($restartBot) {
    & net stop ActuaryPortalBot | Out-Null
    Start-Sleep -Seconds 2
    & net start ActuaryPortalBot | Out-Null
    $restarted += 'Bot'
}

$shortBefore = $before.Substring(0, 7)
$shortAfter  = $after.Substring(0, 7)
$fileList    = ($changed | Select-Object -First 5) -join ','
$restartMsg  = if ($restarted.Count -gt 0) { "restarted:$($restarted -join ',')" } else { 'no-restart' }
Log "PULLED $shortBefore->$shortAfter $restartMsg files:$fileList"
