from telegram import Update
from telegram.ext import ContextTypes

from app.database.repositories.user import UserRepository
from app.services.trade import TradeService
from app.telegram.auth import auth_handler
from app.telegram.handlers._helpers import (
    add_pending_delete,
    cancel_pending,
    clear_recent,
    format_trade,
    list_pending,
    pop_pending_deletes,
    resolve_recent,
)


async def _resolve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_handler(update, context):
        return None
    user_repo = UserRepository()
    user = await user_repo.get_by_chat_id(update.effective_chat.id)
    if not user:
        await update.message.reply_text("User not found.")
        return None
    return user


async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/delete <id|index>`` — start delete confirmation."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /delete <id|index>\n"
            "Send /confirm <id> (or /confirm) to proceed, /cancel to abort."
        )
        return

    user = await _resolve_user(update, context)
    if not user:
        return

    chat_id = update.effective_chat.id
    service = TradeService()
    pending_ids: list[int] = []
    unknown: list[str] = []

    for arg in args:
        # Try recent-index first so users can /delete 1 directly off /latest.
        trade_id = resolve_recent(chat_id, arg)
        if trade_id is None:
            try:
                trade_id = int(arg)
            except ValueError:
                unknown.append(arg)
                continue

        trade = await service.trade_repo.get_by_id_for_user(trade_id, user.id)
        if trade is None:
            unknown.append(arg)
            continue
        add_pending_delete(chat_id, trade_id)
        pending_ids.append(trade_id)

    if not pending_ids:
        await update.message.reply_text(
            f"No valid trades matched: {' '.join(args)}.\n"
            f"Unknown / not owned: {' '.join(unknown) if unknown else '(none)'}"
        )
        return

    preview_lines = []
    for tid in pending_ids:
        trade = await service.trade_repo.get_by_id_for_user(tid, user.id)
        if trade is not None:
            preview_lines.append(format_trade(trade, 0).rstrip())

    args_text = " ".join(str(i) for i in pending_ids)
    suffix = f"Reply /confirm {args_text} to delete all, or /cancel to abort."
    await update.message.reply_text(
        "About to delete:\n\n" + "\n".join(preview_lines) + f"\n\n{suffix}"
    )


async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/confirm [id|index]`` — finalize pending deletes."""
    args = context.args
    user = await _resolve_user(update, context)
    if not user:
        return

    chat_id = update.effective_chat.id
    pending = list_pending(chat_id)
    if not pending:
        await update.message.reply_text("Nothing to confirm.")
        return

    target_ids: list[int] = []
    if not args:
        # Confirm everything pending.
        target_ids = list(pending)
    else:
        for arg in args:
            trade_id = resolve_recent(chat_id, arg)
            if trade_id is None:
                try:
                    trade_id = int(arg)
                except ValueError:
                    continue
            target_ids.append(trade_id)

    removed = pop_pending_deletes(chat_id, target_ids)
    if not removed:
        await update.message.reply_text(f"None of {target_ids} are pending. Use /delete first.")
        return

    service = TradeService()
    deleted: list[int] = []
    not_owned: list[int] = []
    for tid in removed:
        ok = await service.delete_trade(tid, user.id)
        if ok:
            deleted.append(tid)
        else:
            not_owned.append(tid)

    response_lines = []
    if deleted:
        response_lines.append(f"Deleted trade(s): {' '.join(str(i) for i in deleted)}")
    if not_owned:
        response_lines.append(f"Not owned / already gone: {' '.join(str(i) for i in not_owned)}")
    clear_recent(chat_id)
    await update.message.reply_text("\n".join(response_lines))


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/cancel [id|index]`` — drop pending deletes."""
    args = context.args
    chat_id = update.effective_chat.id

    if not args:
        removed = cancel_pending(chat_id)
        msg = "All pending deletes cancelled." if removed else "No pending deletes."
        await update.message.reply_text(msg)
        return

    target_ids: list[int] = []
    for arg in args:
        trade_id = resolve_recent(chat_id, arg)
        if trade_id is None:
            try:
                trade_id = int(arg)
            except ValueError:
                continue
        target_ids.append(trade_id)

    removed = cancel_pending(chat_id, target_ids)
    if removed:
        await update.message.reply_text(
            f"Cancelled pending delete(s): {' '.join(str(i) for i in removed)}"
        )
    else:
        await update.message.reply_text("None of those were pending.")
