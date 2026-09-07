@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 계리결산포탈 - 강제 동기화 (진단+pull+재시작+검증)
cd /d "%~dp0"

echo.
echo  ============================================================
echo   계리결산포탈 - 강제 동기화 스크립트
echo  ============================================================
echo.

REM ── 1. 현재 상태 ────────────────────────────────
echo [1/6] 현재 저장소 상태 확인...
echo.
echo    ▷ 로컬 브랜치:
git rev-parse --abbrev-ref HEAD
echo    ▷ 로컬 최신 커밋:
git log --oneline -1
echo    ▷ dirty 파일 (있으면 pull 이 skip 됨):
git status --porcelain | findstr /v "actuarial.db" | findstr /v "portal-db.json"
echo.

REM ── 2. GitHub 최신본 fetch ────────────────────
echo [2/6] GitHub 에서 최신본 fetch...
git fetch origin master
if errorlevel 1 (echo    [오류] fetch 실패 - 네트워크 확인 & pause & exit /b 1)
echo    ▷ origin/master 최신 커밋:
git log origin/master --oneline -1
echo.

REM ── 3. dirty 있으면 stash ──────────────────────
echo [3/6] 로컬 변경 감지...
git diff --quiet HEAD -- . ":(exclude)server/data/actuarial.db" ":(exclude)server/data/portal-db.json"
if errorlevel 1 (
    echo    ▷ 커밋 안 된 변경 있음. 임시 저장 stash 처리...
    git stash push -m "force-sync auto-stash %DATE% %TIME%" -- . ":(exclude)server/data/actuarial.db" ":(exclude)server/data/portal-db.json"
    echo    ▷ stash 완료. 복구는 나중에: git stash pop
) else (
    echo    ▷ 로컬 변경 없음. OK.
)
echo.

REM ── 4. pull ────────────────────────────────────
echo [4/6] git pull --ff-only origin master ...
git pull --ff-only origin master
if errorlevel 1 (
    echo    [오류] fast-forward pull 실패. 이력이 갈라졌을 수 있음.
    echo    수동 진단: git log --oneline HEAD..origin/master
    pause & exit /b 2
)
echo.
echo    ▷ pull 후 최신 커밋:
git log --oneline -3
echo.

REM ── 5. 변경 파일 검증 ──────────────────────────
echo [5/6] 오늘 변경 사항 실제 반영 검증...
echo.
echo    ▷ executive-report.html - 팀장전용 가드 제거되었나?
findstr /C:"canViewLeaderScreens" executive-report.html >nul
if errorlevel 1 (
    echo       ✅ RBAC 가드 제거 확인 (canViewLeaderScreens 미검출)
) else (
    echo       ⚠ 아직 옛 코드 - RBAC 가드 남아있음
)
echo    ▷ personnel.html - 비번 초기화 버튼 있나?
findstr /C:"btn-card-reset" personnel.html >nul
if errorlevel 1 (
    echo       ⚠ 아직 옛 코드 - btn-card-reset 미검출
) else (
    echo       ✅ 비번 초기화 버튼 확인 (btn-card-reset 검출)
)
echo.

REM ── 6. 서비스 재시작 ───────────────────────────
echo [6/6] 서비스 상태 확인 및 필요시 재시작...
echo.
sc query ActuaryPortalNode 2>nul | findstr STATE
sc query ActuaryPortalBot 2>nul | findstr STATE
echo.
echo    ▷ Node 서버 재시작 (HTML/JS 변경만이면 스킵 가능하나 안전하게)...
net stop ActuaryPortalNode >nul 2>&1
timeout /t 2 /nobreak >nul
net start ActuaryPortalNode >nul 2>&1
timeout /t 3 /nobreak >nul
echo.

REM ── 7. HTTP 응답 확인 ──────────────────────────
echo  ------------------------------------------------------------
echo   HTTP 응답 확인:
curl -s -o nul -w "  localhost:8888   -> HTTP %%{http_code}\n" http://127.0.0.1:8888/
curl -s -o nul -w "  portal.kkuks.com -> HTTP %%{http_code}\n" https://portal.kkuks.com/
echo  ------------------------------------------------------------
echo.
echo   ✅ 동기화 완료
echo.
echo   확인 방법:
echo     1) 크롬에서 portal.kkuks.com 열기
echo     2) Ctrl+Shift+R 로 강제 새로고침 (캐시 무효화)
echo     3) 팀원 계정으로 로그인 -^> 02 팀 관리 -^> 임원 업무보고
echo        빨간 배너 없이 정상 로드되면 성공
echo     4) 팀장 김민국 계정 -^> 인사카드 -^> 강세진 매니저 카드
echo        [비번 초기화] 버튼 (호박색) 보이면 성공
echo.
pause
