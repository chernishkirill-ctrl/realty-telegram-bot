# Realty Telegram Bot

Python Telegram bot for owner-only real-estate listing publication, an in-Telegram
booking WebApp, and private first-come-first-served realtor lead routing.

## Run

- `python main.py` — starts Telegram polling and the WebApp HTTP server.
- `pnpm --filter @workspace/api-server run dev` — unrelated workspace API server.
- `pnpm run typecheck` — workspace TypeScript checks.

## Required configuration

- `MY_TELEGRAM_ID` — only this Telegram user may submit listing URLs.
- `WORKGROUP_CHAT_ID` — private group for technical listing cards and hidden leads.
- `PUBLIC_CHANNEL_ID` — public listing channel.
- `WEBAPP_URL` — public HTTPS origin for the booking form.
- `REALTY_WEBAPP_PORT` — internal Python WebApp port, default `8090`.

`PRIVATE_CHANNEL_ID` is accepted as a compatibility fallback for
`WORKGROUP_CHAT_ID`. The Telegram bot token must continue to come from the
Replit-managed connector, not from source files.

## Architecture

- `main.py` starts `realty_bot.bot.run`.
- `realty_bot/bot.py` owns authorization, parsing, publishing, WebApp lead intake,
  callback claiming, and private realtor notifications.
- `realty_bot/webapp.py` serves the dependency-free HTML booking form and bridges
  form submissions back to the asyncio bot loop.
- `artifacts/api-server/src/app.ts` forwards public WebApp requests from the
  standard HTTPS service port to the Python WebApp port.
- `realty_bot/storage.py` creates `data/leads.db` and performs the atomic
  `status = 'new'` to `status = 'claimed'` transition.
- `telegram_connector.mjs` is the Node bridge for the installed Telegram connector.

## Product rules

- Non-owner messages for listing creation are ignored without a reply.
- Group lead cards never include client name or phone.
- The first successful claim receives the full client data in a private message;
  all later claims are rejected.
- The WebApp closes after submitting the phone form, leaving the user in the
  public channel.

## Known Telegram constraint

Telegram does not allow an inline `web_app` button in a channel post. The public
post therefore uses an HTTPS URL button to the same WebApp. This keeps the form
inside Telegram and avoids a bot-chat redirect while remaining valid for channel
messages.