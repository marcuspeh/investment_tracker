from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.parsers.base import ParserError
from app.services.parsers.ibkr import IBKRParser

FIXTURES = Path(__file__).parent.parent / "fixtures" / "email_samples" / "ibkr"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _parse_email(text: str) -> dict:
    """Tiny RFC822-ish parser for fixture files."""
    subject = ""
    from_ = ""
    date = None
    body_lines: list[str] = []
    in_headers = True
    for line in text.splitlines():
        if in_headers:
            if line.startswith("Subject: "):
                subject = line[len("Subject: ") :]
            elif line.startswith("From: "):
                from_ = line[len("From: ") :]
            elif line.startswith("Date: "):
                # Very forgiving: store as ISO; if it parses, attach UTC tz.
                raw = line[len("Date: ") :].strip()
                try:
                    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    date = dt
                except ValueError:
                    date = None
            elif line.strip() == "":
                in_headers = False
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    return {
        "subject": subject,
        "from": from_,
        "body": body,
        "to": ["user@example.com"],
        "cc": [],
        "date": date,
    }


class TestIBKRParserCanParse:
    def setup_method(self):
        self.parser = IBKRParser()

    def test_can_parse_bought_subject_only(self):
        email = _parse_email(_load("IBKR fill - BOUGHT 100 MRNA.txt"))
        assert self.parser.can_parse(email) is True

    def test_can_parse_sold_subject_only(self):
        email = _parse_email(_load("IBKR fill - SOLD 10 SGOV.txt"))
        assert self.parser.can_parse(email) is True

    def test_can_parse_decimal_quantity(self):
        email = _parse_email(_load("IBKR fill - BOUGHT 25.5 VOO.txt"))
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_non_ibkr_sender(self):
        email = {
            "subject": "BOUGHT 100 MRNA @ 108.31 (UXXX6864)",
            "body": "",
            "from": "random@example.com",
            "to": ["user@example.com"],
            "cc": [],
        }
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_margin_notice_from_ibkr(self):
        # Margin notices come from a different local-part on the IBKR
        # domain (noreply@), not TradingAssistant@. The parser must
        # reject based on sender alone — the body has no fill line, but
        # we shouldn't even get there.
        email = _parse_email(_load("IBKR margin notice.txt"))
        assert email["from"] == "noreply@interactivebrokers.com"
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_when_sender_local_part_differs(self):
        # Subject contains a valid BOUGHT/SOLD summary line, but the
        # sender is a sibling local-part (noreply@) instead of
        # TradingAssistant@. Sender check must reject before the
        # summary regex runs.
        email = {
            "subject": "BOUGHT 100 MRNA @ 108.31 (UXXX6864)",
            "body": "BOUGHT 100 MRNA @ 108.31 (UXXX6864)\n",
            "from": "noreply@interactivebrokers.com",
            "to": ["user@example.com"],
            "cc": [],
        }
        assert self.parser.can_parse(email) is False

    def test_cannot_parse_from_sibling_domain(self):
        # ibkr.com is a sibling corporate domain but fill emails are
        # only sent from interactivebrokers.com.
        email = {
            "subject": "BOUGHT 100 MRNA @ 108.31 (UXXX6864)",
            "body": "",
            "from": "TradingAssistant@ibkr.com",
            "to": ["user@example.com"],
            "cc": [],
        }
        assert self.parser.can_parse(email) is False

    def test_can_parse_sender_is_case_sensitive(self):
        # The match is byte-for-byte exact. Any deviation in casing of
        # the local-part or domain is rejected — IBKR's MTAs always
        # render the address as-is, so a re-cased address means a
        # spoofed sender.
        email = {
            "subject": "BOUGHT 1 MRNA @ 100.00 (UXXX6864)",
            "body": "",
            "from": "TRADINGASSISTANT@INTERACTIVEBROKERS.COM",
            "to": ["user@example.com"],
            "cc": [],
        }
        assert self.parser.can_parse(email) is False

    def test_can_parse_exact_canonical_address(self):
        # Positive control: the exact address IBKR uses.
        email = {
            "subject": "BOUGHT 1 MRNA @ 100.00 (UXXX6864)",
            "body": "",
            "from": "TradingAssistant@interactivebrokers.com",
            "to": ["user@example.com"],
            "cc": [],
        }
        assert self.parser.can_parse(email) is True

    def test_cannot_parse_with_trailing_address_junk(self):
        # Defensive: a stray display-name appendage (rare, but possible
        # after forwarding) must not match the strict sender check.
        email = {
            "subject": "BOUGHT 1 MRNA @ 100.00 (UXXX6864)",
            "body": "",
            "from": "TradingAssistant@interactivebrokers.com via Gmail",
            "to": ["user@example.com"],
            "cc": [],
        }
        assert self.parser.can_parse(email) is False


class TestIBKRParserParse:
    def setup_method(self):
        self.parser = IBKRParser()

    def _parsed(self, name: str):
        return self.parser.parse(_parse_email(_load(name)))

    def test_parse_bought_mrna(self):
        result = self._parsed("IBKR fill - BOUGHT 100 MRNA.txt")
        assert result.side == "BUY"
        assert result.symbol == "MRNA"
        assert result.quantity == Decimal("100")
        assert result.price == Decimal("108.31")
        assert result.account_id == "UXXX6864"
        assert result.currency == "USD"
        assert result.trade_time.year == 2026
        assert result.trade_time.month == 8
        assert result.trade_time.day == 22

    def test_parse_sold_sgov(self):
        result = self._parsed("IBKR fill - SOLD 10 SGOV.txt")
        assert result.side == "SELL"
        assert result.symbol == "SGOV"
        assert result.quantity == Decimal("10")
        assert result.price == Decimal("100.5805")
        assert result.account_id == "UXXX6864"

    def test_parse_decimal_quantity(self):
        result = self._parsed("IBKR fill - BOUGHT 25.5 VOO.txt")
        assert result.quantity == Decimal("25.5")
        assert result.symbol == "VOO"

    def test_description_pulls_order_type_and_exchange(self):
        result = self._parsed("IBKR fill - BOUGHT 100 MRNA.txt")
        assert result.description is not None
        assert "order_type=Market" in result.description
        assert "exchange=NASDAQ" in result.description

    def test_parse_minimal_subject_only(self):
        # No body — parser should still extract from the subject line.
        email = {
            "subject": "BOUGHT 50 AAPL @ 195.40 (U1234567)",
            "body": "",
            "from": "TradingAssistant@interactivebrokers.com",
            "to": ["user@example.com"],
            "cc": [],
            "date": datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc),
        }
        result = self.parser.parse(email)
        assert result.side == "BUY"
        assert result.symbol == "AAPL"
        assert result.quantity == Decimal("50")
        assert result.price == Decimal("195.40")
        assert result.account_id == "U1234567"

    def test_parse_lowercase_buy_keyword(self):
        # Defensive: confirm the regex tolerates lowercase side too.
        email = {
            "subject": "bought 5 VTI @ 245.10 (UXXX6864)",
            "body": "",
            "from": "TradingAssistant@interactivebrokers.com",
            "to": ["user@example.com"],
            "cc": [],
            "date": datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc),
        }
        result = self.parser.parse(email)
        assert result.side == "BUY"
        assert result.symbol == "VTI"
        assert result.quantity == Decimal("5")

    def test_parse_uses_header_date_when_body_has_none(self):
        email = {
            "subject": "SOLD 7 BND @ 72.50 (UXXX6864)",
            "body": "SOLD 7 BND @ 72.50 (UXXX6864)\n\nTrade details omitted.\n",
            "from": "TradingAssistant@interactivebrokers.com",
            "to": ["user@example.com"],
            "cc": [],
            "date": datetime(2026, 8, 22, 13, 30, tzinfo=timezone.utc),
        }
        result = self.parser.parse(email)
        assert result.trade_time.year == 2026
        assert result.trade_time.month == 8
        assert result.trade_time.day == 22

    def test_parse_missing_summary_raises(self):
        email = {
            "subject": "IBKR Trade Notification",
            "body": "Some content without the right shape.",
            "from": "TradingAssistant@interactivebrokers.com",
            "to": ["user@example.com"],
            "cc": [],
        }
        with pytest.raises(ParserError):
            self.parser.parse(email)
