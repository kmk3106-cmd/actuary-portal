@echo off
cd /d "C:\Users\USER\actuary potal"
echo [1/2] Node.js 의존성 확인...
node --version
echo.
echo [2/2] Python 패키지 설치...
pip install openpyxl pandas python-dotenv python-docx jinja2 "python-telegram-bot==22.0"
echo.
echo 설치 완료. start.bat을 더블클릭하여 포탈을 실행하세요.
pause
