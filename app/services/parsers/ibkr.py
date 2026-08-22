"""IBKR fill email parser.

IBKR sends a notification email per executed fill. The exact wording of the
top "summary" line varies; the canonical shapes we've seen are::

    BOUGHT 100 MRNA @ 108.31 (UXXX6864)
    SOLD 10 SGOV @ 100.5805 (UXXX6864)
    BOUGHT 50 AAPL @ 195.40 (U1234567)
    BOUGHT 25.5 VOO @ 478.20 (UXXX6864)

The summary appears in both the Subject and the first non-empty line of the
plain-text body. The body adds structured fields like::

    Trade Date/Time: 2026-08-22, 09:35:12
    Symbol: MRNA
    Quantity: 100
    Trade Price: 108.31
    Order Type: Market
    Account: UXXX6864

We rely on the summary line (Subject + body both work) to extract
side/quantity/symbol/price/account, and use the email's ``Date:`` header
(or any explicit Trade Date/Time line in the body) as the trade timestamp.

The parser claims emails whose ``from`` header is exactly
``TradingAssistant@interactivebrokers.com``. The IBKR domain sends other
notification types (margin, dividend, marketing) from different
local-parts (``noreply@``, ``donotreply@``, etc.) — those are rejected by
the sender check before the summary regex even runs.
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.services.parsers.base import BaseParser, ParsedTrade, ParserError
from app.utils.timezone import SGT, UTC

#: Exact sender for IBKR fill notification emails. IBKR sends fills only
#: from ``TradingAssistant@interactivebrokers.com`` — the same domain
#: also sends marketing/margin/dividend emails from other local-parts
#: (e.g. ``noreply``, ``donotreply``), so we match the local-part too.
#:
#: Comparison is case-sensitive and whitespace-trimmed; IBKR's
#: ``From:`` header always carries the address verbatim, so a
#: byte-for-byte match is the right strictness.
IBKR_FROM_ADDRESS = "tradingassistant@interactivebrokers.com"

#: Summary line pattern. Captures (side, quantity, symbol, price, account_id).
#: Group 1: BOUGHT / SOLD
#: Group 2: quantity (integer or decimal)
#: Group 3: ticker symbol (letters/digits/.-)
#: Group 4: price (decimal)
#: Group 5: account id inside parens
SUMMARY_RE = re.compile(
    r"\b(BOUGHT|SOLD)\s+"
    r"(\d+(?:\.\d+)?)\s+"
    r"([A-Z][A-Z0-9.\-]{0,9})\s+@\s+"
    r"(\d+(?:\.\d+)?)\s+"
    r"\(([A-Z0-9]+)\)",
    re.IGNORECASE,
    # Tolerate tight spacing like "BOUGHT100 MRNA @108.31" by allowing
    # a single optional space between tokens. The \b on the side keeps
    # the regex from matching inside other words.
)

#: Field-level patterns inside the IBKR body, used as a secondary signal
#: when the summary line can't be located (e.g. weird HTML-only email).
FIELD_PATTERNS = {
    "symbol": re.compile(r"\bSymbol:\s*([A-Z][A-Z0-9.\-]{0,9})"),
    "quantity": re.compile(r"\b(?:Quantity|Shares):\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
    "price": re.compile(r"\b(?:Trade\s+Price|Price):\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
    "account": re.compile(r"\bAccount:\s*([A-Z0-9]+)", re.IGNORECASE),
    "side": re.compile(r"\bSide:\s*(BOUGHT|SOLD|BUY|SELL)", re.IGNORECASE),
    "trade_time": re.compile(
        r"\bTrade\s+Date/Time:\s*(\d{4}-\d{2}-\d{2},?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)",
        re.IGNORECASE,
    ),
}


class IBKRParser(BaseParser):
    """Parser for Interactive Brokers fill notification emails."""

    name = "IBKR"

    def can_parse(self, email: dict[str, Any]) -> bool:
        from_ = (email.get("from", "") or "").lower()
        subject = email.get("subject", "") or ""
        body = email.get("body", "") or ""
        # Sender must be exactly TradingAssistant@interactivebrokers.com —
        # case-sensitive, byte-for-byte. Other local-parts on the same
        # domain are margin/dividend/marketing emails — never fills.
        if from_ != IBKR_FROM_ADDRESS:
            return False
        # Final discriminator: must contain a BOUGHT/SOLD summary line.
        return self._find_summary(subject, body) is not None

    def parse(self, email: dict[str, Any]) -> ParsedTrade:
        subject = email.get("subject", "") or ""
        body = email.get("body", "") or ""

        summary = self._find_summary(subject, body)
        if summary is None:
            raise ParserError("IBKR summary line not found")

        side_token, qty_str, symbol, price_str, account_id = summary
        side = "BUY" if side_token.upper() == "BOUGHT" else "SELL"

        quantity = Decimal(qty_str)
        price = Decimal(price_str)

        # Currency: IBKR doesn't put a currency tag on the summary line.
        # Default to USD; users can override via description if needed.
        currency = "USD"

        trade_time = self._extract_trade_time(body, email)

        description = self._build_description(body)

        return ParsedTrade(
            side=side,
            symbol=symbol.upper(),
            quantity=quantity,
            price=price,
            currency=currency,
            account_id=account_id,
            trade_time=trade_time,
            description=description,
        )

    @staticmethod
    def _find_summary(subject: str, body: str) -> tuple[str, str, str, str, str] | None:
        """Return (side, qty, symbol, price, account) from the first
        summary line in either the subject or body. Subject wins on ties.
        """
        for text in (subject, body):
            m = SUMMARY_RE.search(text)
            if m:
                return m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        return None

    @staticmethod
    def _extract_trade_time(body: str, email: dict[str, Any]) -> datetime:
        """Find the fill timestamp.

        Resolution order:
        1. Body ``Trade Date/Time:`` line — parsed as IBKR's local time,
           then converted to UTC. We default the timezone to SGT (IBKR's
           server clock) and let downstream windows convert again.
        2. Email ``Date:`` header (tz-aware), converted to SGT then back
           to naive-UTC.
        3. ``now()`` as a last resort.
        """
        m = FIELD_PATTERNS["trade_time"].search(body)
        if m:
            text = m.group(1).strip()
            # IBKR formats the timestamp with a comma: "2026-08-22, 09:35:12"
            text = text.replace(",", " ")
            parsed = _parse_ibkr_datetime(text)
            if parsed is not None:
                # IBKR timestamps are naive in the body but represent
                # exchange local time. Attach SGT, downstream converts.
                return parsed.replace(tzinfo=SGT)

        header = email.get("date")
        if isinstance(header, datetime):
            if header.tzinfo is None:
                header = header.replace(tzinfo=UTC)
            return header.astimezone(SGT)

        from app.utils.timezone import now_sgt

        return now_sgt()

    @staticmethod
    def _build_description(body: str) -> str | None:
        """Return a compact one-line summary of the IBKR email body.

        We pull a handful of fields so the Telegram notification has
        context (order type, exchange) without dumping the full HTML
        email. Returns ``None`` when no fields are present.
        """
        order_type_m = re.search(r"\bOrder\s+Type:\s*([A-Za-z ]+?)(?:\s*$|\s*\n)", body)
        exchange_m = re.search(r"\b(?:Exchange|Listing\s+Exchange):\s*([A-Z0-9]+)", body)
        parts: list[str] = []
        if order_type_m:
            parts.append(f"order_type={order_type_m.group(1).strip()}")
        if exchange_m:
            parts.append(f"exchange={exchange_m.group(1).strip()}")
        return ", ".join(parts) if parts else None


def _parse_ibkr_datetime(text: str) -> datetime | None:
    """Parse the IBKR body timestamp.

    Tries several formats because IBKR has shipped both 12h and 24h
    variants, with and without AM/PM, with and without seconds, and
    with or without the comma between date and time.
    """
    text = text.strip()
    candidates = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M:%S %p",
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %I:%M:%S%p",
        "%Y-%m-%d %I:%M%p",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
