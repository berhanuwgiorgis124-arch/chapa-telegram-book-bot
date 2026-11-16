from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from bot import (
    BOOK_PRICE,
    CURRENCY,
    INITIALIZE_URL,
    PAYMENT_PENDING_MESSAGE,
    PDF_MISSING_MESSAGE,
    VERIFY_URL,
    ChapaClient,
    OrderStore,
    build_application,
    build_book_keyboard,
    is_verified_purchase,
    make_tx_ref,
    owner_from_tx_ref,
    purchase_notice,
    start_command,
    verify_payment,
)


def success_response(tx_ref: str, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "status": "success",
        "tx_ref": tx_ref,
        "amount": "490.00",
        "currency": "ETB",
    }
    data.update(overrides)
    return {"status": "success", "data": data}


class FakeChapa:
    def __init__(
        self,
        *,
        checkout_url: str = "https://checkout.chapa.co/checkout/example",
        verification: dict[str, object] | None = None,
    ) -> None:
        self.checkout_url = checkout_url
        self.verification = verification
        self.initialize = AsyncMock(return_value=checkout_url)
        self.verify = AsyncMock(
            return_value=verification or success_response("unused")
        )


class TelegramBotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "orders.sqlite3"
        self.pdf_path = Path(self.tempdir.name) / "book.pdf"
        self.store = OrderStore(self.db_path)
        self.addCleanup(self.store.close)

    async def test_start_shows_book_price_and_buy_button(self) -> None:
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=reply_text)
        )

        await start_command(update, SimpleNamespace())

        reply_text.assert_awaited_once()
        args, kwargs = reply_text.call_args
        self.assertIn("490 ETB", args[0])
        self.assertEqual(
            kwargs["reply_markup"].inline_keyboard[0][0].callback_data,
            "buy_book",
        )

    async def test_missing_pdf_blocks_checkout_before_chapa_call(self) -> None:
        query = self.make_query("buy_book")
        chapa = FakeChapa()
        context = self.make_context(chapa)

        await purchase_notice(SimpleNamespace(callback_query=query), context)

        chapa.initialize.assert_not_awaited()
        query.edit_message_text.assert_awaited_once_with(PDF_MISSING_MESSAGE)

    async def test_checkout_creates_order_and_chapa_link(self) -> None:
        self.pdf_path.write_bytes(b"sample pdf")
        user = SimpleNamespace(id=42, first_name="Test", last_name="Reader")
        query = self.make_query("buy_book", user=user)
        chapa = FakeChapa()
        context = self.make_context(chapa)

        await purchase_notice(SimpleNamespace(callback_query=query), context)

        chapa.initialize.assert_awaited_once()
        initialized = chapa.initialize.await_args.kwargs
        self.assertEqual(initialized["first_name"], "Test")
        self.assertEqual(owner_from_tx_ref(initialized["tx_ref"]), 42)
        order = self.store.get_open_order(42)
        self.assertIsNotNone(order)
        assert order is not None
        self.assertEqual(order.status, "pending")
        self.assertEqual(order.amount, str(BOOK_PRICE))
        self.assertIn("checkout.chapa.co", query.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url)

    async def test_verify_sends_pdf_with_content_protection_once(self) -> None:
        self.pdf_path.write_bytes(b"sample pdf")
        user_id = 42
        tx_ref = make_tx_ref(user_id)
        order, created = self.store.create_or_get_order(user_id, tx_ref)
        self.assertTrue(created)
        self.store.set_checkout_url(
            tx_ref, "https://checkout.chapa.co/checkout/example"
        )
        query = self.make_query(f"verify:{tx_ref}", user=SimpleNamespace(id=user_id))
        chapa = FakeChapa(verification=success_response(tx_ref))
        send_document = AsyncMock()
        context = self.make_context(chapa, send_document=send_document)

        await verify_payment(SimpleNamespace(callback_query=query), context)
        await verify_payment(SimpleNamespace(callback_query=query), context)

        chapa.verify.assert_awaited_once_with(tx_ref)
        send_document.assert_awaited_once()
        self.assertTrue(send_document.await_args.kwargs["protect_content"])
        self.assertEqual(self.store.get_order(tx_ref).status, "delivered")

    async def test_verify_rejects_another_users_transaction(self) -> None:
        tx_ref = make_tx_ref(88)
        query = self.make_query(
            f"verify:{tx_ref}",
            user=SimpleNamespace(id=42),
        )
        chapa = FakeChapa()
        context = self.make_context(chapa)

        await verify_payment(SimpleNamespace(callback_query=query), context)

        chapa.verify.assert_not_awaited()
        query.edit_message_text.assert_awaited_once_with(PAYMENT_PENDING_MESSAGE)

    def make_query(
        self,
        data: str,
        *,
        user: SimpleNamespace | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            data=data,
            from_user=user or SimpleNamespace(id=42, first_name="Test", last_name="Reader"),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )

    def make_context(
        self,
        chapa: FakeChapa,
        *,
        send_document: AsyncMock | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "chapa": chapa,
                    "order_store": self.store,
                    "book_pdf_path": self.pdf_path,
                }
            ),
            bot=SimpleNamespace(send_document=send_document or AsyncMock()),
        )


class ChapaClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_calls_official_endpoint_with_bearer_secret(self) -> None:
        seen_requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "checkout_url": "https://checkout.chapa.co/checkout/example"
                    },
                },
            )

        tx_ref = make_tx_ref(42)
        client = ChapaClient(
            "test-secret",
            transport=httpx.MockTransport(handler),
        )

        checkout_url = await client.initialize(
            tx_ref=tx_ref,
            first_name="Test",
            last_name="Reader",
        )

        self.assertEqual(checkout_url, "https://checkout.chapa.co/checkout/example")
        request = seen_requests[0]
        self.assertEqual(str(request.url), INITIALIZE_URL)
        self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
        payload = __import__("json").loads(request.content)
        self.assertEqual(payload["amount"], "490.00")
        self.assertEqual(payload["currency"], CURRENCY)
        self.assertEqual(payload["tx_ref"], tx_ref)
        self.assertNotIn("customization", payload)

    async def test_verify_calls_official_reference_endpoint(self) -> None:
        seen_requests: list[httpx.Request] = []
        tx_ref = make_tx_ref(42)

        async def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return httpx.Response(200, json=success_response(tx_ref))

        client = ChapaClient(
            "test-secret",
            transport=httpx.MockTransport(handler),
        )

        response = await client.verify(tx_ref)

        self.assertEqual(str(seen_requests[0].url), f"{VERIFY_URL}/{tx_ref}")
        self.assertEqual(seen_requests[0].method, "GET")
        self.assertEqual(response["data"]["tx_ref"], tx_ref)


class PaymentValidationTests(unittest.TestCase):
    def test_verification_requires_success_and_exact_purchase_fields(self) -> None:
        tx_ref = make_tx_ref(42)

        self.assertTrue(is_verified_purchase(success_response(tx_ref), expected_tx_ref=tx_ref))
        self.assertFalse(
            is_verified_purchase(
                success_response(tx_ref, amount="489.00"),
                expected_tx_ref=tx_ref,
            )
        )
        self.assertFalse(
            is_verified_purchase(
                success_response(tx_ref, currency="USD"),
                expected_tx_ref=tx_ref,
            )
        )
        self.assertFalse(
            is_verified_purchase(
                success_response("another-reference"),
                expected_tx_ref=tx_ref,
            )
        )
        self.assertFalse(
            is_verified_purchase(
                {"status": "failed", "data": success_response(tx_ref)["data"]},
                expected_tx_ref=tx_ref,
            )
        )

    def test_transaction_reference_is_bound_to_telegram_user(self) -> None:
        tx_ref = make_tx_ref(123456)

        self.assertEqual(owner_from_tx_ref(tx_ref), 123456)
        self.assertIsNone(owner_from_tx_ref("book-123456-not-a-valid-reference"))

    def test_application_requires_both_secrets(self) -> None:
        with patch.dict(os.environ, {"BOT_TOKEN": "", "CHAPA_SECRET_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "BOT_TOKEN"):
                build_application()
        with patch.dict(os.environ, {"BOT_TOKEN": "test-token", "CHAPA_SECRET_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "CHAPA_SECRET_KEY"):
                build_application()

    def test_book_keyboard_contains_one_purchase_action(self) -> None:
        keyboard = build_book_keyboard()

        self.assertEqual(len(keyboard.inline_keyboard), 1)
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "buy_book")


if __name__ == "__main__":
    unittest.main()
