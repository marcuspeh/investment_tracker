from tortoise import fields
from tortoise.models import Model

from app.database.enums import TradeSide


class Trade(Model):
    """A single IBKR fill (BOUGHT/SOLD) parsed from a notification email.

    ``quantity`` is always positive. ``side`` (``BUY`` / ``SELL``) carries
    the direction; ``signed_quantity`` (computed at access time) is positive
    for buys and negative for sells so /today, /week, /range aggregates can
    treat quantity the same way the expense tracker treats amount.

    ``notional`` (quantity * price) is denormalized so queries can sum
    traded value without a join. Stored as a positive value; ``side``
    gives direction when the caller cares about flow direction.
    """

    id = fields.IntField(pk=True, auto_now_add=True)
    user_id = fields.IntField()
    side = fields.CharEnumField(TradeSide)
    symbol = fields.CharField(max_length=32)
    quantity = fields.DecimalField(max_digits=18, decimal_places=6)
    price = fields.DecimalField(max_digits=18, decimal_places=6)
    currency = fields.CharField(max_length=8, default="USD")
    account_id = fields.CharField(max_length=64)
    notional = fields.DecimalField(max_digits=18, decimal_places=2, null=True)
    description = fields.TextField(null=True)
    trade_time = fields.DatetimeField()
    created_at = fields.DatetimeField(db_default=fields.Now())
    updated_at = fields.DatetimeField(db_default=fields.Now())
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "trades"
        ordering = ["-trade_time"]

    def __str__(self):
        return f"Trade(id={self.id}, {self.side} {self.symbol} qty={self.quantity} @ {self.price})"
