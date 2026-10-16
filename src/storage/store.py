"""SQLite store: every observed deal, its price history, and which alerts were sent."""

from __future__ import annotations
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

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
CREATE TABLE IF NOT EXISTS offers (
    page_id    TEXT NOT NULL,
    title_key  TEXT NOT NULL,
    title      TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    alerted_at TEXT,
    PRIMARY KEY (page_id, title_key)
);
CREATE TABLE IF NOT EXISTS transit_checks (
    destination_id TEXT NOT NULL,
    travel_date    TEXT NOT NULL,
    checked_at     TEXT NOT NULL,
    minutes        INTEGER,
    PRIMARY KEY (destination_id, travel_date)
);
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

    def upcoming_deals(self, today: date, seen_since: datetime) -> List[Tuple[Deal, datetime, float]]:
        """(deal, last_seen, lowest_price_eur) for stays from today on, seen since seen_since."""
        rows = self._conn.execute(
            "SELECT payload, last_seen, lowest_price_eur FROM deals "
            "WHERE check_in >= ? AND last_seen >= ? ORDER BY check_in",
            (today.isoformat(), seen_since.isoformat()),
        )
        return [(Deal.model_validate_json(p), datetime.fromisoformat(s), low) for p, s, low in rows]

    def recent_offers(self, limit: int = 50) -> List[Tuple[str, str, str, str]]:
        """(page_id, title, first_seen, last_seen) of terme packages, newest first."""
        return [tuple(r) for r in self._conn.execute(
            "SELECT page_id, title, first_seen, last_seen FROM offers "
            "ORDER BY first_seen DESC, rowid DESC LIMIT ?", (limit,))]

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

    def delete_meta(self, key: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM meta WHERE key = ?", (key,))

    # --- terme offer pages ---------------------------------------------------

    def record_offers(self, page_id: str, offers: Sequence[Tuple[str, str]],
                      now: Optional[datetime] = None) -> None:
        """offers: (title_key, title) pairs currently listed on the page."""
        ts = (now or _now()).isoformat()
        with self._conn:
            for key, title in offers:
                self._conn.execute(
                    """
                    INSERT INTO offers (page_id, title_key, title, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (page_id, title_key) DO UPDATE SET
                        last_seen = excluded.last_seen, title = excluded.title
                    """,
                    (page_id, key, title, ts, ts),
                )

    def unalerted_offers(self, page_ids: Sequence[str]) -> List[Tuple[str, str]]:
        """(page_id, title) of offers on these pages never alerted, oldest first."""
        if not page_ids:
            return []
        marks = ",".join("?" * len(page_ids))
        return [tuple(r) for r in self._conn.execute(
            f"SELECT page_id, title FROM offers WHERE alerted_at IS NULL AND page_id IN ({marks}) "
            "ORDER BY first_seen, rowid", list(page_ids))]

    def mark_offers_alerted(self, offers: Iterable[Tuple[str, str]],
                            now: Optional[datetime] = None) -> None:
        """offers: (page_id, title_key) pairs."""
        ts = (now or _now()).isoformat()
        with self._conn:
            self._conn.executemany(
                "UPDATE offers SET alerted_at = ? WHERE page_id = ? AND title_key = ?",
                [(ts, pid, key) for pid, key in offers],
            )

    # --- live transit checks -------------------------------------------------

    def cached_transit_minutes(self, destination_id: str, travel_date: date, max_age_days: int,
                               now: Optional[datetime] = None) -> Tuple[bool, Optional[int]]:
        """(found, minutes). minutes None means the check found no train/bus route."""
        row = self._conn.execute(
            "SELECT checked_at, minutes FROM transit_checks WHERE destination_id = ? AND travel_date = ?",
            (destination_id, travel_date.isoformat()),
        ).fetchone()
        if not row:
            return False, None
        if (now or _now()) - datetime.fromisoformat(row[0]) > timedelta(days=max_age_days):
            return False, None
        return True, row[1]

    def save_transit_minutes(self, destination_id: str, travel_date: date, minutes: Optional[int],
                             now: Optional[datetime] = None) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO transit_checks (destination_id, travel_date, checked_at, minutes)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (destination_id, travel_date) DO UPDATE SET
                    checked_at = excluded.checked_at, minutes = excluded.minutes
                """,
                (destination_id, travel_date.isoformat(), (now or _now()).isoformat(), minutes),
            )
