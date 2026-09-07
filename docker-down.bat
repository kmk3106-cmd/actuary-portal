@echo off
setlocal
title 계리결산포탈 Docker 정지
cd /d "%~dp0"
echo.
echo  계리결산 포탈 — Docker 정지
echo.
docker compose down
echo.
echo  완료. (cloudflared Windows 서비스는 별도이며 영향 없음)
pause
