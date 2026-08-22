import structlog
from telegram import Update
from telegram.ext import ContextTypes

from app.database.models.user import User
from app.database.repositories.user import UserRepository
from app.services.trade import TradeService
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import (
    fmt_notional,
    format_trades,
    remember_recent,
)
from app.utils.timezone import parse_date

logger = structlog.get_logger()


def _parse_count(args: list[str] | None, default: int = 10, max_count: int = 50) -> int:
    if not args:
        return default
    try:
        return min(int(args[0]), max_count)
    except ValueError:
        return default


async def _resolve_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> User | None:
    if not await auth_handler(update, context):
        return None
    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(update.effective_chat.id)
    if not user:
        await update.message.reply_text("User not found.")
        return None
    return user


async def latest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _resolve_user(update, context)
    if not user:
        return

    count = _parse_count(context.args, default=10, max_count=50)
    service = TradeService()
    trades = await service.get_latest_trades(user.id, count)

    chat_id = update.effective_chat.id
    remember_recent(chat_id, [t.id for t in trades])

    title = "Latest trades"
    text = format_trades(trades, title)
    await update.message.reply_text(text)


async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _resolve_user(update, context)
    if not user:
        return
    service = TradeService()
    counts = await service.get_today_count(user.id)
    buy_total = await service.get_today_buy_total(user.id)
    sell_total = await service.get_today_sell_total(user.id)
    text = (
        "Today's trades (SGT)\n\n"
        f"Buys:  {counts['BUY']} ({fmt_notional(buy_total, 'USD')})\n"
        f"Sells: {counts['SELL']} ({fmt_notional(sell_total, 'USD')})"
    )
    await update.message.reply_text(text)


async def week_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _resolve_user(update, context)
    if not user:
        return
    service = TradeService()
    counts = await service.get_week_count(user.id)
    text = f"This week's trades (SGT)\n\nBuys:  {counts['BUY']}\nSells: {counts['SELL']}"
    await update.message.reply_text(text)


async def month_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _resolve_user(update, context)
    if not user:
        return
    service = TradeService()
    counts = await service.get_month_count(user.id)
    text = f"This month's trades (SGT)\n\nBuys:  {counts['BUY']}\nSells: {counts['SELL']}"
    await update.message.reply_text(text)


async def range_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /range <start> <end>\nExample: /range 2026-08-01 2026-08-22"
        )
        return
    start_str, end_str = args[0], args[1]
    try:
        start_date = parse_date(start_str)
        end_date = parse_date(end_str)
    except ValueError:
        await update.message.reply_text("Invalid date format. Use YYYY-MM-DD.")
        return

    user = await _resolve_user(update, context)
    if not user:
        return

    service = TradeService()
    trades, total_count, is_truncated = await service.get_range_trades(
        user.id, start_date, end_date
    )

    chat_id = update.effective_chat.id
    remember_recent(chat_id, [t.id for t in trades])

    title = f"Trades from {start_str} to {end_str}"
    body = format_trades(trades, title)
    body += f"\n\nTotal: {total_count}"
    if is_truncated:
        body += " (showing first 200, results truncated)"
    await update.message.reply_text(body)


async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /search <symbol>")
        return
    user = await _resolve_user(update, context)
    if not user:
        return
    symbol = " ".join(args).upper()
    service = TradeService()
    trades = await service.search_by_symbol(user.id, symbol)

    chat_id = update.effective_chat.id
    remember_recent(chat_id, [t.id for t in trades])

    title = f'Search results for "{symbol}"'
    text = format_trades(trades, title)
    await update.message.reply_text(text)
