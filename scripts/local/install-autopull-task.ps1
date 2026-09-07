# ═══════════════════════════════════════════════════════════════════
# 계리결산팀 포탈 - Windows Task Scheduler 자동 pull 등록
# ═══════════════════════════════════════════════════════════════════
# 관리자 권한 PowerShell 에서 실행 (우클릭 → 관리자 권한으로 실행)
#
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\install-autopull-task.ps1
#
# 옵션:
#   -RepoDir "C:\Users\USER\actuary potal"
#   -IntervalMinutes 5
#   -TaskName "ActuaryPortal-AutoPull"
# ═══════════════════════════════════════════════════════════════════

param(
    [string]$RepoDir          = "C:\Users\USER\actuary potal",
    [int]   $IntervalMinutes  = 5,
    [string]$TaskName         = "ActuaryPortal-AutoPull",
    [string]$Branch           = ""
)

# 관리자 권한 확인
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()`
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[FAIL] 관리자 권한 필요. PowerShell 을 '관리자 권한으로 실행' 후 재시도." -ForegroundColor Red
    exit 1
}

$scriptPath = Join-Path $RepoDir "scripts\local\auto-pull.ps1"
if (-not (Test-Path $scriptPath)) {
    Write-Host "[FAIL] auto-pull.ps1 없음: $scriptPath" -ForegroundColor Red
    exit 2
}

$argList = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -RepoDir `"$RepoDir`""
if ($Branch) { $argList += " -Branch `"$Branch`"" }

$action  = New-ScheduledTaskAction   -Execute "powershell.exe" -Argument $argList
$trigger = New-ScheduledTaskTrigger  -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::FromDays(3650))

# 부팅 시에도 트리거
$bootTrigger = New-ScheduledTaskTrigger -AtStartup
$bootTrigger.Delay = "PT1M"   # 부팅 1분 후 실행

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# 기존 태스크 있으면 삭제
Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger @($trigger, $bootTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Description "계리결산팀 포탈 자동 git pull + 서비스 재시작 ($IntervalMinutes 분 주기)" | Out-Null

Write-Host ""
Write-Host "  ✅ 등록 완료: $TaskName" -ForegroundColor Green
Write-Host ""
Write-Host "  ▷ 실행 주기 : $IntervalMinutes 분마다"
Write-Host "  ▷ 실행 계정 : SYSTEM"
Write-Host "  ▷ 스크립트  : $scriptPath"
Write-Host "  ▷ 저장소    : $RepoDir"
Write-Host "  ▷ 로그      : $RepoDir\logs\auto-pull.log"
Write-Host ""
Write-Host "  ▶ 즉시 1회 실행 테스트:" -ForegroundColor Cyan
Write-Host "     Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "  ▶ 상태 확인:" -ForegroundColor Cyan
Write-Host "     Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host ""
Write-Host "  ▶ 해제:" -ForegroundColor Cyan
Write-Host "     .\uninstall-autopull-task.ps1"
Write-Host ""
