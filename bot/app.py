from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import threading
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from db import init_db, log_query
from formatters import (
    format_balance_by_model,
    format_balance_single,
    format_csm_movement,
    format_csm_movement_compare,
    format_pl_by_model,
    format_pl_summary,
)
from parser import ParsedQuery, QueryParseError, parse_query
from query_engine import (
    QueryEngineError,
    get_balance_by_model,
    get_balance_single,
    get_csm_movement,
    get_csm_movement_compare,
    get_loaded_periods,
    get_pl_by_model,
    get_pl_summary,
)
from settings import ALLOWED_USER_IDS, HEARTBEAT_PATH, LOG_DIR, TELEGRAM_BOT_TOKEN


def _make_log_handler(log_dir: Path) -> TimedRotatingFileHandler:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        str(log_dir / 'bot.log'),
        when='midnight',
        backupCount=30,
        encoding='utf-8',
    )
    # Rename rotated files from bot.log.2026-05-08  →  bot_20260508.log
    def namer(default_name: str) -> str:
        m = re.search(r'\.(\d{4}-\d{2}-\d{2})$', default_name)
        if m:
            ds = m.group(1).replace('-', '')
            return str(log_dir / f'bot_{ds}.log')
        return default_name
    handler.namer = namer
    return handler


def setup_logging() -> None:
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s - %(message)s')
    file_handler = _make_log_handler(LOG_DIR)
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


logger = logging.getLogger(__name__)


# ── 전역 에러 핸들러 ──────────────────────────────────────────────────────────

def _global_excepthook(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logger.critical('uncaught exception', exc_info=(exc_type, exc_value, exc_tb))


def _threading_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    logger.critical(
        'uncaught thread exception in %s',
        getattr(args.thread, 'name', 'unknown'),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    exc = context.get('exception')
    msg = str(exc) if exc else context.get('message', 'unknown')
    logger.error('asyncio unhandled: %s', msg, exc_info=exc if exc else False)


# ── 헬스체크 하트비트 ──────────────────────────────────────────────────────────

async def heartbeat_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    payload = json.dumps({
        'last_alive': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'status': 'running',
        'pid': os.getpid(),
    }, ensure_ascii=False).encode('utf-8')
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = HEARTBEAT_PATH.with_suffix('.tmp')
        tmp.write_bytes(payload)
        tmp.replace(HEARTBEAT_PATH)
        logger.debug('heartbeat written')
    except Exception as exc:
        logger.warning('heartbeat write failed: %s', exc)


# ── 핵심 로직 ──────────────────────────────────────────────────────────────────

def _is_allowed(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    user = update.effective_user
    return bool(user and user.id in ALLOWED_USER_IDS)


async def _send_denied(update: Update) -> None:
    if update.message:
        await update.message.reply_text('[오류] 조회 권한이 없습니다.\n관리자에게 사용자 등록을 요청해주세요.')


def _extract_query_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if update.message and update.message.text:
        text = update.message.text.strip()
    else:
        text = ''
    if text.startswith('/query'):
        parts = text.split(' ', 1)
        return parts[1].strip() if len(parts) > 1 else ''
    if text.startswith('/조회'):
        parts = text.split(' ', 1)
        return parts[1].strip() if len(parts) > 1 else ''
    if context.args:
        return ' '.join(context.args).strip()
    return text


def _dispatch(parsed: ParsedQuery) -> str:
    if parsed.intent == 'balance_single':
        amount = get_balance_single(parsed.period, parsed.metric or '')
        return format_balance_single(parsed.period, parsed.metric or '', amount)
    if parsed.intent == 'balance_by_model':
        rows = get_balance_by_model(parsed.period, [parsed.metric or ''])
        return format_balance_by_model(parsed.period, rows, [parsed.metric or ''])
    if parsed.intent == 'balance_bundle_by_model':
        rows = get_balance_by_model(parsed.period, ['BEL', 'RA', 'CSM'])
        return format_balance_by_model(parsed.period, rows, ['BEL', 'RA', 'CSM'])
    if parsed.intent == 'pl_summary':
        data = get_pl_summary(parsed.period)
        return format_pl_summary(parsed.period, data)
    if parsed.intent == 'pl_by_model':
        if not parsed.scope:
            raise QueryEngineError(
                '[오류] 손익 조회 범위가 모호합니다.\n'
                '아래 중 하나로 입력해주세요.\n'
                '- /조회 202603 당월 보험손익\n'
                '- /조회 202603 누적 보험손익'
            )
        rows = get_pl_by_model(parsed.period, parsed.scope)
        return format_pl_by_model(parsed.period, parsed.scope, rows)
    if parsed.intent == 'csm_movement_model':
        rows = get_csm_movement(parsed.period, parsed.scope or '당월', parsed.model or '')
        return format_csm_movement(parsed.period, parsed.scope or '당월', parsed.model or '', rows)
    if parsed.intent == 'csm_movement_compare':
        rows = get_csm_movement_compare(parsed.period, parsed.scope or '당월')
        return format_csm_movement_compare(parsed.period, parsed.scope or '당월', rows)
    raise QueryEngineError('[오류] 아직 지원하지 않는 요청입니다.')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        await _send_denied(update)
        return
    periods = ', '.join(get_loaded_periods()) or '없음'
    text = (
        '안녕하세요. 결산 보고서 조회봇입니다.\n'
        f'현재 적재 기준: {periods}\n\n'
        '예시\n'
        '- /query 202603 누적 보험손익\n'
        '- /query 202603 월말 csm잔액\n'
        '- /query 202603 회계모형별 bel ra csm 잔액\n'
        '- /query 202603 np csm 무브먼트 당월\n'
        '- /query 202603 잔여보장부채\n'
        '- /query 202603 발생사고부채\n\n'
        '도움말: /help\n기간목록: /periods'
    )
    if update.message:
        await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        await _send_denied(update)
        return
    text = (
        '[도움말] 기본 문법\n'
        '/query [기준월] [범위] [지표] [선택조건]\n\n'
        '잔액 지표\n'
        '  BEL, RA, CSM, LOSS, 잔여보장부채, 발생사고부채\n\n'
        '예시\n'
        '- /query 202603 월말 csm잔액\n'
        '- /query 202603 누적 보험손익\n'
        '- /query 202603 np csm 무브먼트 누적\n'
        '- /query 202603 회계모형별 loss 잔액\n'
        '- /query 202603 잔여보장부채\n'
        '- /query 202603 발생사고부채\n\n'
        '자연어 예시\n'
        '- 26년3월말 csm잔액은?\n'
        '- np모형의 무브먼트코드별 csm 변동을 보여줘\n'
        '- 26년 3월말 잔여보장부채 얼마야?'
    )
    if update.message:
        await update.message.reply_text(text)


async def periods_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        await _send_denied(update)
        return
    periods = get_loaded_periods()
    text = '[적재 기간]\n' + '\n'.join(f'- {p}' for p in periods) if periods else '[적재 기간]\n- 없음'
    if update.message:
        await update.message.reply_text(text)


async def query_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        await _send_denied(update)
        return
    raw_query = _extract_query_text(update, context)
    if not raw_query:
        if update.message:
            await update.message.reply_text(
                '[오류] 조회어가 비어 있습니다.\n'
                '예시: /query 202603 누적 보험손익'
            )
        return
    user = update.effective_user
    chat = update.effective_chat
    parsed = None
    try:
        parsed = parse_query(raw_query)
        result = _dispatch(parsed)
        log_query(
            str(user.id) if user else None,
            user.username if user else None,
            str(chat.id) if chat else None,
            raw_query,
            parsed.intent,
            parsed.period,
            parsed.scope,
            parsed.metric,
            parsed.model,
            'success',
            None,
        )
        if update.message:
            await update.message.reply_text(result)
    except (QueryParseError, QueryEngineError) as exc:
        logger.warning('query error: %s', exc)
        log_query(
            str(user.id) if user else None,
            user.username if user else None,
            str(chat.id) if chat else None,
            raw_query,
            parsed.intent if parsed else None,
            parsed.period if parsed else None,
            parsed.scope if parsed else None,
            parsed.metric if parsed else None,
            parsed.model if parsed else None,
            'error',
            str(exc),
        )
        if update.message:
            await update.message.reply_text(str(exc))
    except Exception as exc:
        logger.exception('unexpected error')
        log_query(
            str(user.id) if user else None,
            user.username if user else None,
            str(chat.id) if chat else None,
            raw_query,
            None, None, None, None, None,
            'error',
            str(exc),
        )
        if update.message:
            await update.message.reply_text(
                '[오류] 조회 중 일시적인 문제가 발생했습니다.\n'
                '잠시 후 다시 시도해주세요.\n'
                '문제가 계속되면 관리자에게 문의해주세요.'
            )


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith('/start') or text.startswith('/help') or text.startswith('/periods') or text.startswith('/query'):
        return
    await query_command(update, context)


def build_application() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError('TELEGRAM_BOT_TOKEN 환경변수가 비어 있습니다.')
    init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('periods', periods_command))
    app.add_handler(CommandHandler('query', query_command))
    app.add_handler(MessageHandler(filters.TEXT, text_message))
    # 1시간마다 하트비트 파일 갱신 (즉시 첫 실행)
    if app.job_queue:
        app.job_queue.run_repeating(heartbeat_job, interval=3600, first=0)
    return app


def main() -> None:
    setup_logging()
    sys.excepthook = _global_excepthook
    threading.excepthook = _threading_excepthook

    application = build_application()

    loop = asyncio.new_event_loop()
    loop.set_exception_handler(_asyncio_exception_handler)
    asyncio.set_event_loop(loop)

    logger.info('bot is starting (pid=%d)', os.getpid())
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
