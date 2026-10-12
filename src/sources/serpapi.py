"""SerpApi Google Hotels adapter implementation."""

from __future__ import annotations
import hashlib
import logging
import os
import re
from typing import Any, Dict, List, Optional
import httpx

from src.core.models import (
    BoardType,
    Deal,
    Destination,
    PriceBreakdown,
    RoomOffer,
    StayRequest,
)
from src.sources.base import BaseDealSource, DealSourceException

logger = logging.getLogger(__name__)


class SerpApiGoogleHotelsSource(BaseDealSource):
    """
    Adapter for querying Google Hotels via SerpApi.
    Aggregates multi-OTA rates for family occupancy (2 adults + 15yo + 7yo).
    """

    BASE_URL = "https://serpapi.com/search"

    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limit_rps: float = 1.0,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(name="serpapi_google_hotels", rate_limit_rps=rate_limit_rps)
        self.api_key = api_key or os.getenv("SERPAPI_API_KEY", "")
        self._external_client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._external_client:
            return self._external_client
        return httpx.AsyncClient(timeout=30.0)

    async def health_check(self) -> bool:
        """Verify presence of API key."""
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def _estimate_tourist_tax_eur(self, star_rating: Optional[float], nights: int) -> float:
        """
        Estimate municipal tourist tax (tassa di soggiorno) for the family.
        Rule: 2 adults + 15-year-old pay full rate (3 taxable persons).
        The 7-year-old is almost universally exempt in Italian municipalities.
        """
        stars = int(star_rating) if star_rating else 3
        if stars >= 5:
            rate_per_person = 4.50
        elif stars == 4:
            rate_per_person = 3.00
        else:
            rate_per_person = 2.00

        taxable_persons = 3  # 2 adults + 15yo
        return round(nights * taxable_persons * rate_per_person, 2)

    def _parse_star_rating(self, hotel_class: Optional[str]) -> Optional[float]:
        if not hotel_class:
            return None
        match = re.search(r"(\d+(\.\d+)?)", hotel_class)
        return float(match.group(1)) if match else None

    def _generate_deal_id(
        self,
        property_id: str,
        stay: StayRequest,
        total_eur: float,
    ) -> str:
        raw_key = f"{self.name}:{property_id}:{stay.check_in}:{stay.check_out}:{total_eur:.2f}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

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

            # Price extraction
            total_rate_obj = prop.get("total_rate", {})
            rate_per_night_obj = prop.get("rate_per_night", {})

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

            # Amenities & Inclusions
            amenities = [a.lower() for a in prop.get("amenities", [])]
            board = BoardType.BREAKFAST if any("breakfast" in a or "colazione" in a for a in amenities) else BoardType.ROOM_ONLY

            terme_included = any(
                "spa" in a or "wellness" in a or "terme" in a or "thermal" in a
                for a in amenities
            ) or destination.has_thermal_baths

            # Child policy compliance check
            child_compliant = True
            if destination.minimum_child_age_spa and destination.minimum_child_age_spa > 7:
                child_compliant = False

            # Booking URL
            link = prop.get("link") or "https://www.google.com/travel/hotels"
            property_id = prop.get("property_token") or prop.get("hotel_id") or hashlib.md5(name.encode("utf-8")).hexdigest()[:12]

            # Price breakdown
            est_tax = self._estimate_tourist_tax_eur(star_rating, stay.nights)
            price = PriceBreakdown(
                total_eur=float(total_eur),
                price_per_night_eur=float(price_per_night_eur),
                taxes_included=True,
                estimated_tourist_tax_eur=est_tax,
                original_price_eur=None,
            )

            # Room offer
            room_offer = RoomOffer(
                name="Family Occupancy (2A + 15yo + 7yo)",
                room_count=1,
                max_guests=4,
                board=board,
                terme_included=terme_included,
                terme_child_policy_compliant=child_compliant,
            )

            deal_id = self._generate_deal_id(property_id, stay, float(total_eur))

            return Deal(
                id=deal_id,
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
                booking_url=link,
                score=0.0,
            )
        except Exception as exc:
            logger.warning("Error normalizing SerpApi property %s: %s", prop.get("name"), exc)
            return None

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

        params = {
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
            "hotel_class": "3,4,5",
            "amenities": "10,6",  # 10=Spa, 6=Pool
            "api_key": self.api_key,
        }

        client = await self._get_client()
        try:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise DealSourceException(f"SerpApi HTTP error {exc.response.status_code}: {exc}") from exc
        except httpx.RequestError as exc:
            raise DealSourceException(f"SerpApi connection failure: {exc}") from exc
        finally:
            if not self._external_client:
                await client.aclose()

        properties = data.get("properties", [])
        deals: List[Deal] = []
        for prop in properties:
            deal = self._normalize_deal(prop, destination, stay)
            if deal:
                deals.append(deal)

        return deals
