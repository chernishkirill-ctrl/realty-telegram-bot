from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import Settings
from .models import PropertyListing

PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?380[\s()-]*\d{2}|(?:\+?38[\s()-]*)?0\d{2})"
    r"[\s()-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"
)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.images: list[str] = []
        self.text_parts: list[str] = []
        self.json_ld_parts: list[str] = []
        self._script_json = False
        self._script_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key.lower()] = values["content"]
        if tag.lower() == "img":
            for key in ("src", "data-src", "data-original", "data-lazy-src"):
                if values.get(key):
                    self.images.append(values[key])
                    break
        if tag.lower() == "script" and values.get("type") == "application/ld+json":
            self._script_json = True
            self._script_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._script_json:
            self.json_ld_parts.append("".join(self._script_buffer))
            self._script_json = False

    def handle_data(self, data: str) -> None:
        if self._script_json:
            self._script_buffer.append(data)
        else:
            self.text_parts.append(data)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(_clean(item) for item in value if _clean(item))
    if isinstance(value, dict):
        return _clean(value.get("name") or value.get("value") or value.get("text"))
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


def _json_ld(parser: _PageParser) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in parser.json_ld_parts:
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = decoded if isinstance(decoded, list) else [decoded]
        for candidate in candidates:
            if isinstance(candidate, dict) and "@graph" in candidate:
                candidates.extend(candidate["@graph"] or [])
            if isinstance(candidate, dict):
                result.append(candidate)
    return result


def _first_value(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return _clean(value)
    return ""


def _find_json_ld(data: list[dict[str, Any]]) -> dict[str, Any]:
    preferred = (
        "RealEstateListing",
        "Residence",
        "Apartment",
        "House",
        "Product",
        "Offer",
    )
    for item in data:
        item_type = item.get("@type", "")
        types = item_type if isinstance(item_type, list) else [item_type]
        if any(kind in preferred for kind in types):
            return item
    return data[0] if data else {}


def _platform(host: str) -> str:
    host = host.lower()
    if "dom.ria" in host or "domria" in host:
        return "DOM.RIA"
    if "olx" in host:
        return "OLX"
    return host.removeprefix("www.") or "unknown"


def _contacts(text: str) -> list[str]:
    phones = [match.group(0) for match in PHONE_RE.finditer(text)]
    emails = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    return list(dict.fromkeys(_clean(item) for item in [*phones, *emails]))


def _characteristics(item: dict[str, Any], text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    mapping = {
        "numberOfRooms": "Кімнати",
        "floorLevel": "Поверх",
        "floor": "Поверх",
        "numberOfFloors": "Поверховість",
        "floorSize": "Площа",
        "area": "Площа",
        "address": "Адреса",
        "yearBuilt": "Рік побудови",
    }
    for source, label in mapping.items():
        value = _clean(item.get(source))
        if value:
            result[label] = value
    patterns = {
        "Площа": r"(?i)(?:площа|площадь)\s*[:\-]?\s*([\d.,]+\s*(?:м²|м2|кв\.?\s*м))",
        "Кімнати": r"(?i)(?:кімнат|комнат)\s*[:\-]?\s*(\d+)",
        "Поверх": r"(?i)(?:поверх|этаж)\s*[:\-]?\s*(\d+\s*(?:з|из)\s*\d+|\d+)",
    }
    for label, pattern in patterns.items():
        if label not in result:
            match = re.search(pattern, text)
            if match:
                result[label] = _clean(match.group(1))
    return result


def parse_listing(url: str, settings: Settings) -> PropertyListing:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("Нужна корректная ссылка http:// или https:// на объявление.")

    request = Request(
        url,
        headers={
            "User-Agent": settings.user_agent,
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
        },
    )
    with urlopen(request, timeout=settings.request_timeout) as response:
        html = response.read(5_000_000).decode(
            response.headers.get_content_charset() or "utf-8", errors="replace"
        )

    parser = _PageParser()
    parser.feed(html)
    json_ld = _json_ld(parser)
    item = _find_json_ld(json_ld)
    offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
    address = item.get("address")
    location = _clean(address) if address else ""
    title = (
        _first_value(item, "name", "headline")
        or parser.meta.get("og:title", "")
        or parser.meta.get("twitter:title", "")
        or "Об’єкт нерухомості"
    )
    description = (
        _first_value(item, "description")
        or parser.meta.get("og:description", "")
        or parser.meta.get("description", "")
    )
    price = _first_value(offers, "price", "lowPrice") or _first_value(
        item, "price", "priceCurrency"
    )
    currency = _first_value(offers, "priceCurrency")
    if price and currency and currency not in price:
        price = f"{price} {currency}"

    images: list[str] = []
    item_images = item.get("image", [])
    if isinstance(item_images, str):
        item_images = [item_images]
    if isinstance(item_images, list):
        images.extend(_clean(image) for image in item_images)
    images.extend(
        parser.meta[key] for key in ("og:image", "twitter:image") if parser.meta.get(key)
    )
    images.extend(parser.images)
    images = list(
        dict.fromkeys(
            image
            for image in images
            if image.startswith(("http://", "https://")) and not image.endswith(".svg")
        )
    )[:10]

    visible_text = " ".join(parser.text_parts)
    return PropertyListing(
        source_url=url,
        source_platform=_platform(parsed_url.netloc),
        title=title[:300],
        description=description[:3000] or visible_text[:3000],
        price=price,
        location=location,
        characteristics=_characteristics(item, visible_text),
        photos=images,
        contacts=_contacts(f"{visible_text} {description}"),
        raw_data={
            "meta": parser.meta,
            "json_ld": json_ld[:5],
            "html_excerpt": re.sub(r"\s+", " ", html)[:2000],
        },
    )