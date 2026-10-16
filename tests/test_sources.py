"""Unit tests for deal source adapters using offline fixtures."""

from datetime import date
import json
from pathlib import Path
import pytest
import respx
import httpx

from src.core.models import (
    BoardType,
    Destination,
    DestinationCategory,
    PartyComposition,
    StayRequest,
    TransitMode,
    TransitRoute,
    TransitSegment,
)
from src.sources.serpapi import SerpApiGoogleHotelsSource


@pytest.fixture
def sample_destination() -> Destination:
    route = TransitRoute(
        origin="Santa Margherita Ligure-Portofino",
        destination_name="Abano Terme",
        destination_station="Terme Euganee-Abano-Montegrotto",
        total_duration_minutes=250,
        transfers=1,
        segments=[
            TransitSegment(
                mode=TransitMode.TRAIN,
                operator="Trenitalia",
                departure_station="Santa Margherita Ligure-Portofino",
                arrival_station="Milano Centrale",
                duration_minutes=135,
            ),
            TransitSegment(
                mode=TransitMode.TRAIN,
                operator="Trenitalia",
                departure_station="Milano Centrale",
                arrival_station="Terme Euganee-Abano-Montegrotto",
                duration_minutes=105,
            ),
        ],
    )
    return Destination(
        id="abano-terme",
        name="Abano Terme",
        region="Veneto",
        category=DestinationCategory.TERME,
        primary_station="Terme Euganee-Abano-Montegrotto",
        transit_route=route,
        has_thermal_baths=True,
        minimum_child_age_spa=None,
    )


@pytest.fixture
def sample_stay_request() -> StayRequest:
    return StayRequest(
        check_in=date(2026, 11, 6),   # Friday
        check_out=date(2026, 11, 8),  # Sunday (2 nights)
        party=PartyComposition(adults=2, children_ages=[15, 7]),
    )


@pytest.mark.asyncio
async def test_serpapi_source_offline_normalization(
    sample_destination: Destination,
    sample_stay_request: StayRequest,
) -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "serpapi" / "abano_terme_sample.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture_data = json.load(f)

    source = SerpApiGoogleHotelsSource(api_key="mock_test_key")

    with respx.mock(assert_all_called=True) as respx_mock:
        route = respx_mock.get(source.BASE_URL).respond(
            status_code=200,
            json=fixture_data,
        )

        deals = await source.search(sample_destination, sample_stay_request)

        assert route.called
        assert len(deals) == 2

        # Deal 1: Hotel Terme Bologna (3-star)
        deal1 = deals[0]
        assert deal1.property_name == "Hotel Terme Bologna"
        assert deal1.star_rating == 3.0
        assert deal1.price.total_eur == 320.0
        assert deal1.price.price_per_night_eur == 160.0
        # 3 stars -> €2.00/person/night * 3 persons (2A + 15yo, 7yo free) * 2 nights = €12.00
        assert deal1.price.estimated_tourist_tax_eur == 12.00
        assert deal1.room_offer.board == BoardType.BREAKFAST
        assert deal1.room_offer.has_spa_amenity is True
        # Google Hotels' list view doesn't say whether spa entry is in the rate
        assert deal1.room_offer.terme_included is None
        assert deal1.room_offer.terme_child_policy_compliant is True
        # Room details are unknown, not invented
        assert deal1.room_offer.max_guests is None
        assert deal1.room_offer.room_count is None
        # "15% less than usual" -> usual price 320 / 0.85
        assert deal1.price.discount_percent == 15.0

        # Deal 2: Grand Hotel Terme Trieste & Victoria (5-star)
        deal2 = deals[1]
        assert deal2.property_name == "Grand Hotel Terme Trieste & Victoria"
        assert deal2.star_rating == 5.0
        assert deal2.price.total_eur == 760.0
        # 5 stars -> €4.50/person/night * 3 persons * 2 nights = €27.00
        assert deal2.price.estimated_tourist_tax_eur == 27.00

