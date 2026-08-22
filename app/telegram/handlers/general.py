from telegram import Update
from telegram.ext import ContextTypes

from app.telegram.auth import auth_handler


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_handler(update, context):
        return

    await update.message.reply_text(
        "Welcome to Investment Tracker Bot!\n\n"
        "IBKR fill emails forwarded to this bot's inbox are auto-imported.\n"
        "Use /help to see available commands."
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_handler(update, context):
        return

    help_text = """
Available commands:

Viewing trades:
/latest [count] - Show latest trades (default: 10, max: 50)
/today - Show today's trade counts + notional
/week - Show this week's trade counts
/month - Show this month's trade counts
/range <start> <end> - Show trades in date range (YYYY-MM-DD)
/search <symbol> - Search trades by symbol substring

Managing trades:
/delete <id> - Start delete confirmation
/confirm [id] - Confirm a pending delete
/cancel [id] - Cancel pending delete(s)

Every IBKR fill is auto-imported from forwarded emails and a Telegram alert is sent on insert.

Other:
/ping - Check bot is alive
"""
    await update.message.reply_text(help_text)


async def ping_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await auth_handler(update, context):
        return
    await update.message.reply_text("pong")
