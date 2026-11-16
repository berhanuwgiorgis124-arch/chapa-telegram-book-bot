# «እልፍ በል» Telegram Book Bot

A Telegram bot that accepts a 490 ETB payment through Chapa and delivers the
Amharic book PDF after verifying the transaction.

## Run

1. Add `BOT_TOKEN` and `CHAPA_SECRET_KEY` to Replit Secrets.
2. Add the book PDF as `book.pdf` in the project root. Checkout stays disabled until this
   file exists.
3. Start the **Telegram Book Bot** workflow, or run:

   ```sh
   uv run --locked python bot.py
   ```

4. Open the bot in Telegram and send `/start`.

The **Telegram Book Bot** workflow runs long polling in the development
workspace. Production deployment should use an always-on VM service; the existing
API artifact currently has its own Node.js production command.

## Payment and delivery safeguards

- Chapa calls use `httpx.AsyncClient` with a timeout; the bot event loop is not
  blocked by synchronous HTTP requests.
- The verify action checks Chapa's success status, exact `tx_ref`, 490 ETB
  amount, and ETB currency before fulfillment.
- A SQLite order ledger prevents repeated verification clicks from sending a
  second copy after delivery.
- The PDF is sent with Telegram's `protect_content=True` option. This discourages
  forwarding and saving in Telegram, but cannot prevent screenshots or other
  forms of copying.
- Checkout is blocked until `book.pdf` is present.

Run the tests with:

```sh
uv run --locked python -m unittest discover -v
```
