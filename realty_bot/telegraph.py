from __future__ import annotations

import asyncio
import json
import os
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Settings
from .models import PropertyListing


class TelegraphError(RuntimeError):
    pass


class TelegraphClient:
    """Creates public Telegraph pages using the official Telegraph API."""

    endpoint = "https://api.telegra.ph"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _api_call(self, method: str, values: dict[str, str]) -> dict[str, Any]:
        request = Request(
            f"{self.endpoint}/{method}",
            data=urlencode(values).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=self.settings.request_timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise TelegraphError(payload.get("error", "Telegraph API error"))
        return payload["result"]

    def _token(self) -> str:
        from_environment = os.getenv("TELEGRAPH_ACCESS_TOKEN", "").strip()
        if from_environment:
            return from_environment

        token_path = self.settings.telegraph_token_path
        if token_path.exists():
            token = token_path.read_text(encoding="utf-8").strip()
            if token:
                return token

        account = self._api_call(
            "createAccount",
            {
                "short_name": self.settings.telegraph_short_name[:32],
                "author_name": self.settings.telegraph_author_name[:64],
            },
        )
        token = str(account["access_token"])
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token, encoding="utf-8")
        try:
            token_path.chmod(0o600)
        except OSError:
            pass
        return token

    def _page_content(
        self, listing: PropertyListing, public_contacts: str
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [
            {"tag": "h3", "children": [escape(listing.title[:180])]},
        ]
        if listing.price:
            content.append(
                {"tag": "p", "children": [f"Цена: {escape(listing.price)}"]}
            )
        if listing.location:
            content.append(
                {"tag": "p", "children": [f"Локация: {escape(listing.location)}"]}
            )
        if listing.characteristics:
            content.append({"tag": "h4", "children": ["Характеристики"]})
            content.append(
                {
                    "tag": "ul",
                    "children": [
                        {
                            "tag": "li",
                            "children": [f"{escape(key)}: {escape(value)}"],
                        }
                        for key, value in listing.characteristics.items()
                    ],
                }
            )
        if listing.description:
            content.append(
                {"tag": "p", "children": [escape(listing.description[:4000])]}
            )
        for photo in listing.photos[:10]:
            content.append(
                {"tag": "img", "attrs": {"src": photo}}
            )
        content.append(
            {"tag": "p", "children": [f"Контакты: {escape(public_contacts)}"]}
        )
        return content

    def create_page_sync(
        self, listing: PropertyListing, public_contacts: str
    ) -> str:
        result = self._api_call(
            "createPage",
            {
                "access_token": self._token(),
                "title": listing.title[:256] or "Объект недвижимости",
                "content": json.dumps(
                    self._page_content(listing, public_contacts),
                    ensure_ascii=False,
                ),
                "return_content": "false",
            },
        )
        path = result.get("path")
        if not path:
            raise TelegraphError("Telegraph did not return a page path")
        return f"{self.endpoint.replace('api.', '')}/{path}"

    async def create_page(
        self, listing: PropertyListing, public_contacts: str
    ) -> str:
        return await asyncio.to_thread(
            self.create_page_sync, listing, public_contacts
        )