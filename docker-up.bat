@echo off
setlocal
title 계리결산포탈 Docker 기동
cd /d "%~dp0"

echo.
echo  ==============================================
echo   계리결산 포탈 — Docker 기동 (compose up -d)
echo  ==============================================
echo.

REM ── 1. 네이티브 프로세스 정리 (포트/봇 충돌 방지) ────
echo [1/3] 네이티브 프로세스 정리...
REM 운영 native node(server.js) 가 8888 점유 중이면 Docker가 못 바인드함.
REM 봇도 native 로 떠 있으면 텔레그램 중복응답 문제 발생.
taskkill /F /IM cloudflared.exe >nul 2>&1
REM ※ cloudflared 는 Windows 서비스로 별도 자동시작하도록 권장 (compose 범위 밖).
taskkill /F /IM node.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
timeout /t 1 /nobreak >nul
echo    완료.

REM ── 2. 이미지 빌드 (변경 없으면 캐시 활용) ───────────
echo.
echo [2/3] 이미지 빌드 / compose up...
docker compose up -d --build
if errorlevel 1 (
    echo [오류] docker compose 기동 실패. Docker Desktop 이 켜져 있는지 확인하세요.
    pause & exit /b 1
)

REM ── 3. 헬스체크 ─────────────────────────────────────
echo.
echo [3/3] 응답 확인...
timeout /t 4 /nobreak >nul
curl -s -o nul -w "portal-server HTTP %%{http_code}\n" http://127.0.0.1:8888/

echo.
echo  ----------------------------------------------
echo   로컬: http://localhost:8888
echo   외부: https://portal.kkuks.com (cloudflared 필요)
echo.
echo   로그:    docker compose logs -f
echo   정지:    docker compose down  (또는 docker-down.bat)
echo  ----------------------------------------------
echo.
pause
