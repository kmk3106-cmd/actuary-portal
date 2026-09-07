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
    // ── claude-remote (태블릿/모바일 원격) — 비활성화 상태 ──
    //  Trusted Device 등록이 주기적으로 풀리는 문제로, 부팅 시마다 무한 재시작 →
    //  PM2 데몬 안정성 해침 → portal/bot 까지 영향. 일단 PM2 자동기동에서 제외.
    //  활성화하려면: (1) 새 인터랙티브 `claude` → /login 으로 Trusted Device 등록
    //                (2) autostart\claude-remote-install.bat 실행 (수동 PM2 등록)
    //  enrollment 가 다시 풀리면 같은 증상 재발하므로 일회성 사용 권장.
  ],
};
