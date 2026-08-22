from datetime import datetime, timezone
from decimal import Decimal

from tortoise.queryset import QuerySet

from app.database.enums import TradeSide
from app.database.models.trade import Trade


class TradeRepository:
    async def insert(
        self,
        user_id: int,
        side: TradeSide,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        currency: str,
        account_id: str,
        trade_time: datetime,
        notional: Decimal | None = None,
        description: str | None = None,
    ) -> Trade:
        if notional is None:
            notional = (quantity * price).quantize(Decimal("0.01"))
        return await Trade.create(
            user_id=user_id,
            side=side,
            symbol=symbol.upper(),
            quantity=quantity,
            price=price,
            currency=currency.upper(),
            account_id=account_id,
            trade_time=trade_time,
            notional=notional,
            description=description,
        )

    def _base_filter(self, user_id: int) -> QuerySet:
        return Trade.filter(user_id=user_id, deleted_at__isnull=True)

    async def list_latest_for_user(self, user_id: int, count: int = 10) -> list[Trade]:
        return await self._base_filter(user_id).order_by("-trade_time", "-id").limit(count)

    async def list_in_range_for_user(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        limit: int = 201,
    ) -> tuple[list[Trade], int]:
        window = self._base_filter(user_id).filter(
            trade_time__gte=start_date,
            trade_time__lte=end_date,
        )
        total_count = await window.count()
        rows = await window.order_by("-trade_time").limit(limit + 1)
        return rows[:limit], total_count

    async def search_by_symbol(
        self,
        user_id: int,
        symbol_substring: str,
    ) -> list[Trade]:
        return (
            await self._base_filter(user_id)
            .filter(symbol__icontains=symbol_substring)
            .order_by("-trade_time")
            .limit(200)
        )

    async def sum_notional_by_side(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
        side: TradeSide,
    ) -> Decimal:
        """Sum ``notional`` for trades in [start, end] (UTC) matching ``side``.

        Returns ``Decimal('0')`` when no rows match. Caller passes SGT windows
        converted to UTC via ``app.utils.timezone.sgt_to_utc()``.
        """
        results = (
            await self._base_filter(user_id)
            .filter(
                trade_time__gte=start,
                trade_time__lte=end,
                side=side,
            )
            .values_list("notional", flat=True)
        )
        total = Decimal("0")
        for value in results:
            if value is None:
                continue
            total += Decimal(value)
        return total

    async def count_by_side(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
        side: TradeSide,
    ) -> int:
        return (
            await self._base_filter(user_id)
            .filter(
                trade_time__gte=start,
                trade_time__lte=end,
                side=side,
            )
            .count()
        )

    async def get_by_id_for_user(self, trade_id: int, user_id: int) -> Trade | None:
        return await Trade.filter(id=trade_id, user_id=user_id, deleted_at__isnull=True).first()

    async def soft_delete(self, trade: Trade) -> None:
        trade.deleted_at = datetime.now(timezone.utc)
        await trade.save()
