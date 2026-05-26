@echo off
title 계리결산포탈 재기동 (PM2)
cd /d "%~dp0"
echo.
echo  계리결산 포탈 재기동 (코드 변경 즉시 반영)
echo.
git pull origin master
if errorlevel 1 echo [경고] git pull 실패 — 계속 진행
echo.
pm2 restart actuary-portal actuary-bot
echo.
pm2 status
echo.
echo  외부 접속: https://portal.kkuks.com
pause
