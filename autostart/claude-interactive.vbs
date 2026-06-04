' 계리결산팀 포탈 — 부팅 시 인터랙티브 claude 자동 기동
'   목적: remoteControlAtStartup=true 덕분에 새 claude 세션이 자동으로 Remote Control 활성화
'         → 태블릿 Claude 앱에서 부팅 직후부터 접속 가능
'   디자인:
'     - PM2 spawn 이 아닌 인터랙티브 모드 = Trusted Device enrollment 만료 영향 안 받음
'       (만료 시 한 번 /login 만 사용자가 누르면 됨 — 그러면 또 며칠~몇 주 유효)
'     - claude-remote 를 PM2 데몬으로 띄울 때처럼 무한 재시작 → 데몬 다운 위험 없음
'   창 동작:
'     - 인자 7 = SW_SHOWMINNOACTIVE: 작업표시줄에만 보이고 활성화 안 됨 (사용자 작업 안 가림)
'     - 인자 0 (hidden) 도 시도해봤으나 TTY 없이 claude 가 즉시 종료될 위험 있어 7 사용
'   stdin 으로 nul 안 줘야 인터랙티브 모드 유지됨 (cmd /k 가 그 역할)
'
'  활성화 만료 시: 작업표시줄의 'C:\WINDOWS\...cmd.exe' 클릭해 키우고 안에서 `/login` 한 번 입력.
'  중지하려면: 그 cmd 창에서 `/exit` 또는 창 닫기.

Set sh = CreateObject("WScript.Shell")
' chcp 65001 로 UTF-8 코드페이지 (한글 깨짐 방지) → claude 실행
sh.Run "cmd.exe /k ""chcp 65001 >nul & cd /d ""C:\Users\USER\actuary potal"" & claude""", 7, False
