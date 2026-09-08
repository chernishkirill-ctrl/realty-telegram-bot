from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from typing import Any
from urllib.parse import quote

from .config import Settings
from .models import PropertyListing
from .parser import parse_listing
from .storage import Storage
from .telegram import TelegramClient, TelegramError
from .telegraph import TelegraphClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("realty-bot")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()-]{7,22}$")


def _clip(value: str, limit: int) -> str:
    value = value.strip()
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _html(value: Any) -> str:
    return html.escape(_clip(str(value), 4000), quote=True)


def _claim_keyboard(lead_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": "📥 Взять заявку", "callback_data": f"claim:{lead_id}"}
        ]]
    }


def _public_url_keyboard(webapp_url: str, listing_id: str) -> dict[str, Any]:
    url = f"{webapp_url.rstrip('/')}/webapp?listing_id={quote(listing_id)}"
    return {
        "inline_keyboard": [[
            {"text": "📅 Записаться на просмотр", "url": url}
        ]]
    }


def _public_web_app_keyboard(webapp_url: str, listing_id: str) -> dict[str, Any]:
    """Kept separate so the Telegram channel limitation is explicit."""
    url = f"{webapp_url.rstrip('/')}/webapp?listing_id={quote(listing_id)}"
    return {
        "inline_keyboard": [[
            {
                "text": "📅 Записаться на просмотр",
                "web_app": {"url": url},
            }
        ]]
    }


def _public_text(listing: PropertyListing, contacts: str) -> str:
    characteristics = "\n".join(
        f"• {_html(key)}: {_html(value)}"
        for key, value in listing.characteristics.items()
    )
    blocks = [
        f"🏠 <b>{_html(listing.title)}</b>",
        f"📍 {_html(listing.location)}" if listing.location else "",
        f"💰 <b>{_html(listing.price)}</b>" if listing.price else "",
        characteristics,
        "",
        _html(listing.description),
        "",
        (
            f"🔗 <a href=\"{_html(listing.telegraph_url)}\">"
            "Открыть полное описание и фото</a>"
            if listing.telegraph_url
            else ""
        ),
        "",
        f"📞 {_html(contacts)}",
    ]
    return "\n".join(block for block in blocks if block)


def _private_listing_text(listing: PropertyListing, listing_id: str) -> str:
    characteristics = "\n".join(
        f"• {_html(key)}: {_html(value)}"
        for key, value in listing.characteristics.items()
    ) or "—"
    contacts = ", ".join(listing.contacts) or "Не найдены"
    raw_excerpt = _clip(
        json.dumps(listing.raw_data, ensure_ascii=False, indent=2), 2100
    )
    return _clip(
        "\n".join(
            [
                "🧾 <b>Новый объект для обработки</b>",
                f"<b>{_html(listing.title)}</b>",
                f"ID: <code>{_html(listing_id)}</code>",
                (
                    f"Источник: <a href=\"{_html(listing.source_url)}\">"
                    f"{_html(listing.source_platform)}</a>"
                ),
                f"Цена: {_html(listing.price) or '—'}",
                f"Локация: {_html(listing.location) or '—'}",
                (
                    f"Telegraph: <a href=\"{_html(listing.telegraph_url)}\">"
                    "открыть страницу</a>"
                    if listing.telegraph_url
                    else ""
                ),
                "",
                "<b>Характеристики</b>",
                characteristics,
                "",
                f"<b>Контакты из источника:</b> {_html(contacts)}",
                "",
                f"<b>Описание</b>\n{_html(listing.description)}",
                "",
                "<b>Raw extract</b>",
                f"<pre>{_html(raw_excerpt)}</pre>",
            ]
        ),
        4090,
    )


def _new_lead_text(lead: dict[str, Any]) -> str:
    return "\n".join(
        [
            "🔥 <b>Новая заявка на просмотр</b>",
            f"Объект: <b>{_html(lead['title'])}</b>",
            f"ID объекта: <code>{_html(lead['listing_id'])}</code>",
            "",
            "Имя и номер клиента скрыты до закрепления заявки.",
            "Нажмите «Взять заявку», чтобы получить контакты.",
        ]
    )


def _claimed_lead_text(lead: dict[str, Any]) -> str:
    realtor = lead.get("assigned_realtor_username") or str(
        lead.get("assigned_realtor_id", "")
    )
    realtor_label = f"@{realtor}" if not str(realtor).startswith("@") else str(realtor)
    return (
        f"✅ Заявку перехватил риелтор {_html(realtor_label)}. "
        "Данные отправлены ему."
    )


def _realtor_username(user: dict[str, Any]) -> str:
    return str(user.get("username") or user.get("first_name") or user.get("id"))


def _full_name(user: dict[str, Any]) -> str:
    return " ".join(
        part for part in [user.get("first_name"), user.get("last_name")] if part
    ) or "Клиент"


class RealtyBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = Storage(settings.database_path)
        self.telegram = TelegramClient()
        self.telegraph = TelegraphClient(settings)
        self.bot_username = ""
        self.tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        await self.telegram.start()
        identity = await self.telegram.call("getMe")
        self.bot_username = identity.get("username", "")
        await self.telegram.call("deleteWebhook", {"drop_pending_updates": False})
        if self.settings.owner_telegram_id is None:
            logger.warning(
                "MY_TELEGRAM_ID is not configured; all listing-creation messages "
                "will be ignored"
            )
        if not self.settings.webapp_url.startswith("https://"):
            logger.warning(
                "WEBAPP_URL is not HTTPS; Telegram clients may refuse the booking form"
            )
        logger.info(
            "Bot @%s is ready; workgroup=%s public_channel=%s",
            self.bot_username,
            self.settings.workgroup_chat_id,
            self.settings.public_channel_id,
        )

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await self.telegram.close()

    async def poll_forever(self) -> None:
        offset: int | None = None
        while True:
            try:
                updates = await self.telegram.get_updates(offset)
                for update in updates:
                    offset = max(offset or 0, int(update["update_id"]) + 1)
                    task = asyncio.create_task(self.handle_update(update))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Update polling failed; retrying")
                await asyncio.sleep(3)

    async def handle_update(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            await self.handle_callback(update["callback_query"])
            return
        message = update.get("message") or {}
        if message.get("contact") or message.get("text") or message.get("web_app_data"):
            await self.handle_message(message)

    async def handle_message(self, message: dict[str, Any]) -> None:
        """Only the configured owner can create and publish listings."""
        user = message.get("from", {})
        user_id = int(user.get("id", 0))
        if self.settings.owner_telegram_id is None or user_id != self.settings.owner_telegram_id:
            return
        chat = message.get("chat", {})
        if chat.get("type") != "private":
            return
        text = str(message.get("text", "")).strip()
        match = URL_RE.search(text)
        if not match:
            return
        url = match.group(0).rstrip(").,")
        await self.telegram.send_message(user_id, "Ссылка получена. Извлекаю данные объявления…")
        try:
            await self.publish_listing(url)
            await self.telegram.send_message(
                user_id,
                "Готово: объект отправлен в рабочую и публичную группы.",
            )
        except Exception as error:
            logger.exception("Listing processing failed")
            await self.telegram.send_message(
                user_id,
                f"Не удалось обработать ссылку: {_clip(str(error), 500)}",
            )

    async def publish_listing(self, url: str) -> None:
        if not self.settings.webapp_url.startswith("https://"):
            raise RuntimeError(
                "Не настроен WEBAPP_URL. Нужен публичный HTTPS-адрес WebApp."
            )

        existing = self.storage.get_listing_by_url(url)
        if existing:
            listing_id = str(existing["id"])
            listing = PropertyListing(**json.loads(existing["data_json"]))
        else:
            listing = await asyncio.to_thread(parse_listing, url, self.settings)
            listing.telegraph_url = await self.telegraph.create_page(
                listing, self.settings.public_contacts
            )
            listing_id = self.storage.save_listing(listing)

        if not listing.telegraph_url:
            listing.telegraph_url = await self.telegraph.create_page(
                listing, self.settings.public_contacts
            )
            self.storage.update_listing_data(listing_id, listing)

        workgroup = await self.telegram.send_message(
            self.settings.workgroup_chat_id,
            _private_listing_text(listing, listing_id),
        )
        if listing.photos:
            try:
                if len(listing.photos) >= 2:
                    await self.telegram.send_media_group(
                        self.settings.workgroup_chat_id,
                        listing.photos,
                        f"📷 <b>Фото объекта {_html(listing_id)}</b>",
                    )
                else:
                    await self.telegram.send_photo(
                        self.settings.workgroup_chat_id,
                        listing.photos[0],
                        f"📷 <b>Фото объекта {_html(listing_id)}</b>",
                    )
            except TelegramError:
                logger.warning("Could not send internal photos for %s", listing_id)

        public = await self.telegram.send_message(
            self.settings.public_channel_id,
            _public_text(listing, self.settings.public_contacts),
            _public_url_keyboard(self.settings.webapp_url, listing_id),
        )
        self.storage.update_listing_message_ids(
            listing_id, int(workgroup["message_id"]), int(public["message_id"])
        )

    async def submit_web_lead(self, payload: dict[str, Any]) -> dict[str, Any]:
        listing_id = str(payload.get("listing_id", "")).strip()
        full_name = _clip(str(payload.get("full_name", "")).strip(), 200)
        phone = _clip(str(payload.get("phone", "")).strip(), 40)
        username = _clip(str(payload.get("username", "")).strip().lstrip("@"), 64) or None
        user_id_raw = payload.get("telegram_user_id")
        telegram_user_id = int(user_id_raw) if str(user_id_raw).isdigit() else None

        if not listing_id or not self.storage.get_listing(listing_id):
            raise ValueError("Объявление не найдено")
        if len(full_name) < 2:
            raise ValueError("Укажите имя")
        if not PHONE_RE.fullmatch(phone):
            raise ValueError("Укажите корректный номер телефона")

        lead_id = self.storage.create_lead(
            listing_id=listing_id,
            telegram_user_id=telegram_user_id,
            username=username,
            full_name=full_name,
            phone=phone,
        )
        lead = self.storage.get_lead(lead_id)
        if not lead:
            raise RuntimeError("Заявка не сохранилась")

        message = await self.telegram.send_message(
            self.settings.workgroup_chat_id,
            _new_lead_text(lead),
            _claim_keyboard(lead_id),
        )
        self.storage.set_lead_workgroup_message(lead_id, int(message["message_id"]))
        logger.info("New lead %s created for listing %s", lead_id, listing_id)
        return {"ok": True, "lead_id": lead_id}

    async def handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = str(callback["id"])
        data = str(callback.get("data", ""))
        if not data.startswith("claim:"):
            await self.telegram.answer_callback(callback_id)
            return

        callback_chat = (callback.get("message") or {}).get("chat", {})
        if int(callback_chat.get("id", 0)) != self.settings.workgroup_chat_id:
            await self.telegram.answer_callback(
                callback_id, "Эта кнопка действует только в рабочей группе.", show_alert=True
            )
            return

        user = callback.get("from", {})
        user_id = int(user.get("id", 0))
        lead_id = data.removeprefix("claim:")
        lead = self.storage.claim_lead(
            lead_id, user_id, _realtor_username(user)
        )
        if not lead:
            await self.telegram.answer_callback(
                callback_id,
                "Заявка уже перехвачена другим риелтором.",
                show_alert=True,
            )
            return

        workgroup_message_id = lead.get("workgroup_message_id")
        callback_message = callback.get("message", {})
        message_id = workgroup_message_id or callback_message.get("message_id")
        if message_id:
            await self.telegram.edit_message(
                self.settings.workgroup_chat_id,
                int(message_id),
                _claimed_lead_text(lead),
                {},
            )

        username = f"@{lead['username']}" if lead.get("username") else "не указан"
        private_delivery_ok = False
        try:
            await self.telegram.send_message(
                user_id,
                "\n".join(
                    [
                        "✅ <b>Заявка закреплена за вами</b>",
                        f"Имя: <b>{_html(lead['full_name'])}</b>",
                        f"Телефон: <code>{_html(lead['phone'])}</code>",
                        f"Telegram: {_html(username)}",
                        f"Объект: <b>{_html(lead['title'])}</b>",
                        f"Источник: {_html(lead['source_url'])}",
                    ]
                ),
            )
            private_delivery_ok = True
        except TelegramError:
            logger.warning("Could not send private lead details to realtor %s", user_id)

        if private_delivery_ok:
            await self.telegram.answer_callback(
                callback_id, "Заявка закреплена. Полные данные отправлены в личные сообщения."
            )
        else:
            popup = _clip(
                "\n".join(
                    [
                        "Заявка закреплена за вами.",
                        f"Имя: {lead['full_name']}",
                        f"Телефон: {lead['phone']}",
                        f"Telegram: {username}",
                    ]
                ),
                190,
            )
            await self.telegram.answer_callback(callback_id, popup, show_alert=True)


async def run() -> None:
    from .webapp import WebAppServer

    settings = Settings.from_env()
    bot = RealtyBot(settings)
    await bot.start()
    loop = asyncio.get_running_loop()
    webapp = WebAppServer(
        settings.webapp_host,
        settings.webapp_port,
        loop,
        bot.storage.get_listing,
        bot.submit_web_lead,
    )
    webapp.start()
    logger.info("Booking WebApp listening on %s:%s", settings.webapp_host, settings.webapp_port)
    try:
        await bot.poll_forever()
    finally:
        webapp.stop()
        await bot.stop()