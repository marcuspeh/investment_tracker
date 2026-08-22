"""Service layer for trade queries exposed through the Telegram bot."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.database.enums import TradeSide
from app.database.models.trade import Trade
from app.database.repositories.trade import TradeRepository
from app.utils.timezone import (
    get_month_window,
    get_range_window,
    get_today_window,
    get_week_window,
    parse_date,
    sgt_to_utc,
)


class TradeService:
    """Read-side service for the trades table.

    Wraps :class:`TradeRepository` with the SGT↔UTC boundary conversions
    so the rest of the app never has to think about timezones.
    """

    def __init__(self):
        self.trade_repo = TradeRepository()

    async def get_latest_trades(self, user_id: int, count: int = 10) -> list[Trade]:
        return await self.trade_repo.list_latest_for_user(user_id, count)

    async def get_today_buy_total(self, user_id: int) -> Decimal:
        start, end = get_today_window()
        return await self.trade_repo.sum_notional_by_side(
            user_id, sgt_to_utc(start), sgt_to_utc(end), TradeSide.BUY
        )

    async def get_today_sell_total(self, user_id: int) -> Decimal:
        start, end = get_today_window()
        return await self.trade_repo.sum_notional_by_side(
            user_id, sgt_to_utc(start), sgt_to_utc(end), TradeSide.SELL
        )

    async def get_today_count(self, user_id: int) -> dict[str, int]:
        start, end = get_today_window()
        return {
            "BUY": await self.trade_repo.count_by_side(
                user_id, sgt_to_utc(start), sgt_to_utc(end), TradeSide.BUY
            ),
            "SELL": await self.trade_repo.count_by_side(
                user_id, sgt_to_utc(start), sgt_to_utc(end), TradeSide.SELL
            ),
        }

    async def get_week_count(self, user_id: int) -> dict[str, int]:
        start, end = get_week_window()
        return {
            "BUY": await self.trade_repo.count_by_side(
                user_id, sgt_to_utc(start), sgt_to_utc(end), TradeSide.BUY
            ),
            "SELL": await self.trade_repo.count_by_side(
                user_id, sgt_to_utc(start), sgt_to_utc(end), TradeSide.SELL
            ),
        }

    async def get_month_count(self, user_id: int) -> dict[str, int]:
        start, end = get_month_window()
        return {
            "BUY": await self.trade_repo.count_by_side(
                user_id, sgt_to_utc(start), sgt_to_utc(end), TradeSide.BUY
            ),
            "SELL": await self.trade_repo.count_by_side(
                user_id, sgt_to_utc(start), sgt_to_utc(end), TradeSide.SELL
            ),
        }

    async def get_range_trades(
        self,
        user_id: int,
        start_date: datetime | str,
        end_date: datetime | str,
    ) -> tuple[list[Trade], int, bool]:
        """Get trades in a date range.

        Returns ``(rows, total_count, is_truncated)``.
        """
        if isinstance(start_date, str):
            start_date = parse_date(start_date)
        if isinstance(end_date, str):
            end_date = parse_date(end_date)

        start_sgt, end_sgt = get_range_window(start_date, end_date)
        rows, total_count = await self.trade_repo.list_in_range_for_user(
            user_id, sgt_to_utc(start_sgt), sgt_to_utc(end_sgt)
        )
        return rows, total_count, total_count > 200

    async def search_by_symbol(self, user_id: int, symbol_substring: str) -> list[Trade]:
        return await self.trade_repo.search_by_symbol(user_id, symbol_substring)

    async def delete_trade(self, trade_id: int, user_id: int) -> bool:
        trade = await self.trade_repo.get_by_id_for_user(trade_id, user_id)
        if not trade:
            return False
        await self.trade_repo.soft_delete(trade)
        return True

    def format_notional(self, value: Decimal, currency: str = "USD") -> str:
        return f"{currency} {value:,.2f}"

    async def get_range_summary(
        self,
        user_id: int,
        start_date: Any,
        end_date: Any,
    ) -> dict[str, Any]:
        """Aggregate counts + notional totals for a date range."""
        if isinstance(start_date, str):
            start_date = parse_date(start_date)
        if isinstance(end_date, str):
            end_date = parse_date(end_date)
        start_sgt, end_sgt = get_range_window(start_date, end_date)
        start_utc = sgt_to_utc(start_sgt)
        end_utc = sgt_to_utc(end_sgt)
        return {
            "buy_count": await self.trade_repo.count_by_side(
                user_id, start_utc, end_utc, TradeSide.BUY
            ),
            "sell_count": await self.trade_repo.count_by_side(
                user_id, start_utc, end_utc, TradeSide.SELL
            ),
            "buy_notional": await self.trade_repo.sum_notional_by_side(
                user_id, start_utc, end_utc, TradeSide.BUY
            ),
            "sell_notional": await self.trade_repo.sum_notional_by_side(
                user_id, start_utc, end_utc, TradeSide.SELL
            ),
        }
