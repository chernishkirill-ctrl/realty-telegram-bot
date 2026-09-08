from __future__ import annotations

import asyncio
import json
from typing import Any


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    """Telegram Bot API client through the Replit-managed connector.

    The Python connector package is not available in the project package index,
    so this small bridge keeps the bot Python-first while using the installed
    official Replit connector SDK for authenticated requests.
    """

    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            "node",
            "telegram_connector.mjs",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

    async def close(self) -> None:
        if self.process and self.process.stdin:
            self.process.stdin.close()
        if self.process:
            await self.process.wait()

    async def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise TelegramError("Telegram connector is not started")
        request = json.dumps({"method": method, "body": payload or {}}) + "\n"
        async with self.lock:
            self.process.stdin.write(request.encode())
            await self.process.stdin.drain()
            line = await self.process.stdout.readline()
        if not line:
            raise TelegramError("Telegram connector stopped unexpectedly")
        response = json.loads(line)
        if not response.get("ok"):
            raise TelegramError(response.get("description", "Telegram API error"))
        return response.get("result")

    async def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": 25, "limit": 100, "allowed_updates": [
            "message", "callback_query"
        ]}
        if offset is not None:
            payload["offset"] = offset
        return await self.call("getUpdates", payload)

    async def send_message(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if "<b>" in text or "<code>" in text or "<a " in text or "<pre>" in text:
            payload["parse_mode"] = "HTML"
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", payload)

    async def send_photo(
        self, chat_id: int, photo: str, caption: str = "",
        reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption:
            payload["caption"] = caption[:1024]
            if "<b>" in caption or "<code>" in caption or "<a " in caption:
                payload["parse_mode"] = "HTML"
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendPhoto", payload)

    async def send_media_group(
        self, chat_id: int, photos: list[str], caption: str = ""
    ) -> list[dict[str, Any]]:
        media: list[dict[str, Any]] = []
        for index, photo in enumerate(photos[:10]):
            item: dict[str, Any] = {"type": "photo", "media": photo}
            if index == 0 and caption:
                item["caption"] = caption[:1024]
                if "<b>" in caption or "<code>" in caption or "<a " in caption:
                    item["parse_mode"] = "HTML"
            media.append(item)
        return await self.call(
            "sendMediaGroup", {"chat_id": chat_id, "media": media}
        )

    async def answer_callback(
        self, query_id: str, text: str = "", show_alert: bool = False
    ) -> None:
        await self.call(
            "answerCallbackQuery",
            {
                "callback_query_id": query_id,
                "text": text,
                "show_alert": show_alert,
            },
        )

    async def edit_message(
        self, chat_id: int, message_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id, "message_id": message_id, "text": text
        }
        if "<b>" in text or "<code>" in text or "<a " in text:
            payload["parse_mode"] = "HTML"
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        await self.call("editMessageText", payload)