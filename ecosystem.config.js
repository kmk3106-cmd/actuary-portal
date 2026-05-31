module.exports = {
  apps: [
    {
      name: 'actuary-portal',
      script: 'server/server.js',
      interpreter: 'node',
      cwd: '.',
      watch: false,
      autorestart: true,
      restart_delay: 3000,
      max_restarts: 50,
      min_uptime: '10s',
      out_file: 'logs/pm2-portal-out.log',
      error_file: 'logs/pm2-portal-error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      env: {
        NODE_ENV: 'production',
        PORT: '8888',
      },
    },
    {
      name: 'actuary-bot',
      script: 'app.py',
      // 봇 의존성(telegram/pandas/openpyxl/dotenv)이 설치된 venv.
      // pythonw.exe = 콘솔 창이 뜨지 않는 GUI 서브시스템 파이썬. 백그라운드 서비스용.
      //  - python.exe 였을 때 PM2 가 봇 콘솔 창을 띄워서 사용자가 실수로 닫으면 봇 다운.
      //  - 로깅은 bot/data/bot.log 파일핸들러로 별도 기록되므로 stdout 손실 무관.
      interpreter: 'C:\\Users\\USER\\infinite_buy_v22\\.venv\\Scripts\\pythonw.exe',
      cwd: './bot',
      watch: false,
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 50,
      min_uptime: '10s',
      out_file: '../logs/pm2-bot-out.log',
      error_file: '../logs/pm2-bot-error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      env: {
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
      },
    },
    {
      // 태블릿/모바일에서 상시 원격 접속 가능하도록 Claude Code Remote Control 서버 상시 가동.
      // 사전 조건: 이 기기가 Trusted Device 로 등록돼 있어야 함 (인터랙티브 claude 세션에서 /login 으로 enrollment).
      // capacity 32, 새 세션마다 git worktree 격리.
      name: 'claude-remote',
      script: 'C:\\Users\\USER\\AppData\\Local\\Microsoft\\WinGet\\Links\\claude.exe',
      args: 'remote-control --capacity 32 --spawn worktree',
      interpreter: 'none',
      cwd: 'C:\\Users\\USER\\actuary potal',
      watch: false,
      autorestart: true,
      restart_delay: 10000,
      max_restarts: 30,
      min_uptime: '30s',
      out_file: 'logs/pm2-claude-remote-out.log',
      error_file: 'logs/pm2-claude-remote-error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    },
  ],
};
