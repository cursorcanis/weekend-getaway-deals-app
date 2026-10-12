"""Stub adapter for direct Terme and Spa resort deal scrapers."""

from __future__ import annotations
import logging
from typing import List, Optional
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

# Known age limits across prominent Italian thermal bath operators
TERME_MINIMUM_AGE_POLICIES = {
    "qc_terme": 14,             # QC Terme strictly bars children under 14
    "bormio_bagni_vecchi": 14,  # QC Terme Bagni Vecchi (14+)
    "bormio_bagni_nuovi": 14,   # QC Terme Bagni Nuovi (14+)
    "bagno_vignoni_posta": 14,  # La Posta Hotel & Spa (Adults only 14+)
    "bormio_terme": 0,          # Family thermal spa (0+, slides 10+)
    "sirmione_aquaria": 2,      # Aquaria allows >= 2.5 years
    "terme_saturnia": 0,        # Parco Termale allows all ages (children pools 0.7m)
    "rapolano_querciolaia": 0,  # Antica Querciolaia (0+)
    "terme_merano": 0,          # Merano pools (0+, saunas 14+)
}


class DirectTermeScraperSource(BaseDealSource):
    """
    Adapter stub for direct web scraping of official Italian thermal bath package pages
    (e.g., Bormio Terme, Terme di Saturnia, Terme di Sirmione Aquaria, Abano Terme resorts).

    This source extracts special weekend getaway promotions, verifies child admission
    rules (7yo eligibility), and maps offers into the normalized Deal model.
    """

    def __init__(
        self,
        rate_limit_rps: float = 0.5,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(name="terme_direct_scraper", rate_limit_rps=rate_limit_rps)
        self._external_client = http_client

    async def health_check(self) -> bool:
        """Verify connectivity to target package endpoints or scraping proxy."""
        return True

    def validate_family_spa_eligibility(
        self,
        operator_slug: str,
        child_ages: List[int],
    ) -> bool:
        """
        Check if all children in the party meet the operator's minimum age requirements.
        Returns False if any child is barred (e.g. 7yo at QC Terme).
        """
        min_age = TERME_MINIMUM_AGE_POLICIES.get(operator_slug, 0)
        return all(age >= min_age for age in child_ages)

    async def search(
        self,
        destination: Destination,
        stay: StayRequest,
    ) -> List[Deal]:
        """
        Search direct package offers for destinations with thermal baths.

        In production, this queries target URLs via Firecrawl or HTTPX,
        parses the HTML/Markdown payload for weekend room + spa package bundles,
        and enforces child admission eligibility.
        """
        if not destination.has_thermal_baths:
            return []

        # Enforce spa admission check for the 7-year-old
        is_compliant = True
        if destination.minimum_child_age_spa and destination.minimum_child_age_spa > 7:
            logger.info(
                "Destination %s thermal baths require age %s+; family 7yo is barred.",
                destination.name,
                destination.minimum_child_age_spa,
            )
            is_compliant = False

        deals: List[Deal] = []

        # Stub implementation: In Phase 5, concrete scrapers for Bormio Terme,
        # Sirmione, and Saturnia will populate this list from live package pages.
        logger.debug(
            "Direct Terme scraper queried for %s (compliant=%s). Concrete parsers activate in Phase 5.",
            destination.name,
            is_compliant,
        )

        return deals
