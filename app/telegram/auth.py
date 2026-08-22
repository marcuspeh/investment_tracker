from telegram import Update
from telegram.ext import ContextTypes

from app.database.repositories.user import UserRepository


class AuthMiddleware:
    """Middleware that loads whitelist on startup and enforces authorization."""

    def __init__(self):
        self._whitelist: set[int] = set()
        self._user_repo = UserRepository()

    async def load_whitelist(self) -> None:
        """Load the whitelist of allowed users from the database."""
        users = await self._user_repo.list_active()
        self._whitelist = {user.telegram_chat_id for user in users}

        if not self._whitelist:
            raise ValueError("No users in whitelist. Please add users to the database.")

    def is_authorized(self, chat_id: int) -> bool:
        return chat_id in self._whitelist


auth_middleware = AuthMiddleware()


async def auth_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat is None:
        return False

    chat_id = update.effective_chat.id
    if not auth_middleware.is_authorized(chat_id):
        await update.message.reply_text(
            "You are not authorized to use this bot. Please contact the administrator."
        )
        return False
    return True
