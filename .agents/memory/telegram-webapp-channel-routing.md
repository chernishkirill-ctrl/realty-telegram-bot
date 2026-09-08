---
name: Telegram channel WebApp routing
description: Telegram channel-button limitations and the workspace routing needed for the booking form.
---

Telegram Bot API does not allow an inline `web_app` button in channel messages; that field is restricted to private chats. For channel UX, use an HTTPS URL button to a Mini WebApp, then close the WebApp after the form POST so the user remains in Telegram.

**Why:** Sending `web_app` directly in a channel makes publication fail or produces a non-functional button. The registered API artifact also owns the public `/api` route, while the Python bot can run its WebApp on a separate internal port.

**How to apply:** Keep the public URL under the artifact's `/api` prefix, proxy `/api/webapp` to Python `/webapp`, and proxy `/api/leads` to Python `/api/leads` before the Express JSON parser.