"""Unit tests for EmailIngestionService.process_email.

Mocks the three repositories so we can exercise the dedup / parser /
ownership / insert paths without a real database.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.database.enums import ImportStatus
from app.services.email_ingestion import EmailIngestionService
from app.services.parsers.base import ParsedTrade, ParserError
from app.services.parsers.registry import ParserRegistry


@dataclass
class FakeUserEmail:
    user_id: int = 42


def _make_service(
    *,
    existing_import=None,
    user_email=None,
    parsed=None,
    parser_error: bool = False,
    notification_service=None,
) -> tuple[EmailIngestionService, dict[str, AsyncMock]]:
    registry = ParserRegistry()
    parser = MagicMock()
    parser.parse = MagicMock(side_effect=ParserError("bad") if parser_error else None)
    if parsed is not None:
        parser.parse = MagicMock(return_value=parsed)
    registry.register(parser)
    registry.find_parser = MagicMock(return_value=parser)

    imported_mock = MagicMock()
    imported_mock.exists_by_message_id = AsyncMock(return_value=existing_import is not None)
    imported_mock.get_by_message_id = AsyncMock(return_value=existing_import)
    imported_mock.insert = AsyncMock(return_value=MagicMock())

    user_email_mock = MagicMock()
    user_email_mock.find_by_email = AsyncMock(return_value=user_email)

    fake_trade = MagicMock()
    fake_trade.id = 1
    trade_mock = MagicMock()
    trade_mock.insert = AsyncMock(return_value=fake_trade)

    service = EmailIngestionService.__new__(EmailIngestionService)
    service.parser_registry = registry
    service.imported_email_repo = imported_mock
    service.user_email_repo = user_email_mock
    service.trade_repo = trade_mock
    service.notification_service = notification_service
    return service, {
        "imported": imported_mock,
        "user_email": user_email_mock,
        "trade": trade_mock,
        "parser": parser,
    }


def _parsed(side: str = "BUY") -> ParsedTrade:
    return ParsedTrade(
        side=side,
        symbol="MRNA",
        quantity=Decimal("100"),
        price=Decimal("108.31"),
        currency="USD",
        account_id="UXXX6864",
        trade_time=datetime(2026, 8, 22, 9, 35),
        description=None,
    )


def _email(**overrides: Any) -> dict:
    base = {
        "message_id": "<abc@example.com>",
        "subject": "BOUGHT 100 MRNA @ 108.31 (UXXX6864)",
        "body": "BOUGHT 100 MRNA @ 108.31 (UXXX6864)\n",
        "from": "TradingAssistant@interactivebrokers.com",
        "to": ["user@example.com"],
        "cc": [],
    }
    if "from_" in overrides:
        overrides["from"] = overrides.pop("from_")
    base.update(overrides)
    return base


class TestProcessEmailSuccess:
    @pytest.mark.asyncio
    async def test_inserts_trade_when_user_and_parser_match(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(user_id=42),
            parsed=_parsed(),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS
        mocks["trade"].insert.assert_awaited_once()
        mocks["imported"].insert.assert_awaited_with("<abc@example.com>", ImportStatus.SUCCESS)

    @pytest.mark.asyncio
    async def test_user_email_string_form(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(),
        )
        status = await service.process_email(_email(to="user@example.com"))
        assert status == ImportStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_user_email_list_form(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(),
        )
        status = await service.process_email(_email(to=["a@example.com", "user@example.com"]))
        assert status == ImportStatus.SUCCESS


class TestProcessEmailFailure:
    @pytest.mark.asyncio
    async def test_parser_error_marks_failed(self):
        service, mocks = _make_service(parser_error=True)
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        mocks["imported"].insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.FAILED, "PARSE_ERROR"
        )
        mocks["trade"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_user_email_marks_failed_with_unknown_forwarder(self):
        service, mocks = _make_service(
            user_email=None,
            parsed=_parsed(),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        mocks["imported"].insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.FAILED, "UNKNOWN_FORWARDER"
        )
        mocks["trade"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_side_marks_failed(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(side="NOT_A_SIDE"),
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        mocks["imported"].insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.FAILED, "UNKNOWN_SIDE"
        )
        mocks["trade"].insert.assert_not_awaited()


class TestProcessEmailDedup:
    @pytest.mark.asyncio
    async def test_returns_existing_status_when_already_imported(self):
        existing = MagicMock()
        existing.status = ImportStatus.SUCCESS
        existing.reason = None
        service, mocks = _make_service(existing_import=existing)
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS
        mocks["trade"].insert.assert_not_awaited()
        mocks["imported"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_forwarder_on_repeat_returns_failed(self):
        existing = MagicMock()
        existing.status = ImportStatus.FAILED
        existing.reason = "UNKNOWN_FORWARDER"
        service, mocks = _make_service(existing_import=existing)
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        mocks["trade"].insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_integrity_error_on_insert_treated_as_already_seen(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(),
        )
        mocks["imported"].insert = AsyncMock(return_value=None)
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS


class TestProcessEmailNoParser:
    @pytest.mark.asyncio
    async def test_no_parser_marks_skipped(self):
        registry = ParserRegistry()
        registry.find_parser = MagicMock(return_value=None)
        service = EmailIngestionService.__new__(EmailIngestionService)
        service.parser_registry = registry
        service.imported_email_repo = MagicMock()
        service.imported_email_repo.exists_by_message_id = AsyncMock(return_value=False)
        service.imported_email_repo.insert = AsyncMock(return_value=MagicMock())
        service.user_email_repo = MagicMock()
        service.trade_repo = MagicMock()

        status = await service.process_email(_email())
        assert status == ImportStatus.SKIPPED
        service.imported_email_repo.insert.assert_awaited_with(
            "<abc@example.com>", ImportStatus.SKIPPED
        )


class TestNotificationOnSuccess:
    @pytest.mark.asyncio
    async def test_notification_called_on_success(self):
        notification_mock = MagicMock()
        notification_mock.notify_trade = AsyncMock()
        service, _ = _make_service(
            user_email=FakeUserEmail(user_id=42),
            parsed=_parsed(),
            notification_service=notification_mock,
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS
        notification_mock.notify_trade.assert_awaited_once()
        args = notification_mock.notify_trade.await_args.args
        assert args[0] == 42
        assert args[1].id == 1

    @pytest.mark.asyncio
    async def test_notification_not_called_on_failure(self):
        notification_mock = MagicMock()
        notification_mock.notify_trade = AsyncMock()
        service, _ = _make_service(
            user_email=None,
            parsed=_parsed(),
            notification_service=notification_mock,
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.FAILED
        notification_mock.notify_trade.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_works_without_notification_service(self):
        service, mocks = _make_service(
            user_email=FakeUserEmail(),
            parsed=_parsed(),
            notification_service=None,
        )
        status = await service.process_email(_email())
        assert status == ImportStatus.SUCCESS
        mocks["trade"].insert.assert_awaited_once()


class TestUserAttributionTrust:
    @pytest.mark.asyncio
    async def test_does_not_match_from_field(self):
        service, mocks = _make_service(
            user_email=None,
            parsed=_parsed(),
        )
        mocks["user_email"].find_by_email = AsyncMock(return_value=None)
        status = await service.process_email(
            _email(from_="attacker-controlled-but-broker-domain@interactivebrokers.com")
        )
        assert status == ImportStatus.FAILED
        called_with = mocks["user_email"].find_by_email.await_args.args[0]
        assert called_with != "attacker-controlled-but-broker-domain@interactivebrokers.com"
