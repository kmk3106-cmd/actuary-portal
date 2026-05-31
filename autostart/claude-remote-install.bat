@echo off
setlocal
title Claude Remote Control 영구 등록 (PM2)
cd /d "%~dp0\.."

echo.
echo  ============================================
echo   Claude Code Remote Control PM2 등록
echo  ============================================
echo.
echo  ⚠ 사전 조건:
echo     반드시 인터랙티브 Claude Code 에서 `/login` 으로
echo     이 기기를 "Trusted Device" 로 등록해두어야 합니다.
echo     등록 안 된 상태에서는 "device is not enrolled" 오류로 거부됩니다.
echo.
set /p READY="등록 마쳤습니까? (Y/N): "
if /I not "%READY%"=="Y" (
    echo.
    echo  먼저 새 터미널에서 `claude` 실행 → `/login` → 브라우저 등록 후 다시 이 배치 실행하세요.
    pause & exit /b 1
)

echo.
echo [1/3] PM2 앱으로 추가 + 즉시 기동...
pm2 start "C:\Users\USER\AppData\Local\Microsoft\WinGet\Links\claude.exe" ^
    --name claude-remote ^
    --interpreter none ^
    --cwd "C:\Users\USER\actuary potal" ^
    --restart-delay 10000 ^
    --max-restarts 30 ^
    --min-uptime 30s ^
    --output logs\pm2-claude-remote-out.log ^
    --error  logs\pm2-claude-remote-error.log ^
    --log-date-format "YYYY-MM-DD HH:mm:ss Z" ^
    -- remote-control --capacity 32 --spawn worktree
if errorlevel 1 (echo    [오류] PM2 start 실패. & pause & exit /b 1)

echo.
echo [2/3] 12초 대기 후 상태 확인...
timeout /t 12 /nobreak >nul
pm2 status

echo.
echo [3/3] dump.pm2 저장 (부팅 시 자동 부활)...
pm2 save
if errorlevel 1 (echo    [경고] save 실패 — 수동 'pm2 save' 필요)

echo.
echo  --------------------------------------------
echo   확인:
echo     1) pm2 logs claude-remote --lines 30  (Connected 메시지 + URL)
echo     2) https://claude.ai/code  의 세션 목록에 표시
echo     3) 태블릿 Claude 앱 → 세션 목록에서 선택
echo.
echo   "device is not enrolled" 오류가 보이면:
echo     - pm2 delete claude-remote
echo     - 새 터미널 claude → /login → 브라우저 등록
echo     - 이 배치 다시 실행
echo  --------------------------------------------
echo.
pause
