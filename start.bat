@echo off
cd /d "C:\Users\USER\actuary potal"
start "Portal Server" cmd /k "node server/server.js"
timeout /t 2 /nobreak > nul
start "Telegram Bot" cmd /k "bot\run.bat"
timeout /t 1 /nobreak > nul
start "" "http://localhost:8888/login.html"
