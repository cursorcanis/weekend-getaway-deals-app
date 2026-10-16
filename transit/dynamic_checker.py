"""Live check of the Friday train/bus journey from Santa Margherita Ligure before an alert.

Uses the Google Routes API in TRANSIT mode (docs/compliance_phase5.md (b) 5b):
free monthly tier, results cached at most 30 days, Google credited in alerts.
Trenitalia, Viaggiatreno and Italo are never called automatically.
"""

from __future__ import annotations
import logging
import re
from datetime import date, timedelta
from typing import Optional

import httpx

from src.core.models import Destination

logger = logging.getLogger(__name__)

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


class TransitCheckError(Exception):
    """The Routes API call failed. Messages never contain the API key."""


def _last_sunday(year: int, month: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def italy_utc_offset(day: date) -> str:
    """CET/CEST without needing tzdata (missing on Windows): summer time runs from the
    last Sunday of March to the last Sunday of October."""
    summer = _last_sunday(day.year, 3) <= day < _last_sunday(day.year, 10)
    return "+02:00" if summer else "+01:00"


def _seconds(duration: str) -> Optional[int]:
    m = re.fullmatch(r"(\d+)(?:\.\d+)?s", duration or "")
    return int(m.group(1)) if m else None


class TransitChecker:
    def __init__(
        self,
        api_key: str,
        store,
        origin_lat: float,
        origin_lon: float,
        departure_time: str = "14:00",
        cache_days: int = 30,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._api_key = api_key
        self.store = store
        self.origin = {"latitude": origin_lat, "longitude": origin_lon}
        self.departure_time = departure_time
        self.cache_days = min(cache_days, 30)
        self.client = client or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    def fastest_minutes(self, destination: Destination, travel_date: date) -> Optional[int]:
        """
        Fastest train/bus journey in minutes leaving after departure_time on travel_date,
        or None when Google finds no transit route (e.g. timetables not published yet).
        """
        found, minutes = self.store.cached_transit_minutes(
            destination.id, travel_date, self.cache_days)
        if found:
            return minutes
        minutes = self._query(destination, travel_date)
        self.store.save_transit_minutes(destination.id, travel_date, minutes)
        return minutes

    def _query(self, destination: Destination, travel_date: date) -> Optional[int]:
        if destination.latitude is None or destination.longitude is None:
            raise TransitCheckError(f"no coordinates for {destination.id}")
        departure = (f"{travel_date.isoformat()}T{self.departure_time}:00"
                     f"{italy_utc_offset(travel_date)}")
        body = {
            "origin": {"location": {"latLng": self.origin}},
            "destination": {"location": {"latLng": {
                "latitude": destination.latitude, "longitude": destination.longitude}}},
            "travelMode": "TRANSIT",
            "departureTime": departure,
            "computeAlternativeRoutes": True,
        }
        headers = {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": "routes.duration",
        }
        try:
            resp = self.client.post(ROUTES_URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise TransitCheckError(f"Routes API request failed ({type(exc).__name__})") from None
        if resp.status_code != 200:
            try:
                detail = str(resp.json().get("error", {}).get("status", ""))
            except ValueError:
                detail = ""
            raise TransitCheckError(f"Routes API returned HTTP {resp.status_code} {detail}".strip())
        durations = [_seconds(r.get("duration", "")) for r in resp.json().get("routes", []) or []]
        durations = [d for d in durations if d]
        return round(min(durations) / 60) if durations else None


def format_minutes(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"
