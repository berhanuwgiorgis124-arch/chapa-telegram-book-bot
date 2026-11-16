---
name: Python Telegram package collision
description: Prevent the unrelated `telegram` distribution from breaking python-telegram-bot imports.
---

Use `python-telegram-bot` as the sole provider of the `telegram` import namespace. Do not add the separate distribution named `telegram`; both install files into the same namespace, and the unrelated package can overwrite exports used by python-telegram-bot.

**Why:** Installing the similarly named package replaced the Telegram library's import files and broke the bot at runtime.

**How to apply:** After Python dependency changes, verify imports such as `from telegram import InlineKeyboardButton` and run the bot test suite.
