from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import PropertyListing


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    """SQLite persistence for listings and private lead routing."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None
        )
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self.lock, self.connection:
            self.connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS listings (
                    id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL UNIQUE,
                    source_platform TEXT NOT NULL,
                    title TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    workgroup_message_id INTEGER,
                    public_message_id INTEGER,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    listing_id TEXT NOT NULL REFERENCES listings(id),
                    telegram_user_id INTEGER,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN ('new', 'claimed')),
                    assigned_realtor_id INTEGER,
                    assigned_realtor_username TEXT,
                    workgroup_message_id INTEGER,
                    created_at TEXT NOT NULL,
                    assigned_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_leads_status
                    ON leads(status);
                CREATE INDEX IF NOT EXISTS idx_leads_listing
                    ON leads(listing_id);
                """
            )

    def get_listing_by_url(self, source_url: str) -> sqlite3.Row | None:
        with self.lock:
            return self.connection.execute(
                "SELECT * FROM listings WHERE source_url = ?", (source_url,)
            ).fetchone()

    def get_listing(self, listing_id: str) -> sqlite3.Row | None:
        with self.lock:
            return self.connection.execute(
                "SELECT * FROM listings WHERE id = ?", (listing_id,)
            ).fetchone()

    def save_listing(self, listing: PropertyListing) -> str:
        listing_id = uuid.uuid4().hex[:16]
        payload = json.dumps(listing.as_dict(), ensure_ascii=False)
        with self.lock, self.connection:
            existing = self.connection.execute(
                "SELECT id FROM listings WHERE source_url = ?", (listing.source_url,)
            ).fetchone()
            if existing:
                return str(existing["id"])
            self.connection.execute(
                """
                INSERT INTO listings
                    (id, source_url, source_platform, title, data_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    listing_id,
                    listing.source_url,
                    listing.source_platform,
                    listing.title,
                    payload,
                    _now(),
                ),
            )
        return listing_id

    def update_listing_data(self, listing_id: str, listing: PropertyListing) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE listings SET data_json = ?, title = ? WHERE id = ?",
                (
                    json.dumps(listing.as_dict(), ensure_ascii=False),
                    listing.title,
                    listing_id,
                ),
            )

    def update_listing_message_ids(
        self,
        listing_id: str,
        workgroup_message_id: int | None,
        public_message_id: int | None,
    ) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                """
                UPDATE listings
                SET workgroup_message_id = COALESCE(?, workgroup_message_id),
                    public_message_id = COALESCE(?, public_message_id)
                WHERE id = ?
                """,
                (workgroup_message_id, public_message_id, listing_id),
            )

    def create_lead(
        self,
        listing_id: str,
        telegram_user_id: int | None,
        username: str | None,
        full_name: str,
        phone: str,
    ) -> str:
        lead_id = uuid.uuid4().hex[:16]
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO leads
                    (id, listing_id, telegram_user_id, username, full_name, phone, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_id,
                    listing_id,
                    telegram_user_id,
                    username,
                    full_name,
                    phone,
                    _now(),
                ),
            )
        return lead_id

    def set_lead_workgroup_message(self, lead_id: str, message_id: int) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE leads SET workgroup_message_id = ? WHERE id = ?",
                (message_id, lead_id),
            )

    def get_lead(self, lead_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT leads.*, listings.source_url, listings.title
                FROM leads
                JOIN listings ON listings.id = leads.listing_id
                WHERE leads.id = ?
                """,
                (lead_id,),
            ).fetchone()
        return dict(row) if row else None

    def claim_lead(
        self, lead_id: str, realtor_id: int, realtor_username: str
    ) -> dict[str, Any] | None:
        """Claim exactly once; the SQL condition is the race-condition guard."""
        with self.lock, self.connection:
            cursor = self.connection.execute(
                """
                UPDATE leads
                SET status = 'claimed',
                    assigned_realtor_id = ?,
                    assigned_realtor_username = ?,
                    assigned_at = ?
                WHERE id = ? AND status = 'new'
                """,
                (realtor_id, realtor_username, _now(), lead_id),
            )
            if cursor.rowcount != 1:
                return None
        return self.get_lead(lead_id)