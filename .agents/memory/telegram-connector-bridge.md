---
name: Telegram connector bridge
description: Why the Telegram bot uses a Node SDK bridge from Python.
---

The Replit-managed Telegram connector is available through the installed
`@replit/connectors-sdk` Node package, while the documented Python package was
not resolvable from the current package registry. The bot therefore keeps its
business logic in Python and sends newline-delimited requests to a small
Node process that calls `connectors.proxy("telegram", ...)`.

**Why:** This preserves the managed connector's authentication and avoids
putting a bot token in source code, without changing the requested Python bot.

**How to apply:** Keep Telegram API calls behind the bridge; do not replace it
with a raw Bot API token unless the integration setup and package availability
are intentionally changed.