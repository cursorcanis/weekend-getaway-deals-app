"""SerpApi Google Hotels adapter implementation."""

from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

from src.core.models import (
    BoardType,
    Deal,
    Destination,
    PartyComposition,
    PriceBreakdown,
    RoomOffer,
    StayRequest,
)
from src.sources.base import BaseDealSource, DealSourceException

logger = logging.getLogger(__name__)

SPA_KEYWORDS = ("spa", "wellness", "terme", "termale", "thermal", "benessere")
BREAKFAST_KEYWORDS = ("breakfast", "colazione")
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class SerpApiGoogleHotelsSource(BaseDealSource):
    """
    Adapter for querying Google Hotels via SerpApi.
    Aggregates multi-OTA rates for the configured family party.

    Every search costs paid quota, so responses are cached on disk (when
    `cache_dir` is set), calls are throttled to `rate_limit_rps`, and transient
    failures (429/5xx/network) are retried with exponential backoff and jitter.
    """

    BASE_URL = "https://serpapi.com/search"

    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limit_rps: float = 1.0,
        http_client: Optional[httpx.AsyncClient] = None,
        hotel_class: Optional[str] = None,
        amenities: Optional[str] = None,
        max_retries: int = 3,
        cache_dir: Optional[Path] = None,
        cache_ttl_hours: float = 12.0,
        tax_exempt_under_age: int = 14,
    ) -> None:
        super().__init__(name="serpapi_google_hotels", rate_limit_rps=rate_limit_rps)
        self.api_key = api_key or os.getenv("SERPAPI_API_KEY", "")
        self._external_client = http_client
        # Optional server-side filters. Off by default: the app looks for plain
        # hotel deals as well as spa hotels, so don't drop hotels without a spa.
        self.hotel_class = hotel_class
        self.amenities = amenities
        self.max_retries = max_retries
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl_seconds = cache_ttl_hours * 3600
        self.tax_exempt_under_age = tax_exempt_under_age
        self._throttle_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._external_client:
            return self._external_client
        return httpx.AsyncClient(timeout=30.0)

    async def health_check(self) -> bool:
        """Verify presence of API key."""
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def _estimate_tourist_tax_eur(
        self,
        star_rating: Optional[float],
        nights: int,
        party: PartyComposition,
    ) -> float:
        """
        Rough estimate of the municipal tourist tax (tassa di soggiorno).

        Rates vary by comune; this uses typical per-person/night bands by star
        rating. Children under `tax_exempt_under_age` are assumed exempt (most
        comuni exempt under-10s to under-14s), so a 15-year-old pays.
        """
        stars = int(star_rating) if star_rating else 3
        if stars >= 5:
            rate_per_person = 4.50
        elif stars == 4:
            rate_per_person = 3.00
        else:
            rate_per_person = 2.00

        taxable_persons = party.adults + sum(
            1 for age in party.children_ages if age >= self.tax_exempt_under_age
        )
        return round(nights * taxable_persons * rate_per_person, 2)

    def _parse_star_rating(self, hotel_class: Optional[str]) -> Optional[float]:
        if not hotel_class:
            return None
        match = re.search(r"(\d+(\.\d+)?)", str(hotel_class))
        return float(match.group(1)) if match else None

    def _parse_discount_percent(self, deal_description: Optional[str]) -> Optional[float]:
        """Parse Google's "18% less than usual" style deal description."""
        if not deal_description:
            return None
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", deal_description)
        if not match:
            return None
        pct = float(match.group(1).replace(",", "."))
        return pct if 0 < pct < 100 else None

    def _generate_deal_id(self, property_id: str, stay: StayRequest) -> str:
        # Price is deliberately NOT part of the identity: the same room on the
        # same dates must keep one id so price drops can be detected.
        raw_key = f"{self.name}:{property_id}:{stay.check_in}:{stay.check_out}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

    def _booking_url(self, prop: Dict[str, Any]) -> Optional[str]:
        if prop.get("link"):
            return prop["link"]
        for offer in prop.get("prices", []) or []:
            if offer.get("link"):
                return offer["link"]
        return None

    def _normalize_deal(
        self,
        prop: Dict[str, Any],
        destination: Destination,
        stay: StayRequest,
    ) -> Optional[Deal]:
        """Normalize a raw SerpApi Google Hotels property item into a Deal object."""
        try:
            name = prop.get("name")
            if not name:
                return None

            # Price extraction (SerpApi "lowest" includes taxes and fees)
            total_rate_obj = prop.get("total_rate") or {}
            rate_per_night_obj = prop.get("rate_per_night") or {}

            total_eur = total_rate_obj.get("extracted_lowest")
            price_per_night_eur = rate_per_night_obj.get("extracted_lowest")

            if not total_eur and price_per_night_eur:
                total_eur = price_per_night_eur * stay.nights
            elif total_eur and not price_per_night_eur:
                price_per_night_eur = round(total_eur / stay.nights, 2)

            if not total_eur or total_eur <= 0:
                return None

            # Star rating and reviews
            star_rating = self._parse_star_rating(prop.get("hotel_class"))
            raw_rating = prop.get("overall_rating")
            user_review_score = round(float(raw_rating) * 2.0, 1) if raw_rating else None
            review_count = prop.get("reviews")

            # Amenities: only what the property itself lists, never inferred
            # from the destination being a terme town.
            amenities = [str(a).lower() for a in prop.get("amenities", []) or []]
            board = (
                BoardType.BREAKFAST
                if any(k in a for a in amenities for k in BREAKFAST_KEYWORDS)
                else BoardType.ROOM_ONLY
            )
            has_spa_amenity = any(k in a for a in amenities for k in SPA_KEYWORDS)

            # Spa admission for the youngest child (destination-level policy)
            youngest = min(stay.party.children_ages, default=99)
            child_compliant = not (
                has_spa_amenity
                and destination.minimum_child_age_spa is not None
                and destination.minimum_child_age_spa > youngest
            )

            property_id = (
                prop.get("property_token")
                or prop.get("hotel_id")
                or hashlib.md5(name.encode("utf-8")).hexdigest()[:12]
            )

            discount_pct = self._parse_discount_percent(prop.get("deal_description"))
            original_price = (
                round(float(total_eur) / (1 - discount_pct / 100), 2) if discount_pct else None
            )

            price = PriceBreakdown(
                total_eur=float(total_eur),
                price_per_night_eur=float(price_per_night_eur),
                taxes_included=True,
                estimated_tourist_tax_eur=self._estimate_tourist_tax_eur(
                    star_rating, stay.nights, stay.party
                ),
                original_price_eur=original_price,
            )

            # Google Hotels' list view does not say which room(s) the price is
            # for, so room name/count/capacity stay unknown (None) rather than
            # being presented as a confirmed family room.
            room_offer = RoomOffer(
                board=board,
                has_spa_amenity=has_spa_amenity,
                terme_included=None,
                terme_child_policy_compliant=child_compliant,
            )

            return Deal(
                id=self._generate_deal_id(property_id, stay),
                source_id=self.name,
                property_id=property_id,
                property_name=name,
                star_rating=star_rating,
                user_review_score=user_review_score,
                review_count=review_count,
                destination_id=destination.id,
                stay_request=stay,
                room_offer=room_offer,
                price=price,
                booking_url=self._booking_url(prop),
                score=0.0,
            )
        except Exception as exc:
            logger.warning("Error normalizing SerpApi property %s: %s", prop.get("name"), exc)
            return None

    def _build_params(self, destination: Destination, stay: StayRequest) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "engine": "google_hotels",
            "q": f"{destination.name} hotels",
            "check_in_date": stay.check_in.isoformat(),
            "check_out_date": stay.check_out.isoformat(),
            "adults": stay.party.adults,
            "children": len(stay.party.children_ages),
            "children_ages": ",".join(str(a) for a in stay.party.children_ages),
            "gl": "it",
            "hl": "it",
            "currency": "EUR",
        }
        if self.hotel_class:
            params["hotel_class"] = self.hotel_class
        if self.amenities:
            params["amenities"] = self.amenities
        return params

    def _cache_path(self, params: Dict[str, Any]) -> Optional[Path]:
        if not self.cache_dir:
            return None
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, path: Optional[Path]) -> Optional[Dict[str, Any]]:
        if not path or not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.cache_ttl_seconds:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_cache(self, path: Optional[Path], data: Dict[str, Any]) -> None:
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write SerpApi cache %s: %s", path, exc)

    async def _throttle(self) -> None:
        if self.rate_limit_rps <= 0:
            return
        async with self._throttle_lock:
            wait = self._last_request_at + 1.0 / self.rate_limit_rps - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def _fetch(self, params: Dict[str, Any]) -> Dict[str, Any]:
        client = await self._get_client()
        try:
            for attempt in range(self.max_retries + 1):
                await self._throttle()
                try:
                    response = await client.get(
                        self.BASE_URL, params={**params, "api_key": self.api_key}
                    )
                    if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                        raise httpx.HTTPStatusError(
                            "retryable", request=response.request, response=response
                        )
                    response.raise_for_status()
                    data = response.json()
                    if data.get("error"):
                        raise DealSourceException(f"SerpApi error: {data['error']}")
                    return data
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status not in RETRYABLE_STATUS or attempt >= self.max_retries:
                        raise DealSourceException(f"SerpApi HTTP error {status}") from exc
                except httpx.RequestError as exc:
                    if attempt >= self.max_retries:
                        # Never include the request URL: it carries the API key.
                        raise DealSourceException(
                            f"SerpApi connection failure: {type(exc).__name__}"
                        ) from exc
                delay = (2 ** attempt) + random.uniform(0, 1)
                logger.info("SerpApi transient failure, retrying in %.1fs", delay)
                await asyncio.sleep(delay)
            raise DealSourceException("SerpApi retries exhausted")
        finally:
            if not self._external_client:
                await client.aclose()

    async def search(
        self,
        destination: Destination,
        stay: StayRequest,
    ) -> List[Deal]:
        """
        Query SerpApi for hotels in the destination matching occupancy and dates.
        """
        if not self.api_key:
            raise DealSourceException("SERPAPI_API_KEY is not configured.")

        params = self._build_params(destination, stay)
        cache_path = self._cache_path(params)
        data = self._read_cache(cache_path)
        if data is None:
            data = await self._fetch(params)
            self._write_cache(cache_path, data)

        deals: List[Deal] = []
        for prop in data.get("properties", []) or []:
            deal = self._normalize_deal(prop, destination, stay)
            if deal:
                deals.append(deal)

        return deals
