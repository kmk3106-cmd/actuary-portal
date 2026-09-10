@echo off
chcp 65001 >nul
title 계리결산포탈 - 최신 코드 반영 (Pull + 서버 재시작)
REM ============================================================
REM  더블클릭 한 번으로:
REM   1) 최신 코드 내려받기 (git pull)
REM   2) 실행 중인 node 서버 종료
REM   3) 서버 재시작 (server.js 변경까지 반영)
REM  ※ 이 배치가 있는 폴더(=저장소)를 기준으로 동작하므로 경로 수정 불필요
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo    계리결산팀 포탈 - 최신 코드 반영
echo    폴더: %cd%
echo ============================================================
echo.

echo [1/3] 최신 코드 내려받기 (git pull origin master)...
git pull origin master
if errorlevel 1 (
  echo.
  echo   [경고] git pull 실패.
  echo   - 로컬에 저장 안 한 변경이 있거나 인터넷 문제일 수 있습니다.
  echo   - 화면 메시지를 확인한 뒤 다시 실행하세요.
  echo.
  pause
  exit /b 1
)
echo.

echo [2/3] 실행 중인 서버(node) 종료...
taskkill /F /IM node.exe >nul 2>&1
if errorlevel 1 (
  echo   - 실행 중이던 서버 없음 ^(처음 켜는 경우 정상^)
) else (
  echo   - 기존 서버 종료 완료
)
timeout /t 2 /nobreak >nul
echo.

echo [3/3] 서버 재시작...
start "Portal Server" cmd /k "node server/server.js"
echo   - 새 서버 창을 띄웠습니다. ^(이 창은 닫지 마세요^)
timeout /t 3 /nobreak >nul
echo.

echo 서버 응답 확인 중...
powershell -NoProfile -Command "try{$c=(Invoke-WebRequest -Uri 'http://127.0.0.1:8888/login.html' -UseBasicParsing -TimeoutSec 6).StatusCode; Write-Host ('   [정상] 서버 응답 HTTP '+$c) -ForegroundColor Green}catch{Write-Host '   [대기] 아직 응답 없음 - 5~10초 후 브라우저에서 확인하세요' -ForegroundColor Yellow}"
echo.

echo ============================================================
echo    반영 완료!
echo    - 브라우저에서 Ctrl+Shift+R 로 강력 새로고침 하세요.
echo    - 내부:  http://localhost:8888/login.html
echo    - 외부:  https://portal.kkuks.com
echo ============================================================
echo.
pause
