# «እልፍ በል» Telegram Book Bot

A Telegram bot that accepts a 490 ETB Chapa payment for the Amharic book «እልፍ በል» and sends the PDF after verifying the transaction.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `uv run --locked python bot.py` — run the Telegram bot
- `uv run --locked python -m unittest discover -v` — run bot tests
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required secrets: `BOT_TOKEN`, `CHAPA_SECRET_KEY`
- Required file: `book.pdf` — checkout is blocked until the file exists
- Recommended deployment target: VM, because Telegram long polling needs a continuously running process
- The bot currently runs as a development workflow; production services in this pnpm workspace are configured per artifact

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- Python 3.13, `python-telegram-bot`
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

- `bot.py` — Telegram handlers, Chapa HTTP client, order ledger, and PDF fulfillment
- `test_bot.py` — bot, payment validation, and API request tests
- `pyproject.toml` and `uv.lock` — Python dependencies
- `book.pdf` — book file to deliver
- `data/orders.sqlite3` — local payment and fulfillment ledger (generated at runtime)
- `artifacts/api-server` — shared Express API service

## Architecture decisions

- Verify Chapa's transaction reference, status, amount, and currency before delivering the book.
- The bot is configured for VM deployment because Telegram long polling needs a continuously running process.
- Chapa initialization intentionally sends only the core transaction fields; the optional nested `customization` object caused HTTP 400, while the minimal payload returned a hosted checkout URL.

## Product

- `/start` and `/help` show the book and its 490 ETB price.
- Checkout and PDF delivery require `book.pdf`; purchases are blocked until it exists.

## User preferences

None stated.

## Gotchas

- `protect_content=True` discourages forwarding and saving but cannot prevent screenshots or other copying.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
