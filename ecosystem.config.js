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
      // 봇 의존성(telegram/pandas/openpyxl/dotenv)이 설치된 venv 의 python 절대경로.
      // 시스템 PATH 의 python (3.14 등) 으로 떨어지면 deps 미설치로 실패하므로 명시.
      interpreter: 'C:\\Users\\USER\\infinite_buy_v22\\.venv\\Scripts\\python.exe',
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
