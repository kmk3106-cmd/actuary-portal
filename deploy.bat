@echo off
setlocal
title 계리결산포탈 배포
cd /d "%~dp0"

echo.
echo  ============================================
echo   계리결산팀 포탈 배포 / 재시작
echo  ============================================
echo.

REM ── 1. 최신 코드 받기 ────────────────────────
echo [1/4] 최신 코드 받기 (git pull)...
git pull origin master
if errorlevel 1 (
    echo    [오류] git pull 실패. 네트워크 또는 충돌 확인 필요.
    pause & exit /b 1
)
echo    완료.

REM ── 2. 포탈 서버 재시작 ──────────────────────
echo.
echo [2/4] 포탈 서버 재시작...
taskkill /F /IM node.exe >nul 2>&1
timeout /t 1 /nobreak >nul
start "Portal Server" /MIN cmd /c "node server\server.js >> server\server.log 2>&1"
timeout /t 2 /nobreak >nul
echo    완료.

REM ── 3. 텔레그램 봇 재시작 ───────────────────
echo.
echo [3/4] 텔레그램 봇 재시작...
taskkill /F /IM python.exe >nul 2>&1
timeout /t 2 /nobreak >nul
start "Telegram Bot" /MIN cmd /c ""C:\Users\USER\infinite_buy_v22\.venv\Scripts\python.exe" bot\app.py >> bot\data\bot.log 2>&1"
timeout /t 2 /nobreak >nul
echo    완료.

REM ── 4. Cloudflare 터널 (없으면 시작) ─────────
echo.
echo [4/4] Cloudflare 터널 확인...
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | find /i "cloudflared.exe" >nul
if errorlevel 1 (
    echo    터널 시작 중...
    start "CF Tunnel" /MIN cmd /c "cloudflared tunnel run actuary-portal >> server\cloudflare.log 2>&1"
    timeout /t 2 /nobreak >nul
    echo    완료.
) else (
    echo    터널 이미 실행 중. 건너뜀.
)

REM ── 서버 응답 확인 ───────────────────────────
echo.
echo    서버 응답 확인 중...
timeout /t 3 /nobreak >nul
curl -s http://localhost:8888/tables/users >nul 2>&1
if errorlevel 1 (
    echo    [경고] 서버 응답 없음. 잠시 후 다시 확인하세요.
) else (
    echo    서버 정상 응답 확인.
)

echo.
echo  --------------------------------------------
echo   로컬  : http://localhost:8888
echo   외부  : https://portal.kkuks.com
echo  --------------------------------------------
echo.
pause
