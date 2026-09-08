"""Complete entry point for the owner-only real-estate Telegram bot."""

import asyncio

from realty_bot.bot import run


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
