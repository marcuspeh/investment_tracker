import enum


class TradeSide(str, enum.Enum):
    """Direction of an IBKR fill."""

    BUY = "BUY"
    SELL = "SELL"


class ImportStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
