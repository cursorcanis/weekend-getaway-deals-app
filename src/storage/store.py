"""SQLite store: every observed deal, its price history, and which alerts were sent."""

from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Union

from src.core.models import Deal

SCHEMA = """
CREATE TABLE IF NOT EXISTS deals (
    deal_id         TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    property_name   TEXT NOT NULL,
    destination_id  TEXT NOT NULL,
    check_in        TEXT NOT NULL,
    check_out       TEXT NOT NULL,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    last_price_eur  REAL NOT NULL,
    lowest_price_eur REAL NOT NULL,
    payload         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_history (
    deal_id   TEXT NOT NULL,
    seen_at   TEXT NOT NULL,
    total_eur REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_price_history_deal ON price_history (deal_id, seen_at);
CREATE TABLE IF NOT EXISTS alerts_sent (
    deal_id    TEXT NOT NULL,
    sent_at    TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    total_eur  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_alerts_sent_deal ON alerts_sent (deal_id, sent_at);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DealStore:
    def __init__(self, path: Union[str, Path]):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), timeout=5.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DealStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def record_observations(self, deals: Iterable[Deal], now: Optional[datetime] = None) -> None:
        ts = (now or _now()).isoformat()
        with self._conn:
            for d in deals:
                price = d.price.total_eur
                self._conn.execute(
                    """
                    INSERT INTO deals (deal_id, source_id, property_name, destination_id, check_in,
                                       check_out, first_seen, last_seen, last_price_eur,
                                       lowest_price_eur, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (deal_id) DO UPDATE SET
                        last_seen = excluded.last_seen,
                        last_price_eur = excluded.last_price_eur,
                        lowest_price_eur = MIN(deals.lowest_price_eur, excluded.last_price_eur),
                        payload = excluded.payload
                    """,
                    (d.id, d.source_id, d.property_name, d.destination_id,
                     d.stay_request.check_in.isoformat(), d.stay_request.check_out.isoformat(),
                     ts, ts, price, price, d.model_dump_json()),
                )
                self._conn.execute(
                    "INSERT INTO price_history (deal_id, seen_at, total_eur) VALUES (?, ?, ?)",
                    (d.id, ts, price),
                )

    def last_alerted_price(self, deal_id: str) -> Optional[float]:
        """Price in the most recent alert for this deal, or None if never alerted."""
        row = self._conn.execute(
            "SELECT total_eur FROM alerts_sent WHERE deal_id = ? ORDER BY sent_at DESC, rowid DESC LIMIT 1",
            (deal_id,),
        ).fetchone()
        return row[0] if row else None

    def record_alert(self, deal_id: str, alert_type: str, total_eur: float,
                     now: Optional[datetime] = None) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO alerts_sent (deal_id, sent_at, alert_type, total_eur) VALUES (?, ?, ?, ?)",
                (deal_id, (now or _now()).isoformat(), alert_type, total_eur),
            )

    def price_history(self, deal_id: str) -> list:
        return [r[0] for r in self._conn.execute(
            "SELECT total_eur FROM price_history WHERE deal_id = ? ORDER BY seen_at, rowid", (deal_id,)
        )]

    def get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
