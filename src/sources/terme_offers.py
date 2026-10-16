"""Watch terme offer listing pages and report package titles not seen before.

These pages carry no family price, so they don't produce Deals: an alert says
"new package at X" with the link, and the family checks the terms themselves.
Rules for fetching come from docs/compliance_phase5.md; see data/terme_offer_pages.yaml.
"""

from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import httpx
import yaml

from src.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_PAGES_PATH = PROJECT_ROOT / "data" / "terme_offer_pages.yaml"
USER_AGENT = "WeekendGetawayDeals/0.5 (personal, non-commercial)"
MIN_SECONDS_BETWEEN_REQUESTS = 2.0
BLOCKING_STATUS = {403, 429}


@dataclass(frozen=True)
class OfferPage:
    id: str
    name: str
    destination_id: str
    url: str
    heading_tag: str
    start_after: str
    stop_at: Optional[str] = None
    exclude: Optional[str] = None


@dataclass(frozen=True)
class Offer:
    page: OfferPage
    title: str

    @property
    def key(self) -> str:
        return title_key(self.title)


def title_key(title: str) -> str:
    return " ".join(title.split()).casefold()


def load_offer_pages(path: Optional[Path] = None) -> List[OfferPage]:
    p = Path(path or DEFAULT_PAGES_PATH)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        raw = (yaml.safe_load(f) or {}).get("pages", []) or []
    return [OfferPage(**entry) for entry in raw]


class _Headings(HTMLParser):
    """Collect (tag, text) for every h1-h6, in document order."""

    TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: List[Tuple[str, str]] = []
        self._tag: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag in self.TAGS and self._tag is None:
            self._tag, self._text = tag, []

    def handle_endtag(self, tag) -> None:
        if tag == self._tag:
            self.headings.append((tag, " ".join("".join(self._text).split())))
            self._tag = None

    def handle_data(self, data) -> None:
        if self._tag:
            self._text.append(data)


def parse_offer_titles(html: str, page: OfferPage) -> List[str]:
    parser = _Headings()
    parser.feed(html)
    titles: List[str] = []
    seen = set()
    started = False
    for tag, text in parser.headings:
        if not started:
            started = bool(re.search(page.start_after, text))
            continue
        if page.stop_at and re.search(page.stop_at, text):
            break
        if tag != page.heading_tag or not text:
            continue
        if page.exclude and re.search(page.exclude, text):
            continue
        if title_key(text) not in seen:
            seen.add(title_key(text))
            titles.append(text)
    return titles


class OfferWatcher:
    """
    Fetch each page (rate-limited, conditional GET, at most every interval_hours),
    record its offer titles in the store, and return the offers not yet alerted.
    """

    def __init__(
        self,
        store,
        client: Optional[httpx.Client] = None,
        interval_hours: float = 12.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False
        )
        self.interval = timedelta(hours=interval_hours)
        self._sleep = sleep
        self._last_request = 0.0

    def _meta(self, page: OfferPage, field: str) -> Optional[str]:
        return self.store.get_meta(f"offers:{page.id}:{field}")

    def _set_meta(self, page: OfferPage, field: str, value: str) -> None:
        self.store.set_meta(f"offers:{page.id}:{field}", value)

    def _due(self, page: OfferPage, now: datetime) -> bool:
        last = self._meta(page, "fetched_at")
        return not last or now - datetime.fromisoformat(last) >= self.interval

    def _throttle(self) -> None:
        wait = self._last_request + MIN_SECONDS_BETWEEN_REQUESTS - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    def check(
        self, pages: List[OfferPage], now: Optional[datetime] = None
    ) -> Tuple[List[Offer], List[str]]:
        now = now or datetime.now(timezone.utc)
        errors: List[str] = []
        for page in pages:
            blocked = self._meta(page, "blocked")
            if blocked:
                errors.append(f"{page.name}: skipped, the site refused us ({blocked}); "
                              f"run --offers-unblock {page.id} after checking by hand")
                continue
            if not self._due(page, now):
                continue
            try:
                error = self._fetch_and_record(page, now)
            except httpx.HTTPError as exc:
                error = f"request failed ({type(exc).__name__})"
            if error:
                errors.append(f"{page.name}: {error}")
        pending = self.store.unalerted_offers([p.id for p in pages])
        by_id = {p.id: p for p in pages}
        return [Offer(by_id[pid], title) for pid, title in pending], errors

    def _fetch_and_record(self, page: OfferPage, now: datetime) -> Optional[str]:
        headers = {"User-Agent": USER_AGENT}
        etag, modified = self._meta(page, "etag"), self._meta(page, "last_modified")
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        self._throttle()
        resp = self.client.get(page.url, headers=headers)
        self._set_meta(page, "fetched_at", now.isoformat())

        if resp.status_code in BLOCKING_STATUS:
            # Never work around blocking: stop polling this page until a human looks.
            self._set_meta(page, "blocked", f"HTTP {resp.status_code} on {now:%Y-%m-%d}")
            return f"HTTP {resp.status_code}; polling stopped"
        if resp.status_code == 304:
            return None
        if resp.status_code != 200:
            return f"HTTP {resp.status_code}"

        titles = parse_offer_titles(resp.text, page)
        if not titles:
            # Don't treat it as "all offers gone": the page layout probably changed.
            return "no offers found; the page layout may have changed"
        self._set_meta(page, "etag", resp.headers.get("ETag", ""))
        self._set_meta(page, "last_modified", resp.headers.get("Last-Modified", ""))
        self.store.record_offers(page.id, [(title_key(t), t) for t in titles], now)
        return None
