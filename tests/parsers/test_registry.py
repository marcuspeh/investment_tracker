from datetime import datetime, timezone
from decimal import Decimal

from app.services.parsers.ibkr import IBKRParser
from app.services.parsers.registry import ParserRegistry


def make_email(
    subject: str, body: str, from_: str = "TradingAssistant@interactivebrokers.com"
) -> dict:
    return {
        "subject": subject,
        "body": body,
        "from": from_,
        "to": ["user@example.com"],
        "cc": [],
        "date": datetime(2026, 8, 22, tzinfo=timezone.utc),
    }


def test_registry_returns_first_matching_parser():
    registry = ParserRegistry()
    registry.register(IBKRParser())
    parser = registry.find_parser(make_email("BOUGHT 1 X @ 1.00 (U123)", ""))
    assert parser is not None
    assert parser.name == "IBKR"


def test_registry_returns_none_when_no_parser_matches():
    registry = ParserRegistry()
    registry.register(IBKRParser())
    parser = registry.find_parser(make_email("Hi there", "Nothing", "other@example.com"))
    assert parser is None


def test_registry_parse_returns_none_when_no_parser_matches():
    registry = ParserRegistry()
    registry.register(IBKRParser())
    result = registry.parse(make_email("Hi there", "Nothing", "other@example.com"))
    assert result is None


def test_registry_parse_returns_trade_on_match():
    registry = ParserRegistry()
    registry.register(IBKRParser())
    result = registry.parse(make_email("BOUGHT 5 VOO @ 478.20 (UXXX6864)", ""))
    assert result is not None
    assert result.symbol == "VOO"
    assert result.quantity == Decimal("5")
    assert result.price == Decimal("478.20")
