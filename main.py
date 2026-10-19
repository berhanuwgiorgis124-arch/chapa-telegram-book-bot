from __future__ import annotations

import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

BOOK_TITLE = "«እልፍ በል»"
BOOK_PRICE_ETB = 490
BUY_BOOK_CALLBACK = "buy_book"

WELCOME_MESSAGE = (
    f"እንኳን ደህና መጡ! {BOOK_TITLE} መጽሐፍ ዋጋው {BOOK_PRICE_ETB} ETB ነው።\n\n"
    "ለግዢ መረጃ ከታች ያለውን ቁልፍ ይጫኑ።"
)
PAYMENT_DISABLED_MESSAGE = (
    f"የ{BOOK_TITLE} መጽሐፍ ክፍያ ለጊዜው አልተነቃም።\n\n"
    "እባክዎ ክፍያ አይፈጽሙ። የክፍያ አገልግሎቱ ሲዘጋጅ እንደገና ይሞክሩ።"
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def build_book_keyboard() -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(
        f"📚 {BOOK_TITLE} መጽሐፍን ግዛ ({BOOK_PRICE_ETB} ETB)",
        callback_data=BUY_BOOK_CALLBACK,
    )
    return InlineKeyboardMarkup([[button]])


async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None:
        return

    await message.reply_text(
        WELCOME_MESSAGE,
        reply_markup=build_book_keyboard(),
    )


async def purchase_notice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()
    if query.data != BUY_BOOK_CALLBACK:
        return

    await query.edit_message_text(PAYMENT_DISABLED_MESSAGE)


async def log_handler_error(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    # Avoid logging exception text: HTTP errors can include sensitive request data.
    error_name = type(context.error).__name__ if context.error else "UnknownError"
    logger.error("Telegram update handler failed (%s)", error_name)


def build_application(token: str | None = None) -> Application:
    bot_token = token if token is not None else os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError(
            "BOT_TOKEN is missing. Add the Telegram bot token in Replit Secrets."
        )

    application = ApplicationBuilder().token(bot_token).build()
    application.add_handler(CommandHandler(["start", "help"], start_command))
    application.add_handler(
        CallbackQueryHandler(
            purchase_notice,
            pattern=f"^{BUY_BOOK_CALLBACK}$",
        )
    )
    application.add_error_handler(log_handler_error)
    return application


def main() -> None:
    application = build_application()
    logger.info("Starting the Telegram book bot.")
    application.run_polling()


if __name__ == "__main__":
    main()
