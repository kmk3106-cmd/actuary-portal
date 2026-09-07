# 계리결산팀 포탈 — 2시간 간격 헬스체크 (Task Scheduler 호출)
#
# 동작:
#   1. localhost:8888 TCP 응답 확인 (3초 타임아웃)
#   2. 정상이면 로그 "OK" 한 줄 남기고 종료
#   3. 비정상이면 pm2 resurrect 호출 (dump.pm2 의 앱 부활) 후 종료
# 설계: 절대 사용자에게 팝업·에러 안 띄움. 모든 오류 swallow.
#       복구 시도만 하고 검증은 다음 사이클(2시간 뒤)에 위임.

$ErrorActionPreference = 'SilentlyContinue'
$LogPath = "$env:USERPROFILE\.pm2\healthcheck.log"
$PM2     = "$env:APPDATA\npm\pm2.cmd"
$Stamp   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

function Write-Log($msg) {
    try { Out-File -FilePath $LogPath -InputObject "$Stamp $msg" -Append -Encoding UTF8 } catch {}
}

function Test-Portal {
    $tcp = $null
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect('127.0.0.1', 8888, $null, $null)
        if ($iar -eq $null) { return $false }
        $wait = $iar.AsyncWaitHandle.WaitOne(3000, $false)
        if (-not $wait) { return $false }
        return $tcp.Connected
    } catch {
        return $false
    } finally {
        if ($tcp -ne $null) { try { $tcp.Close() } catch {} }
    }
}

if (Test-Portal) {
    Write-Log "OK"
    exit 0
}

Write-Log "DOWN - resurrect"
try {
    & cmd.exe /c "`"$PM2`" resurrect" 2>&1 | Out-Null
} catch {}
