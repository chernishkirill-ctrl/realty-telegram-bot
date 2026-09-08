from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


MY_TELEGRAM_ID = "ВАШ_TELEGRAM_ID"
WORKGROUP_ID_PLACEHOLDER = "ID_РАБОЧЕЙ_ГРУППЫ"


@dataclass(frozen=True)
class Settings:
    owner_telegram_id: int | None = None
    workgroup_chat_id: int = -1004428877093
    public_channel_id: int = -1003889243376
    public_contacts: str = "Зв’яжіться з ріелтором у Telegram"
    database_path: Path = Path("data/leads.db")
    telegraph_token_path: Path = Path("data/telegraph_access_token.txt")
    telegraph_short_name: str = "RealtyBot"
    telegraph_author_name: str = "Realty"
    webapp_url: str = ""
    webapp_host: str = "0.0.0.0"
    webapp_port: int = 8090
    request_timeout: float = 25.0
    user_agent: str = (
        "Mozilla/5.0 (compatible; RealtyBot/1.0; +https://replit.com)"
    )

    @classmethod
    def from_env(cls) -> "Settings":
        owner_raw = os.getenv("MY_TELEGRAM_ID", MY_TELEGRAM_ID).strip()
        owner_id = int(owner_raw) if owner_raw.isdigit() else None

        workgroup_raw = os.getenv("WORKGROUP_CHAT_ID", "").strip()
        if not workgroup_raw:
            workgroup_raw = os.getenv("PRIVATE_CHANNEL_ID", str(cls.workgroup_chat_id))
        workgroup_id = (
            int(workgroup_raw)
            if workgroup_raw.lstrip("-").isdigit()
            else cls.workgroup_chat_id
        )

        public_raw = os.getenv("PUBLIC_CHANNEL_ID", str(cls.public_channel_id))
        public_id = (
            int(public_raw)
            if public_raw.lstrip("-").isdigit()
            else cls.public_channel_id
        )

        webapp_url = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
        if not webapp_url:
            dev_domain = os.getenv("REPLIT_DEV_DOMAIN", "").strip()
            if dev_domain:
                webapp_url = f"https://{dev_domain}/api"

        return cls(
            owner_telegram_id=owner_id,
            workgroup_chat_id=workgroup_id,
            public_channel_id=public_id,
            public_contacts=os.getenv("PUBLIC_REALTOR_CONTACTS", cls.public_contacts),
            database_path=Path(
                os.getenv("REALTY_DATABASE_PATH", str(cls.database_path))
            ),
            telegraph_token_path=Path(
                os.getenv(
                    "TELEGRAPH_TOKEN_PATH", str(cls.telegraph_token_path)
                )
            ),
            telegraph_short_name=os.getenv(
                "TELEGRAPH_SHORT_NAME", cls.telegraph_short_name
            ),
            telegraph_author_name=os.getenv(
                "TELEGRAPH_AUTHOR_NAME", cls.telegraph_author_name
            ),
            webapp_url=webapp_url,
            webapp_host=os.getenv("WEBAPP_HOST", cls.webapp_host),
            webapp_port=int(os.getenv("REALTY_WEBAPP_PORT", "8090")),
            request_timeout=float(os.getenv("PARSER_TIMEOUT_SECONDS", "25")),
        )