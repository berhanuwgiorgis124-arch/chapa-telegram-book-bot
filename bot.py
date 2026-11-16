
from flask import Flask
from threading import Thread
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is active!"

@app.route('/health')
def health():
    return "OK", 200

def run():
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 8080)),
        use_reloader=False
    )

def keep_alive():
    Thread(target=run, daemon=True).start()

keep_alive()

@app.route('/health')
def health():
    return "OK", 200

import logging
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

BOOK_TITLE = "«እልፍ በል»"
BOOK_PRICE = Decimal("490.00")
CURRENCY = "ETB"
INITIALIZE_URL = "https://api.chapa.co/v1/transaction/initialize"
VERIFY_URL = "https://api.chapa.co/v1/transaction/verify"
BUY_BOOK_CALLBACK = "buy_book"
TX_REF_PATTERN = re.compile(r"^book-(\d{1,20})-([0-9a-f]{16})$")

WELCOME_MESSAGE = (
    f"እንኳን ደህና መጡ! {BOOK_TITLE} መጽሐፍ ዋጋው {BOOK_PRICE:.0f} ETB ነው።\n\n"
    "ለግዢ መረጃ ከታች ያለውን ቁልፍ ይጫኑ።"
)
PDF_MISSING_MESSAGE = (
    "መጽሐፉ ለመላክ ገና አልተዘጋጀም። እባክዎ ክፍያ አይፈጽሙ፤ "
    "ፋይሉ ከተዘጋጀ በኋላ ይህ አገልግሎት ይነቃል።"
)
CHECKOUT_ERROR_MESSAGE = (
    "የክፍያ ሊንክ ማመንጨት አልተቻለም። እባክዎ ቆይተው እንደገና ይሞክሩ።"
)
PAYMENT_PENDING_MESSAGE = (
    "ክፍያው ገና አልተረጋገጠም። ክፍያውን ከፈጸሙ በኋላ እንደገና ያረጋግጡ።"
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class ChapaError(RuntimeError):
    def __init__(self, category: str, status_code: int | None = None) -> None:
        self.category = category
        self.status_code = status_code
        super().__init__(category)


@dataclass(frozen=True)
class Order:
    tx_ref: str
    telegram_user_id: int
    amount: str
    currency: str
    status: str
    checkout_url: str | None


class OrderStore:
    """SQLite ledger to keep payment and fulfillment retries idempotent."""

    def __init__(self, path: str | Path = "data/orders.sqlite3") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                tx_ref TEXT PRIMARY KEY,
                telegram_user_id INTEGER NOT NULL,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL,
                checkout_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS orders_by_user "
            "ON orders(telegram_user_id, created_at)"
        )
        self.connection.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    @staticmethod
    def _from_row(row: sqlite3.Row | None) -> Order | None:
        if row is None:
            return None
        return Order(
            tx_ref=row["tx_ref"],
            telegram_user_id=row["telegram_user_id"],
            amount=row["amount"],
            currency=row["currency"],
            status=row["status"],
            checkout_url=row["checkout_url"],
        )

    def get_order(self, tx_ref: str) -> Order | None:
        row = self.connection.execute(
            "SELECT * FROM orders WHERE tx_ref = ?",
            (tx_ref,),
        ).fetchone()
        return self._from_row(row)

    def get_open_order(self, telegram_user_id: int) -> Order | None:
        row = self.connection.execute(
            """
            SELECT * FROM orders
            WHERE telegram_user_id = ? AND status != 'failed'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (telegram_user_id,),
        ).fetchone()
        return self._from_row(row)

    def create_or_get_order(
        self, telegram_user_id: int, tx_ref: str
    ) -> tuple[Order, bool]:
        now = self._now()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                """
                SELECT * FROM orders
                WHERE telegram_user_id = ? AND status != 'failed'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (telegram_user_id,),
            ).fetchone()
            if row is not None:
                self.connection.commit()
                order = self._from_row(row)
                assert order is not None
                return order, False

            self.connection.execute(
                """
                INSERT INTO orders (
                    tx_ref, telegram_user_id, amount, currency, status,
                    checkout_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'initializing', NULL, ?, ?)
                """,
                (tx_ref, telegram_user_id, str(BOOK_PRICE), CURRENCY, now, now),
            )
            self.connection.commit()
            order = self.get_order(tx_ref)
            assert order is not None
            return order, True
        except Exception:
            self.connection.rollback()
            raise

    def set_checkout_url(self, tx_ref: str, checkout_url: str) -> None:
        self.connection.execute(
            """
            UPDATE orders
            SET checkout_url = ?, status = 'pending', updated_at = ?
            WHERE tx_ref = ? AND status = 'initializing'
            """,
            (checkout_url, self._now(), tx_ref),
        )
        self.connection.commit()

    def mark_failed(self, tx_ref: str) -> None:
        self.connection.execute(
            """
            UPDATE orders SET status = 'failed', updated_at = ?
            WHERE tx_ref = ? AND status = 'initializing'
            """,
            (self._now(), tx_ref),
        )
        self.connection.commit()

    def mark_paid(self, tx_ref: str) -> bool:
        self.connection.execute(
            """
            UPDATE orders SET status = 'paid', updated_at = ?
            WHERE tx_ref = ? AND status = 'pending'
            """,
            (self._now(), tx_ref),
        )
        self.connection.commit()
        order = self.get_order(tx_ref)
        return order is not None and order.status == "paid"

    def claim_delivery(self, tx_ref: str) -> bool:
        cursor = self.connection.execute(
            """
            UPDATE orders SET status = 'delivering', updated_at = ?
            WHERE tx_ref = ? AND status = 'paid'
            """,
            (self._now(), tx_ref),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def mark_delivered(self, tx_ref: str) -> None:
        self.connection.execute(
            """
            UPDATE orders SET status = 'delivered', updated_at = ?
            WHERE tx_ref = ? AND status = 'delivering'
            """,
            (self._now(), tx_ref),
        )
        self.connection.commit()

    def release_delivery(self, tx_ref: str) -> None:
        self.connection.execute(
            """
            UPDATE orders SET status = 'paid', updated_at = ?
            WHERE tx_ref = ? AND status = 'delivering'
            """,
            (self._now(), tx_ref),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class ChapaClient:
    def __init__(
        self,
        secret_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.secret_key = (
            secret_key
            if secret_key is not None
            else os.getenv("CHAPA_SECRET_KEY", "").strip()
        )
        if not self.secret_key:
            raise RuntimeError(
                "CHAPA_SECRET_KEY is missing. Add it in Replit Secrets."
            )
        self.transport = transport

    async def _request_json(
        self,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=5.0),
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as error:
            raise ChapaError("http_status", error.response.status_code) from None
        except httpx.HTTPError as error:
            raise ChapaError(type(error).__name__) from None
        except ValueError:
            raise ChapaError("invalid_json") from None

        if not isinstance(body, dict):
            raise ChapaError("invalid_response")
        return body

    async def initialize(
        self,
        *,
        tx_ref: str,
        first_name: str,
        last_name: str,
    ) -> str:
        payload = await self._request_json(
            "POST",
            INITIALIZE_URL,
            {
                "amount": f"{BOOK_PRICE:.2f}",
                "currency": CURRENCY,
                "tx_ref": tx_ref,
                "first_name": first_name or "ገዢ",
                "last_name": last_name or "",
            },
        )
        data = payload.get("data")
        checkout_url = data.get("checkout_url") if isinstance(data, dict) else None
        if payload.get("status") != "success":
            raise ChapaError("provider_rejected")
        if not self._is_chapa_checkout_url(checkout_url):
            raise ChapaError("invalid_checkout_url")
        return checkout_url

    async def verify(self, tx_ref: str) -> dict[str, Any]:
        return await self._request_json("GET", f"{VERIFY_URL}/{tx_ref}")

    @staticmethod
    def _is_chapa_checkout_url(value: object) -> bool:
        if not isinstance(value, str):
            return False
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (
            host == "chapa.co" or host.endswith(".chapa.co")
        )


def is_verified_purchase(
    response: dict[str, Any],
    *,
    expected_tx_ref: str,
    expected_amount: Decimal = BOOK_PRICE,
    expected_currency: str = CURRENCY,
) -> bool:
    data = response.get("data")
    if (
        response.get("status") != "success"
        or not isinstance(data, dict)
        or str(data.get("status", "")).lower() != "success"
        or data.get("tx_ref") != expected_tx_ref
        or str(data.get("currency", "")).upper() != expected_currency
    ):
        return False
    try:
        actual_amount = Decimal(str(data.get("amount")))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return actual_amount == expected_amount


def make_tx_ref(telegram_user_id: int) -> str:
    return f"book-{telegram_user_id}-{secrets.token_hex(8)}"


def owner_from_tx_ref(tx_ref: str) -> int | None:
    match = TX_REF_PATTERN.fullmatch(tx_ref)
    return int(match.group(1)) if match else None


def build_book_keyboard() -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(
        f"📚 {BOOK_TITLE} መጽሐፍን ግዛ ({BOOK_PRICE:.0f} ETB)",
        callback_data=BUY_BOOK_CALLBACK,
    )
    return InlineKeyboardMarkup([[button]])


def build_checkout_keyboard(order: Order) -> InlineKeyboardMarkup:
    if not order.checkout_url:
        raise ValueError("A pending order must have a checkout URL.")
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💳 ክፍያ ፈጽም (Pay Now)",
                    url=order.checkout_url,
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 ክፍያ አረጋግጥ (Verify Payment)",
                    callback_data=f"verify:{order.tx_ref}",
                )
            ],
        ]
    )


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


async def _show_existing_order(query: Any, order: Order) -> None:
    if order.status == "pending" and order.checkout_url:
        await query.edit_message_text(
            "የክፍያ ማገናኛዎ ከታች አለ። ክፍያውን ከፈጸሙ በኋላ አረጋግጡ።",
            reply_markup=build_checkout_keyboard(order),
        )
    elif order.status == "initializing":
        await query.edit_message_text(
            "የክፍያ ማገናኛው እየተዘጋጀ ነው። እባክዎ ትንሽ ቆይተው ይሞክሩ።"
        )
    elif order.status == "paid":
        await query.edit_message_text(
            "ክፍያዎ ተረጋግጧል። የመጽሐፉ መላክ እየተዘጋጀ ነው።"
        )
    elif order.status == "delivering":
        await query.edit_message_text(
            "ክፍያዎ ተረጋግጧል። መጽሐፉ እየተላከ ነው፤ እባክዎ ይጠብቁ።"
        )
    elif order.status == "delivered":
        await query.edit_message_text(
            "ይህ መጽሐፍ ቀደም ሲል ተልኮልዎታል። እንደገና ክፍያ አያስፈልግም።"
        )
    else:
        await query.edit_message_text(CHECKOUT_ERROR_MESSAGE)


async def purchase_notice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if query.data != BUY_BOOK_CALLBACK:
        return

    order_store: OrderStore = context.application.bot_data["order_store"]
    chapa: ChapaClient = context.application.bot_data["chapa"]
    pdf_path: Path = context.application.bot_data["book_pdf_path"]
    user = query.from_user

    if not pdf_path.is_file():
        await query.edit_message_text(PDF_MISSING_MESSAGE)
        return

    existing_order = order_store.get_open_order(user.id)
    if existing_order is not None:
        await _show_existing_order(query, existing_order)
        return

    order, created = order_store.create_or_get_order(user.id, make_tx_ref(user.id))
    if not created:
        await _show_existing_order(query, order)
        return

    try:
        checkout_url = await chapa.initialize(
            tx_ref=order.tx_ref,
            first_name=user.first_name or "ገዢ",
            last_name=user.last_name or "",
        )
    except ChapaError as error:
        order_store.mark_failed(order.tx_ref)
        logger.warning(
            "Chapa checkout initialization failed (category=%s, status=%s)",
            error.category,
            error.status_code,
        )
        await query.edit_message_text(CHECKOUT_ERROR_MESSAGE)
        return

    order_store.set_checkout_url(order.tx_ref, checkout_url)
    updated_order = order_store.get_order(order.tx_ref)
    if updated_order is None:
        logger.error("Order disappeared after checkout initialization.")
        await query.edit_message_text(CHECKOUT_ERROR_MESSAGE)
        return

    await query.edit_message_text(
        "እባክዎ ከታች ባለው ሊንክ ክፍያውን ይፈጽሙ፤ ከጨረሱ በኋላ ክፍያውን ያረጋግጡ።",
        reply_markup=build_checkout_keyboard(updated_order),
    )


async def verify_payment(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    callback_data = query.data or ""
    if not callback_data.startswith("verify:"):
        return
    tx_ref = callback_data.partition(":")[2]
    if owner_from_tx_ref(tx_ref) != query.from_user.id:
        await query.edit_message_text(PAYMENT_PENDING_MESSAGE)
        return

    order_store: OrderStore = context.application.bot_data["order_store"]
    chapa: ChapaClient = context.application.bot_data["chapa"]
    pdf_path: Path = context.application.bot_data["book_pdf_path"]
    order = order_store.get_order(tx_ref)
    if order is None or order.telegram_user_id != query.from_user.id:
        await query.edit_message_text(PAYMENT_PENDING_MESSAGE)
        return

    if order.status in {"delivered", "delivering", "initializing"}:
        await _show_existing_order(query, order)
        return

    if order.status == "pending":
        try:
            verification = await chapa.verify(tx_ref)
        except ChapaError as error:
            logger.warning(
                "Chapa verification failed (category=%s, status=%s)",
                error.category,
                error.status_code,
            )
            await query.edit_message_text(PAYMENT_PENDING_MESSAGE)
            return

        if not is_verified_purchase(
            verification,
            expected_tx_ref=order.tx_ref,
            expected_amount=Decimal(order.amount),
            expected_currency=order.currency,
        ):
            await query.edit_message_text(PAYMENT_PENDING_MESSAGE)
            return
        if not order_store.mark_paid(order.tx_ref):
            latest_order = order_store.get_order(order.tx_ref)
            if latest_order is None or latest_order.status != "paid":
                await query.edit_message_text(PAYMENT_PENDING_MESSAGE)
                return
            order = latest_order
        else:
            order = order_store.get_order(tx_ref) or order

    if order.status != "paid":
        await query.edit_message_text(PAYMENT_PENDING_MESSAGE)
        return

    if not pdf_path.is_file():
        await query.edit_message_text(
            "ክፍያዎ ተረጋግጧል፣ ግን የመጽሐፉ ፋይል ለጊዜው አይገኝም። "
            "እባክዎ እንደገና ክፍያ አይፈጽሙ፤ ፋይሉ ሲዘጋጅ መላኩ ይቀጥላል።"
        )
        return

    if not order_store.claim_delivery(tx_ref):
        latest_order = order_store.get_order(tx_ref)
        if latest_order is not None:
            await _show_existing_order(query, latest_order)
        return

    try:
        with pdf_path.open("rb") as book_file:
            await context.bot.send_document(
                chat_id=query.from_user.id,
                document=book_file,
                caption=f"እነሆ {BOOK_TITLE} መጽሐፍ። መልካም ንባብ!",
                protect_content=True,
            )
    except (OSError, TelegramError, httpx.HTTPError) as error:
        order_store.release_delivery(tx_ref)
        logger.warning("Book delivery failed (%s)", type(error).__name__)
        await query.edit_message_text(
            "ክፍያዎ ተረጋግጧል፣ ግን መጽሐፉን መላክ አልተቻለም። "
            "እባክዎ ይህን መልዕክት እንደገና ያረጋግጡ፤ ክፍያውን እንደገና አይፈጽሙ።"
        )
        return

    order_store.mark_delivered(tx_ref)
    await query.edit_message_text("ክፍያዎ ተሳክቷል፤ መጽሐፉ በግል መልዕክት ተልኳል።")


async def log_handler_error(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    error_name = type(context.error).__name__ if context.error else "UnknownError"
    logger.error("Telegram update handler failed (%s)", error_name)


def build_application(
    token: str | None = None,
    *,
    chapa: ChapaClient | None = None,
    order_store: OrderStore | None = None,
    pdf_path: str | Path | None = None,
) -> Application:
    bot_token = token if token is not None else os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError(
            "BOT_TOKEN is missing. Add the Telegram bot token in Replit Secrets."
        )

    application = ApplicationBuilder().token(bot_token).build()
    application.bot_data["chapa"] = chapa or ChapaClient()
    application.bot_data["order_store"] = order_store or OrderStore(
        os.getenv("ORDER_DB_PATH", "data/orders.sqlite3")
    )
    application.bot_data["book_pdf_path"] = Path(
        pdf_path or os.getenv("BOOK_PDF_PATH", "book.pdf")
    )
    application.add_handler(CommandHandler(["start", "help"], start_command))
    application.add_handler(
        CallbackQueryHandler(purchase_notice, pattern=f"^{BUY_BOOK_CALLBACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(verify_payment, pattern=r"^verify:")
    )
    application.add_error_handler(log_handler_error)
    return application

def main() -> None:
    application = build_application()
    logger.info("Starting the Telegram book bot.")
    application.run_polling()


if __name__ == "__main__":
    keep_alive()
    main()
    
