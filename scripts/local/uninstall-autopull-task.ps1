# 계리결산팀 포탈 - auto-pull 스케줄러 해제
# 관리자 권한 PowerShell 에서 실행

param(
    [string]$TaskName = "ActuaryPortal-AutoPull"
)

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()`
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[FAIL] 관리자 권한 필요" -ForegroundColor Red
    exit 1
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "[INFO] '$TaskName' 태스크 없음 (이미 해제됨)" -ForegroundColor Yellow
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] '$TaskName' 태스크 해제 완료" -ForegroundColor Green
