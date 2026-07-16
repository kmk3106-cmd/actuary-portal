@echo off
setlocal
title actuary-portal - Windows Services Setup (nssm)
cd /d "%~dp0\.."

echo.
echo  ==============================================
echo   actuary-portal - Windows Services 등록 (nssm)
echo  ==============================================
echo.
echo  이 스크립트는 관리자 권한 필요.
echo  Node 서버·봇을 Windows Service 로 상시 가동시킴.
echo  세션/로그오프 무관하게 항상 살아있음. 프로세스 죽으면 자동 재시작.
echo.
pause

REM ── 0. nssm 설치 확인 ─────────────────────────
where nssm >nul 2>&1
if errorlevel 1 (
    echo [nssm 설치 중...]
    winget install NSSM.NSSM --silent --accept-source-agreements --accept-package-agreements
)

set NSSM=C:\Users\USER\AppData\Local\Microsoft\WinGet\Links\nssm.exe
set ROOT=%~dp0..
set NODE=C:\Program Files\nodejs\node.exe
set PYTHONW=C:\Users\USER\infinite_buy_v22\.venv\Scripts\pythonw.exe

REM ── 1. 기존 PM2 / Startup vbs 정리 ────────────
echo.
echo [1/4] 기존 PM2 / Startup vbs 무장해제 (충돌 방지)...
pm2 delete all >nul 2>&1
pm2 kill >nul 2>&1
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\actuary-portal-pm2-resurrect.vbs" (
    ren "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\actuary-portal-pm2-resurrect.vbs" "actuary-portal-pm2-resurrect.vbs.disabled" >nul 2>&1
)
schtasks /Change /TN ActuaryPortal-Healthcheck /Disable >nul 2>&1
echo    완료.

REM ── 2. 기존 서비스 제거 (재실행 대비) ─────────
echo.
echo [2/4] 기존 서비스 제거...
"%NSSM%" stop ActuaryPortalNode >nul 2>&1
"%NSSM%" remove ActuaryPortalNode confirm >nul 2>&1
"%NSSM%" stop ActuaryPortalBot >nul 2>&1
"%NSSM%" remove ActuaryPortalBot confirm >nul 2>&1
timeout /t 2 /nobreak >nul

REM ── 3. 서비스 등록 (경로에 공백 있으므로 AppDirectory + 상대경로) ─
echo.
echo [3/4] 서비스 등록...

"%NSSM%" install ActuaryPortalNode "%NODE%" >nul
"%NSSM%" set ActuaryPortalNode AppParameters "server\server.js" >nul
"%NSSM%" set ActuaryPortalNode AppDirectory "%ROOT%" >nul
"%NSSM%" set ActuaryPortalNode AppStdout "%ROOT%\logs\nssm-portal-out.log" >nul
"%NSSM%" set ActuaryPortalNode AppStderr "%ROOT%\logs\nssm-portal-err.log" >nul
"%NSSM%" set ActuaryPortalNode AppEnvironmentExtra "PORT=8888" "NODE_ENV=production" >nul
"%NSSM%" set ActuaryPortalNode Start SERVICE_AUTO_START >nul
"%NSSM%" set ActuaryPortalNode AppExit Default Restart >nul
"%NSSM%" set ActuaryPortalNode AppRestartDelay 3000 >nul
"%NSSM%" set ActuaryPortalNode Description "actuary-portal Node server (auto)" >nul

"%NSSM%" install ActuaryPortalBot "%PYTHONW%" >nul
"%NSSM%" set ActuaryPortalBot AppParameters "app.py" >nul
"%NSSM%" set ActuaryPortalBot AppDirectory "%ROOT%\bot" >nul
"%NSSM%" set ActuaryPortalBot AppStdout "%ROOT%\logs\nssm-bot-out.log" >nul
"%NSSM%" set ActuaryPortalBot AppStderr "%ROOT%\logs\nssm-bot-err.log" >nul
"%NSSM%" set ActuaryPortalBot AppEnvironmentExtra "PYTHONIOENCODING=utf-8" "PYTHONUTF8=1" >nul
"%NSSM%" set ActuaryPortalBot Start SERVICE_AUTO_START >nul
"%NSSM%" set ActuaryPortalBot AppExit Default Restart >nul
"%NSSM%" set ActuaryPortalBot AppRestartDelay 5000 >nul
"%NSSM%" set ActuaryPortalBot Description "actuary-portal Telegram bot (auto)" >nul
echo    완료.

REM ── 4. 서비스 시작 + 검증 ─────────────────────
echo.
echo [4/4] 서비스 시작...
net start ActuaryPortalNode
net start ActuaryPortalBot
timeout /t 5 /nobreak >nul

echo.
echo  --------------------------------------------
echo   상태:
sc query ActuaryPortalNode | findstr STATE
sc query ActuaryPortalBot  | findstr STATE
echo.
echo   HTTP:
curl -s -o nul -w "  localhost:8888   -> HTTP %%{http_code}\n" http://127.0.0.1:8888/
curl -s -o nul -w "  portal.kkuks.com -> HTTP %%{http_code}\n" https://portal.kkuks.com/
echo  --------------------------------------------
echo.
echo   관리:
echo     net start ActuaryPortalNode / net stop ActuaryPortalNode
echo     sc query ActuaryPortalNode
echo     로그: %ROOT%\logs\nssm-portal-*.log
echo   Cloudflared 는 Windows 서비스로 별도 관리 (변경 없음)
echo  --------------------------------------------
echo.
pause
