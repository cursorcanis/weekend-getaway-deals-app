"""Regression tests for SerpApi adapter behaviour: identity, inference, retries, cache."""

from datetime import date
import httpx
import pytest
import respx

from src.core.models import (
    Destination,
    DestinationCategory,
    PartyComposition,
    StayRequest,
    TransitRoute,
)
from src.sources.base import DealSourceException
from src.sources.serpapi import SerpApiGoogleHotelsSource


def make_destination(min_spa_age=None) -> Destination:
    return Destination(
        id="abano-terme",
        name="Abano Terme",
        region="Veneto",
        category=DestinationCategory.TERME,
        primary_station="Terme Euganee-Abano-Montegrotto",
        transit_route=TransitRoute(
            destination_name="Abano Terme",
            destination_station="Terme Euganee-Abano-Montegrotto",
            total_duration_minutes=300,
        ),
        has_thermal_baths=True,
        minimum_child_age_spa=min_spa_age,
    )


STAY = StayRequest(
    check_in=date(2026, 11, 6),
    check_out=date(2026, 11, 8),
    party=PartyComposition(adults=2, children_ages=[15, 7]),
)


def prop(**overrides):
    base = {
        "name": "Hotel Example",
        "property_token": "tok123",
        "hotel_class": "4-star hotel",
        "total_rate": {"extracted_lowest": 400},
        "rate_per_night": {"extracted_lowest": 200},
        "amenities": ["Free Wi-Fi"],
        "link": "https://example.com/hotel",
    }
    base.update(overrides)
    return base


def test_deal_id_is_stable_when_price_changes():
    src = SerpApiGoogleHotelsSource(api_key="test-key-123")
    d1 = src._normalize_deal(prop(), make_destination(), STAY)
    d2 = src._normalize_deal(
        prop(total_rate={"extracted_lowest": 350}, rate_per_night={"extracted_lowest": 175}),
        make_destination(),
        STAY,
    )
    assert d1.id == d2.id
    assert d1.price.total_eur != d2.price.total_eur


def test_spa_not_inferred_from_thermal_destination():
    src = SerpApiGoogleHotelsSource(api_key="test-key-123")
    deal = src._normalize_deal(prop(amenities=["Free Wi-Fi"]), make_destination(), STAY)
    assert deal.room_offer.has_spa_amenity is False
    assert deal.room_offer.terme_included is None


def test_italian_amenities_recognised():
    src = SerpApiGoogleHotelsSource(api_key="test-key-123")
    deal = src._normalize_deal(
        prop(amenities=["Colazione gratuita", "Centro benessere"]), make_destination(), STAY
    )
    assert deal.room_offer.board.value == "breakfast"
    assert deal.room_offer.has_spa_amenity is True


def test_spa_age_restriction_flags_youngest_child():
    src = SerpApiGoogleHotelsSource(api_key="test-key-123")
    deal = src._normalize_deal(prop(amenities=["Spa"]), make_destination(min_spa_age=14), STAY)
    assert deal.room_offer.terme_child_policy_compliant is False


def test_booking_url_falls_back_to_offer_link_then_none():
    src = SerpApiGoogleHotelsSource(api_key="test-key-123")
    with_offer = src._normalize_deal(
        prop(link=None, prices=[{"source": "Booking.com", "link": "https://booking.example/x"}]),
        make_destination(),
        STAY,
    )
    assert str(with_offer.booking_url) == "https://booking.example/x"
    without = src._normalize_deal(prop(link=None), make_destination(), STAY)
    assert without.booking_url is None


def test_tourist_tax_follows_party_ages():
    src = SerpApiGoogleHotelsSource(api_key="test-key-123", tax_exempt_under_age=14)
    # 4-star: EUR 3/person/night; 2 adults + 15yo taxable, 7yo exempt -> 2 * 3 * 3
    assert src._estimate_tourist_tax_eur(4.0, 2, STAY.party) == 18.0
    young = PartyComposition(adults=2, children_ages=[10, 7])
    assert src._estimate_tourist_tax_eur(4.0, 2, young) == 12.0


def test_no_amenity_or_class_filter_by_default():
    src = SerpApiGoogleHotelsSource(api_key="test-key-123")
    params = src._build_params(make_destination(), STAY)
    assert "amenities" not in params and "hotel_class" not in params
    assert params["children_ages"] == "15,7"
    assert "api_key" not in params  # added only at request time, never cached


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr("src.sources.serpapi.asyncio.sleep", no_sleep)
    src = SerpApiGoogleHotelsSource(api_key="test-key-123", rate_limit_rps=0)
    with respx.mock:
        route = respx.get(src.BASE_URL).mock(
            side_effect=[
                httpx.Response(429),
                httpx.Response(200, json={"properties": [prop()]}),
            ]
        )
        deals = await src.search(make_destination(), STAY)
    assert route.call_count == 2
    assert len(deals) == 1


@pytest.mark.asyncio
async def test_error_message_does_not_leak_api_key(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr("src.sources.serpapi.asyncio.sleep", no_sleep)
    src = SerpApiGoogleHotelsSource(api_key="secret-key-xyz", rate_limit_rps=0, max_retries=1)
    with respx.mock:
        respx.get(src.BASE_URL).mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(DealSourceException) as exc_info:
            await src.search(make_destination(), STAY)
    assert "secret-key-xyz" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_cache_avoids_second_paid_call(tmp_path):
    src = SerpApiGoogleHotelsSource(api_key="test-key-123", rate_limit_rps=0, cache_dir=tmp_path)
    with respx.mock:
        route = respx.get(src.BASE_URL).respond(json={"properties": [prop()]})
        first = await src.search(make_destination(), STAY)
        second = await src.search(make_destination(), STAY)
    assert route.call_count == 1
    assert len(first) == len(second) == 1
    assert not any("test-key-123" in p.read_text() for p in tmp_path.iterdir())
