from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PropertyListing:
    source_url: str
    source_platform: str
    title: str
    description: str
    price: str = ""
    location: str = ""
    characteristics: dict[str, str] = field(default_factory=dict)
    photos: list[str] = field(default_factory=list)
    contacts: list[str] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)
    telegraph_url: str = ""
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)