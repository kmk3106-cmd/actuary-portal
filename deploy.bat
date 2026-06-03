@echo off
chcp 65001 >nul
setlocal
title actuary-portal deploy (PM2)
cd /d "%~dp0"

REM 코드페이지를 UTF-8(65001) 로 전환해 한글 깨짐 방지.
REM 본 스크립트는 PM2 기반 — 구버전의 taskkill /F /IM node.exe 패턴 제거.
REM   (실수로 Claude Code 등 다른 node 프로세스까지 죽일 위험 차단)
REM Cloudflared 는 Windows 서비스(StartType=Automatic) 로 별도 관리.

echo.
echo  ==============================================
echo   actuary-portal — git pull + PM2 restart
echo  ==============================================
echo.

REM ── 1. 최신 코드 받기 ─────────────────────────
echo [1/3] git pull origin master ...
git pull origin master
if errorlevel 1 (
    echo    [WARN] git pull 실패 — 네트워크/충돌 확인 권장, 그래도 PM2 restart 는 진행.
)
echo.

REM ── 2. PM2 앱 재시작 (코드 변경 즉시 반영) ────
echo [2/3] PM2 restart ...
pm2 restart actuary-portal actuary-bot
if errorlevel 1 (
    echo    [INFO] restart 실패 — daemon 미가동 가능. pm2 resurrect 시도:
    pm2 resurrect
)
echo.

REM ── 3. 응답 확인 ──────────────────────────────
echo [3/3] HTTP 응답 확인 ...
timeout /t 3 /nobreak >nul
curl -s -o nul -w "  localhost:8888   -> HTTP %%{http_code}\n" http://127.0.0.1:8888/
curl -s -o nul -w "  portal.kkuks.com -> HTTP %%{http_code}\n" https://portal.kkuks.com/

echo.
echo  ----------------------------------------------
echo   pm2 status   : pm2 status
echo   pm2 logs     : pm2 logs --lines 50
echo   외부 접속    : https://portal.kkuks.com
echo  ----------------------------------------------
echo.
pause
