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
  ],
};

// ── 태블릿/모바일 원격 접속 (Claude Code Remote Control 상시 가동) ──
//  조직 정책상 "Trusted Device" 등록이 선행돼야 PM2 spawn 이 통과한다
//  (등록 안 된 디바이스는 "device is not enrolled" 오류로 거부됨).
//  활성화 순서:
//   1) 새 터미널에서 `claude` 실행 → 인터랙티브 세션 안에서 `/login` 입력
//   2) 브라우저로 device 등록 절차 완료 (1회만)
//   3) autostart\claude-remote-install.bat 실행 → PM2 앱으로 영구 등록
//  이후 부팅 시 항상 가동되어 태블릿 Claude 앱에서 즉시 접속 가능.
