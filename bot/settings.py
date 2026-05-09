from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(_env_path)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv('DB_PATH', str(BASE_DIR.parent / 'server' / 'data' / 'actuarial.db')))
LOG_DIR = Path(os.getenv('LOG_DIR', str(BASE_DIR / 'logs')))
HEARTBEAT_PATH = Path(os.getenv('HEARTBEAT_PATH', str(BASE_DIR.parent / 'server' / 'data' / 'bot-heartbeat.json')))
PORTAL_URL = os.getenv('PORTAL_URL', 'http://127.0.0.1:8888').rstrip('/')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()

_allowed = os.getenv('ALLOWED_USER_IDS', '').strip()
ALLOWED_USER_IDS = {int(x.strip()) for x in _allowed.split(',') if x.strip().isdigit()}

DEFAULT_PERIOD = os.getenv('DEFAULT_PERIOD', '202603')
CURRENT_PERIODS = [x.strip() for x in os.getenv('CURRENT_PERIODS', DEFAULT_PERIOD).split(',') if x.strip()]
