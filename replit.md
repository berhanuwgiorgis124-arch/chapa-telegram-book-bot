# «እልፍ በል» Telegram Book Bot

A Telegram bot that introduces the Amharic book «እልፍ በል» at 490 ETB. Payment and PDF delivery are disabled until a supported payment provider is connected and the book file is available.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `uv run --locked python main.py` — run the Telegram bot
- `python -m unittest discover -v` — run bot tests
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required secret: `BOT_TOKEN`
- Deployment target: VM, for the bot's long-running Telegram polling process

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- Python 3.13, `python-telegram-bot`
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

- `main.py` — Telegram commands and the book purchase prompt
- `test_main.py` — bot behavior tests
- `pyproject.toml` and `uv.lock` — Python dependencies
- `artifacts/api-server` — shared Express API service

## Architecture decisions

- Checkout is intentionally inactive; do not represent a purchase as paid or deliver the book until a supported payment integration is connected and the transaction is verified.
- The bot is configured for VM deployment because Telegram long polling needs a continuously running process.

## Product

- `/start` and `/help` show the book and its 490 ETB price.
- The purchase button explains that payment is not enabled and tells customers not to pay.

## User preferences

None stated.

## Gotchas

- Checkout and PDF fulfillment are not implemented; the original book PDF was not included with the source code.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
