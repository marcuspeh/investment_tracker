from typing import Any

from app.database.enums import ImportStatus, TradeSide
from app.database.repositories.imported_email import ImportedEmailRepository
from app.database.repositories.trade import TradeRepository
from app.database.repositories.user_email import UserEmailRepository
from app.services.notification import NotificationService
from app.services.parsers.base import ParserError
from app.services.parsers.registry import ParserRegistry
from app.utils.timezone import sgt_to_utc


class EmailIngestionService:
    """Service for processing incoming emails and extracting trades."""

    def __init__(
        self,
        parser_registry: ParserRegistry,
        notification_service: NotificationService | None = None,
    ):
        self.parser_registry = parser_registry
        self.notification_service = notification_service
        self.trade_repo = TradeRepository()
        self.user_email_repo = UserEmailRepository()
        self.imported_email_repo = ImportedEmailRepository()

    async def process_email(self, email: dict[str, Any]) -> ImportStatus:
        """Process an email and extract a trade if possible.

        Args:
            email: Email dict with 'message_id', 'subject', 'body', 'from', etc.

        Returns:
            ImportStatus indicating the result of processing.
        """
        message_id = email.get("message_id", "")
        if await self.imported_email_repo.exists_by_message_id(message_id):
            existing = await self.imported_email_repo.get_by_message_id(message_id)
            if existing and existing.status == ImportStatus.FAILED:
                if existing.reason == "UNKNOWN_FORWARDER":
                    return ImportStatus.FAILED
            return existing.status if existing else ImportStatus.SKIPPED

        parser = self.parser_registry.find_parser(email)
        if parser is None:
            await self.imported_email_repo.insert(message_id, ImportStatus.SKIPPED)
            return ImportStatus.SKIPPED

        try:
            parsed = parser.parse(email)
        except ParserError:
            await self.imported_email_repo.insert(message_id, ImportStatus.FAILED, "PARSE_ERROR")
            return ImportStatus.FAILED

        if parsed.side not in TradeSide._value2member_map_:
            await self.imported_email_repo.insert(message_id, ImportStatus.FAILED, "UNKNOWN_SIDE")
            return ImportStatus.FAILED

        # Resolve ownership. Trust only `to`/`cc` — these are the addresses
        # the email was actually delivered to. `from` is the broker's domain
        # and is not user-controlled.
        candidate_emails: list[str] = []
        for field in ("to", "cc"):
            value = email.get(field)
            if isinstance(value, str):
                candidate_emails.append(value)
            elif isinstance(value, (list, tuple)):
                candidate_emails.extend(v for v in value if v)

        user_email = None
        for candidate in candidate_emails:
            user_email = await self.user_email_repo.find_by_email(candidate)
            if user_email:
                break

        if not user_email:
            await self.imported_email_repo.insert(
                message_id, ImportStatus.FAILED, "UNKNOWN_FORWARDER"
            )
            return ImportStatus.FAILED

        side = TradeSide(parsed.side)
        trade_time_utc = sgt_to_utc(parsed.trade_time)

        trade = await self.trade_repo.insert(
            user_id=user_email.user_id,
            side=side,
            symbol=parsed.symbol,
            quantity=parsed.quantity,
            price=parsed.price,
            currency=parsed.currency,
            account_id=parsed.account_id,
            trade_time=trade_time_utc,
            notional=(parsed.quantity * parsed.price),
            description=parsed.description,
        )

        if self.notification_service is not None:
            await self.notification_service.notify_trade(user_email.user_id, trade)

        await self.imported_email_repo.insert(message_id, ImportStatus.SUCCESS)
        return ImportStatus.SUCCESS
