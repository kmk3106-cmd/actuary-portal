@echo off
setlocal
title 계리결산포탈 부팅 자동시작 등록
cd /d "%~dp0"

echo.
echo  ============================================
echo   부팅 자동시작 (PM2 resurrect) 등록
echo  ============================================
echo.

REM ── 1. 깨질 수 있는 pm2-windows-startup Run-key 제거 ────
echo [1/3] HKCU\Run\PM2 제거 (pm2-windows-startup 가 만든 깨지기 쉬운 등록 정리)...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v PM2 /f >nul 2>&1
echo    완료.

REM ── 2. Startup 폴더에 vbs 2종 사본 배치 ──────────────
echo.
echo [2/3] %%APPDATA%%\Microsoft\Windows\Start Menu\Programs\Startup 에 vbs 2종 배치...
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy /Y "%~dp0pm2-resurrect.vbs"        "%STARTUP%\actuary-portal-pm2-resurrect.vbs" >nul
copy /Y "%~dp0claude-interactive.vbs"   "%STARTUP%\actuary-portal-claude-interactive.vbs" >nul
if errorlevel 1 (
    echo    [오류] 복사 실패.
    pause & exit /b 1
)
echo    "%STARTUP%\actuary-portal-pm2-resurrect.vbs"        (portal/bot 자동기동)
echo    "%STARTUP%\actuary-portal-claude-interactive.vbs"   (태블릿 원격용 인터랙티브 claude)

REM ── 3. 즉시 검증 (vbs 한 번 실행 → pm2 status) ────────
echo.
echo [3/3] vbs 즉시 실행 후 상태 확인...
wscript.exe "%STARTUP%\actuary-portal-pm2-resurrect.vbs"
timeout /t 5 /nobreak >nul
pm2 status

REM ── 4. 2시간 헬스체크 Task Scheduler 등록 ────────────
echo.
echo [4/4] 2시간 헬스체크 작업 등록 (Task Scheduler)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$n='ActuaryPortal-Healthcheck'; Unregister-ScheduledTask -TaskName $n -Confirm:$false -EA SilentlyContinue;" ^
  "$a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%~dp0healthcheck.ps1\"';" ^
  "$t1=New-ScheduledTaskTrigger -AtLogOn;" ^
  "$t2=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 2);" ^
  "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5);" ^
  "$p=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited;" ^
  "Register-ScheduledTask -TaskName $n -Action $a -Trigger @($t1,$t2) -Settings $s -Principal $p -Description '계리결산팀 포탈 2시간 헬스체크' | Out-Null"
if errorlevel 1 (echo    [경고] Task 등록 실패) else (echo    완료.)

echo.
echo  --------------------------------------------
echo   다음 부팅부터 자동 기동됩니다.
echo   2시간마다 다운 체크 → 다운 시 자동 복구 (조용히)
echo   로그: %USERPROFILE%\.pm2\healthcheck.log
echo   Cloudflared 는 Windows 서비스(Automatic)로 별도 관리 — 변경 없음.
echo  --------------------------------------------
echo.
pause
