# «እልፍ በል» Telegram Book Bot

A Telegram bot that introduces the Amharic book «እልፍ በል» and its 490 ETB
price.

## Run

1. Add the Telegram bot token to Replit Secrets as `BOT_TOKEN`.
2. Start the **Telegram Book Bot** workflow, or run:

   ```sh
   uv run --locked python main.py
   ```

3. Open the bot in Telegram and send `/start`.

The bot uses Telegram long polling and is configured for a Replit VM deployment,
which supports continuously running bot processes.

## Payment status

Checkout and PDF delivery are intentionally disabled. No payment provider was
connected, and the bot will clearly tell customers not to pay. Do not enable
payments until a supported payment provider is connected, successful payments
are verified against the expected amount and currency, and the book PDF is
available for delivery.
