@echo off
title 계리결산포탈 PM2 상태
pm2 status
echo.
echo  ----------------------------------------------
echo   재기동:        pm2 restart actuary-portal actuary-bot
echo   서버만 재기동: pm2 restart actuary-portal
echo   봇만 재기동:   pm2 restart actuary-bot
echo   로그 보기:     pm2 logs            (Ctrl+C 로 종료)
echo   정지:          pm2 stop all
echo   완전 제거:     pm2 delete all  ^&^&  pm2 save --force
echo  ----------------------------------------------
pause
