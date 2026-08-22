from decimal import Decimal
from typing import Any

from app.utils.timezone import utc_to_sgt

# In-memory state for two-step delete confirmation, keyed by chat_id.
_pending_deletes: dict[int, set[int]] = {}

# Last list shown to each chat_id: maps the 1-based index in /latest output
# to the real trade id. Used so /delete <index> works directly off the
# numbering the user just saw.
_recent_index: dict[int, dict[int, int]] = {}


def remember_recent(chat_id: int, trade_ids: list[int]) -> None:
    """Cache the ordering shown in the most recent list command."""
    _recent_index[chat_id] = {i + 1: trade_id for i, trade_id in enumerate(trade_ids)}


def resolve_recent(chat_id: int, key: int | str) -> int | None:
    """Resolve a user's ``key`` (1-based index from /latest) to the real
    trade id stored in the most-recent-list cache.
    """
    cached = _recent_index.get(chat_id, {})
    try:
        key_int = int(key)
    except (TypeError, ValueError):
        return None
    return cached.get(key_int)


def clear_recent(chat_id: int) -> None:
    _recent_index.pop(chat_id, None)


def add_pending_delete(chat_id: int, trade_id: int) -> None:
    bucket = _pending_deletes.setdefault(chat_id, set())
    bucket.add(trade_id)


def pop_pending_deletes(chat_id: int, ids: list[int] | None = None) -> set[int]:
    bucket = _pending_deletes.get(chat_id, set())
    if ids is None:
        removed = set(bucket)
        bucket.clear()
    else:
        target = set(int(i) for i in ids)
        removed = target & bucket
        bucket -= target
    if not bucket:
        _pending_deletes.pop(chat_id, None)
    return removed


def cancel_pending(chat_id: int, ids: list[int] | None = None) -> set[int]:
    return pop_pending_deletes(chat_id, ids)


def list_pending(chat_id: int) -> set[int]:
    return set(_pending_deletes.get(chat_id, set()))


def fmt_qty(qty: Decimal | float) -> str:
    """Format quantity for display — trim trailing zeros."""
    s = format(Decimal(str(qty)), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def fmt_price(price: Decimal | float) -> str:
    return f"{Decimal(str(price)):,.4f}".rstrip("0").rstrip(".")


def fmt_notional(notional: Decimal | float | None, currency: str) -> str:
    if notional is None:
        return "-"
    return f"{currency} {Decimal(str(notional)):,.2f}"


def format_trade(trade: Any, index: int) -> str:
    """Format a trade for plain-text display."""
    time_sgt = utc_to_sgt(trade.trade_time)
    side = trade.side.value if hasattr(trade.side, "value") else str(trade.side)
    arrow = "▲" if side == "BUY" else "▼"
    return (
        f"{index}. {arrow} {side} {fmt_qty(trade.quantity)} {trade.symbol} "
        f"@ {trade.currency} {fmt_price(trade.price)}\n"
        f"   {time_sgt.strftime('%d %b %Y %H:%M')} | {trade.account_id} | "
        f"{fmt_notional(trade.notional, trade.currency)}"
    )


def format_trades(trades: list, title: str = "Trades") -> str:
    if not trades:
        return f"{title}\n\nNo trades found."
    lines = [title, ""]
    for i, t in enumerate(trades, 1):
        lines.append(format_trade(t, i))
    return "\n".join(lines)
