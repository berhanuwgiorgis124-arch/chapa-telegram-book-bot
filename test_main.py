from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from main import (
    BOOK_PRICE_ETB,
    PAYMENT_DISABLED_MESSAGE,
    WELCOME_MESSAGE,
    build_application,
    build_book_keyboard,
    purchase_notice,
    start_command,
)


class TelegramBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_shows_book_price_and_purchase_button(self) -> None:
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=reply_text)
        )

        await start_command(update, SimpleNamespace())

        reply_text.assert_awaited_once()
        args, kwargs = reply_text.call_args
        self.assertEqual(args[0], WELCOME_MESSAGE)
        self.assertIn(str(BOOK_PRICE_ETB), args[0])
        button = kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.callback_data, "buy_book")

    async def test_purchase_button_explains_payments_are_disabled(self) -> None:
        query = SimpleNamespace(
            data="buy_book",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        send_document = AsyncMock()
        context = SimpleNamespace(bot=SimpleNamespace(send_document=send_document))

        await purchase_notice(update, context)

        query.answer.assert_awaited_once()
        query.edit_message_text.assert_awaited_once_with(PAYMENT_DISABLED_MESSAGE)
        send_document.assert_not_awaited()

    def test_application_requires_a_bot_token(self) -> None:
        with patch.dict(os.environ, {"BOT_TOKEN": ""}):
            with self.assertRaisesRegex(RuntimeError, "BOT_TOKEN"):
                build_application()

    def test_application_registers_start_and_purchase_handlers(self) -> None:
        application = build_application("123456:example-token")

        self.assertEqual(sum(map(len, application.handlers.values())), 2)
        self.assertEqual(len(application.error_handlers), 1)

    def test_book_keyboard_contains_one_buy_action(self) -> None:
        keyboard = build_book_keyboard()

        self.assertEqual(len(keyboard.inline_keyboard), 1)
        self.assertEqual(len(keyboard.inline_keyboard[0]), 1)
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "buy_book")


if __name__ == "__main__":
    unittest.main()
