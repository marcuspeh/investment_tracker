from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass
class ParsedTrade:
    """A single IBKR fill parsed from a notification email.

    ``quantity`` and ``price`` are positive Decimal values. Direction is
    carried by ``side``; ``notional`` is the absolute trade value
    (quantity * price).
    """

    side: str  # TradeSide enum value
    symbol: str
    quantity: Decimal
    price: Decimal
    currency: str
    account_id: str
    trade_time: datetime
    description: str | None = None


class ParserError(Exception):
    """Exception raised when parsing fails."""

    pass


class BaseParser(ABC):
    """Abstract base class for email parsers."""

    @abstractmethod
    def can_parse(self, email: dict[str, Any]) -> bool:
        """Return True iff this parser claims the email."""
        pass

    @abstractmethod
    def parse(self, email: dict[str, Any]) -> ParsedTrade:
        """Parse the email and return a `ParsedTrade`."""
        pass
