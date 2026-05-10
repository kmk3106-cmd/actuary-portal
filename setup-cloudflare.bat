@echo off
setlocal enabledelayedexpansion
title Cloudflare 터널 초기 설정 (최초 1회)
cd /d "%~dp0"

echo.
echo  ============================================
echo   Cloudflare 터널 초기 설정 (최초 1회만)
echo  ============================================
echo.

REM ── 1. cloudflared 설치 확인 ─────────────────
echo [1/5] cloudflared 설치 확인...
where cloudflared >nul 2>&1
if errorlevel 1 (
    echo    설치 중... (완료 후 이 창을 닫고 다시 실행하세요)
    winget install Cloudflare.cloudflared --silent
    echo.
    echo    설치 완료. 새 터미널을 열어 다시 실행하세요.
    pause & exit /b
)
echo    완료.

REM ── 2. Cloudflare 로그인 ─────────────────────
echo.
echo [2/5] Cloudflare 로그인
echo    브라우저가 열리면 KKUKS.COM 선택 후 승인하세요.
echo.
cloudflared tunnel login
if errorlevel 1 ( echo    [오류] 로그인 실패. 재시도하세요. & pause & exit /b )
echo    로그인 완료.

REM ── 3. 터널 생성 + ID 추출 ───────────────────
echo.
echo [3/5] 터널 생성...
cloudflared tunnel create actuary-portal > "%TEMP%\cf_create.tmp" 2>&1
type "%TEMP%\cf_create.tmp"

for /f %%i in ('powershell -NoProfile -Command ^
  "Get-Content '%TEMP%\cf_create.tmp' | Select-String '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | %%{ $_.Matches.Value } | Select -First 1"') do set TUNNEL_ID=%%i

if "!TUNNEL_ID!"=="" (
    echo.
    echo    터널 ID를 자동으로 찾지 못했습니다.
    echo    위 출력에서 ID(xxxxxxxx-xxxx-...) 를 복사해 입력하세요:
    set /p TUNNEL_ID=   터널 ID:
)
echo    터널 ID: !TUNNEL_ID!

REM ── 4. config.yml 작성 ───────────────────────
echo.
echo [4/5] config.yml 작성...
set CF_DIR=%USERPROFILE%\.cloudflared
if not exist "!CF_DIR!" mkdir "!CF_DIR!"

(
echo tunnel: actuary-portal
echo credentials-file: !CF_DIR!\!TUNNEL_ID!.json
echo.
echo ingress:
echo   - hostname: portal.kkuks.com
echo     service: http://localhost:8888
echo   - service: http_status:404
) > "!CF_DIR!\config.yml"
echo    !CF_DIR!\config.yml 작성 완료.

REM ── 5. DNS 등록 ──────────────────────────────
echo.
echo [5/5] DNS 등록 (portal.kkuks.com)...
cloudflared tunnel route dns actuary-portal portal.kkuks.com
if errorlevel 1 (
    echo    [경고] DNS 설정 실패 또는 이미 등록됨. Cloudflare 대시보드에서 확인하세요.
) else (
    echo    DNS 등록 완료.
)

echo.
echo  ============================================
echo   초기 설정 완료!
echo.
echo   이후에는 deploy.bat 만 실행하면 됩니다.
echo   접속 주소: https://portal.kkuks.com
echo  ============================================
echo.
pause
