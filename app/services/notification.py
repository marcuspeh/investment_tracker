from decimal import Decimal

import structlog
from telegram.ext import Application

from app.database.models.trade import Trade
from app.database.repositories.user import UserRepository
from app.utils.timezone import utc_to_sgt

logger = structlog.get_logger()


def _format_qty(qty: Decimal | float) -> str:
    q = Decimal(str(qty))
    # Drop trailing zeros for cleaner output (e.g. 10.0 -> "10").
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _format_price(price: Decimal | float) -> str:
    return f"{Decimal(str(price)):,.4f}".rstrip("0").rstrip(".")


def format_trade_notification(trade: Trade) -> str:
    """Format a trade for Telegram notification."""
    time_sgt = utc_to_sgt(trade.trade_time)
    verb = "bought" if trade.side.value == "BUY" else "sold"
    notional = (
        trade.notional
        if trade.notional is not None
        else (Decimal(str(trade.quantity)) * Decimal(str(trade.price)))
    )
    return (
        f"�� New trade recorded\n"
        f"You {verb} {_format_qty(trade.quantity)} {trade.symbol} "
        f"@ {trade.currency} {_format_price(trade.price)}\n"
        f"Notional: {trade.currency} {notional:,.2f}\n"
        f"Account: {trade.account_id}\n"
        f"Time: {time_sgt.strftime('%d %b %Y %H:%M')}"
    )


class NotificationService:
    """Sends trade notifications to users via Telegram.

    Holds a reference to the bot's ``Application`` so it can push messages
    from background tasks (e.g. the email poller) without coupling the
    ingestion flow to the bot's lifecycle directly.
    """

    def __init__(self, application: Application, user_repo: UserRepository | None = None):
        self._application = application
        self._user_repo = user_repo or UserRepository()

    async def notify_trade(self, user_id: int, trade: Trade) -> bool:
        """Send a Telegram message to the owner of ``user_id`` announcing
        ``trade``. Returns True iff the message was sent successfully.
        """
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            logger.warning("notify_user_not_found", user_id=user_id)
            return False

        text = format_trade_notification(trade)
        try:
            await self._application.bot.send_message(
                chat_id=user.telegram_chat_id,
                text=text,
            )
        except Exception as e:
            logger.error(
                "notify_failed",
                user_id=user_id,
                chat_id=user.telegram_chat_id,
                error=str(e),
            )
            return False
        return
