import asyncio
from typing import Any, Callable, Coroutine

import structlog
from imap_tools import AND, MailBox

from app.config.settings import get_settings
from app.database.enums import ImportStatus
from app.services.email_ingestion import EmailIngestionService
from app.services.notification import NotificationService
from app.services.parsers import IBKRParser, ParserRegistry
from app.telegram.bot import TelegramBot
from app.utils.html import strip_html

logger = structlog.get_logger()


class GmailPoller:
    """Polls Gmail via IMAP for unseen emails and processes them."""

    def __init__(
        self,
        telegram_bot: TelegramBot | None = None,
        on_email_processed: Callable[[ImportStatus], Coroutine[Any, Any, None]] | None = None,
    ):
        self.settings = get_settings()
        self.on_email_processed = on_email_processed
        self.telegram_bot = telegram_bot
        self._running = False
        self._task: asyncio.Task | None = None

        # Set up parser registry — one parser per broker / channel.
        self.parser_registry = ParserRegistry()
        self.parser_registry.register(IBKRParser())

    async def start(self) -> None:
        """Start the polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("gmail_poller_started", host=self.settings.imap_host)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("gmail_poller_stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                logger.error("poll_error", error=str(e))
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _poll_once(self) -> None:
        logger.debug("poll_start")

        def fetch_unseen():
            with MailBox(self.settings.imap_host, port=self.settings.imap_port) as mailbox:
                mailbox.login(self.settings.imap_username, self.settings.imap_password)
                return list(mailbox.fetch(AND(seen=False), limit=100))

        try:
            emails = await asyncio.to_thread(fetch_unseen)
        except Exception as e:
            logger.error("fetch_error", error=str(e))
            return

        for email in emails:
            await self._process_email(email)

        logger.info("poll_end", emails_fetched=len(emails))

    async def _process_email(self, email) -> None:
        message_id = email.uid or ""
        if not message_id:
            logger.warning("email_no_uid", subject=email.subject)
            await asyncio.to_thread(self._mark_as_read, email)
            return

        logger.debug(
            "email_fetched",
            message_id=message_id,
            subject=email.subject,
        )

        body = email.text or (strip_html(email.html) if email.html else "") or ""
        email_dict = {
            "message_id": message_id,
            "subject": email.subject,
            "body": body,
            "from": email.from_,
            "to": list(email.to),
            "cc": list(email.cc),
            "date": email.date,
        }

        try:
            notification_service = None
            if self.telegram_bot is not None and self.telegram_bot._app is not None:
                notification_service = NotificationService(self.telegram_bot._app)
            service = EmailIngestionService(
                self.parser_registry,
                notification_service=notification_service,
            )
            status = await service.process_email(email_dict)
            if status in (ImportStatus.SUCCESS, ImportStatus.SKIPPED, ImportStatus.FAILED):
                await asyncio.to_thread(self._mark_as_read, email)

            if status == ImportStatus.SUCCESS:
                logger.info("email_processed", message_id=message_id, status=status.value)
            elif status == ImportStatus.FAILED:
                logger.warning("email_failed", message_id=message_id, status=status.value)
            else:
                logger.info("email_skipped", message_id=message_id)

            if self.on_email_processed:
                await self.on_email_processed(status)

        except Exception as e:
            logger.error("email_error", message_id=message_id, error=str(e))
            await asyncio.to_thread(self._mark_as_read, email)

    def _mark_as_read(self, email) -> None:
        try:
            with MailBox(self.settings.imap_host, port=self.settings.imap_port).login(
                self.settings.imap_username,
                self.settings.imap_password,
            ) as mailbox:
                mailbox.flag(email.uid, ["\\Seen"], True)
        except Exception as e:
            logger.error("mark_read_error", error=str(e))
