' 계리결산팀 포탈 — 부팅 자동시작 (PM2 resurrect)
'  Windows 사용자 로그인 시 호출. wscript 로 실행되어 콘솔 창을 띄우지 않고
'  pm2.cmd 의 절대경로를 직접 호출 → resurrect 로 dump.pm2 의 앱(actuary-portal, actuary-bot) 부활.
'
' 왜 자체 .vbs 인가:
'  pm2-windows-startup 의 invisible.vbs 는 %APPDATA%\npm\node_modules\... 안에 있어
'  npm cache prune·백신 격리·모듈 폴더 변동 시 사라지면서 wscript 가 "파일 없음" 오류를 띄움.
'  본 파일은 프로젝트 폴더 안에 위치 → 사용자가 제어, git 추적 가능, 사라지지 않음.
'
' 등록 위치: %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ (사본 또는 바로가기)
' 수동 실행: 파일 더블클릭 (성공 시 아무 창도 뜨지 않음 — pm2 status 로 확인)

Set sh = CreateObject("WScript.Shell")
' pm2.cmd 절대경로 (npm global bin). 큰따옴표 이스케이프 주의.
sh.Run """C:\Users\USER\AppData\Roaming\npm\pm2.cmd"" resurrect", 0, False
