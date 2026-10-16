"""Phase 5: named terme resorts, terme offer-page watcher, live transit check, alert lines."""

import argparse
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from src.cli import destinations_by_id, run_offers, select_destinations, verify_transit
from src.core.config import Settings
from src.core.models import (
    Deal,
    Destination,
    DestinationCategory,
    PartyComposition,
    PriceBreakdown,
    RoomOffer,
    StayRequest,
    TransitRoute,
)
from src.engine.alerts import select_alerts
from src.engine.ranking import rank_deals
from src.notify.format import format_offers_telegram, format_offers_text, format_text
from src.sources.serpapi import SerpApiGoogleHotelsSource
from src.sources.terme_offers import (
    USER_AGENT,
    Offer,
    OfferPage,
    OfferWatcher,
    load_offer_pages,
    parse_offer_titles,
)
from src.storage.store import DealStore
from transit.dynamic_checker import TransitCheckError, TransitChecker, italy_utc_offset
from transit.static_catalogue import StaticCatalogue, load_resort_targets

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
STAY = StayRequest(check_in=date(2026, 11, 6), check_out=date(2026, 11, 8),
                   party=PartyComposition(adults=2, children_ages=[15, 7]))
DEST = Destination(
    id="saturnia", name="Saturnia", region="Toscana", category=DestinationCategory.TERME,
    primary_station="Grosseto", latitude=42.648, longitude=11.512,
    transit_route=TransitRoute(destination_name="Saturnia", destination_station="Grosseto",
                               total_duration_minutes=390),
)
PAGE = OfferPage(
    id="spa", name="Test Spa offers", destination_id="saturnia",
    url="https://spa.example.com/offerte/", heading_tag="h2",
    start_after="^OFFERTE$", stop_at="^Offerte$", exclude="(?i)golf",
)


def offers_html(*titles: str) -> str:
    items = "".join(f"<div><h2 class='t'>{t}</h2><p>from EUR 199 pp</p></div>" for t in titles)
    return (f"<html><body><h2>Menu</h2><h1>OFFERTE</h1>{items}"
            f"<h2>Offerte</h2><h2>Footer link</h2></body></html>")


@pytest.fixture
def store():
    with DealStore(":memory:") as s:
        yield s


# --- offer page parsing --------------------------------------------------------

def test_parse_takes_headings_between_markers_only():
    html = offers_html("SHORT STAY", "Golf &amp; SPA", "Family <b>Weekend</b>", "SHORT  STAY")
    assert parse_offer_titles(html, PAGE) == ["SHORT STAY", "Family Weekend"]


def test_parse_without_start_marker_finds_nothing():
    assert parse_offer_titles("<h2>SHORT STAY</h2>", PAGE) == []


def test_configured_pages_load_and_respect_compliance_review():
    pages = load_offer_pages()
    assert {p.id for p in pages} == {"saturnia-resort", "terme-merano"}
    catalogue = StaticCatalogue()
    for p in pages:
        assert catalogue.get(p.destination_id), p.destination_id
        # robots.txt (Merano) disallows offer/date/room query URLs; we only poll listings
        assert "?" not in p.url
        # booking engines and JS-only pages are out of scope
        assert "grottagiusti" not in p.url and "synxis" not in p.url


# --- offer watcher -------------------------------------------------------------

class FakeSite:
    def __init__(self, html: str, status: int = 200, headers=None):
        self.html, self.status, self.headers = html, status, headers or {}
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, text=self.html, headers=self.headers)


def watcher(store, site, **kw):
    return OfferWatcher(store, client=httpx.Client(transport=httpx.MockTransport(site.handler)),
                        sleep=lambda s: None, **kw)


def test_watcher_reports_new_offers_until_alerted(store):
    site = FakeSite(offers_html("SHORT STAY", "Plan & Save"), headers={"ETag": '"v1"'})
    offers, errors = watcher(store, site).check([PAGE], now=NOW)
    assert errors == []
    assert [o.title for o in offers] == ["SHORT STAY", "Plan & Save"]
    assert site.requests[0].headers["User-Agent"] == USER_AGENT

    # Not delivered yet: still pending next run, without fetching again (12h interval)
    offers, _ = watcher(store, site).check([PAGE], now=NOW + timedelta(hours=1))
    assert len(offers) == 2 and len(site.requests) == 1

    store.mark_offers_alerted((o.page.id, o.key) for o in offers)
    assert watcher(store, site).check([PAGE], now=NOW + timedelta(hours=2))[0] == []


def test_watcher_only_new_titles_after_change_and_conditional_get(store):
    site = FakeSite(offers_html("SHORT STAY"), headers={"ETag": '"v1"'})
    offers, _ = watcher(store, site).check([PAGE], now=NOW)
    store.mark_offers_alerted((o.page.id, o.key) for o in offers)

    site.html = offers_html("SHORT STAY", "Natale in famiglia")
    offers, _ = watcher(store, site).check([PAGE], now=NOW + timedelta(hours=13))
    assert [o.title for o in offers] == ["Natale in famiglia"]
    assert site.requests[1].headers["If-None-Match"] == '"v1"'


def test_watcher_304_is_quiet(store):
    site = FakeSite("", status=304)
    assert watcher(store, site).check([PAGE], now=NOW) == ([], [])


@pytest.mark.parametrize("status", [403, 429])
def test_watcher_stops_polling_when_refused(store, status):
    site = FakeSite("denied", status=status)
    _, errors = watcher(store, site).check([PAGE], now=NOW)
    assert "polling stopped" in errors[0]
    _, errors = watcher(store, site).check([PAGE], now=NOW + timedelta(days=3))
    assert len(site.requests) == 1 and "--offers-unblock spa" in errors[0]

    store.delete_meta("offers:spa:blocked")
    watcher(store, site).check([PAGE], now=NOW + timedelta(days=3))
    assert len(site.requests) == 2


def test_watcher_layout_change_is_an_error_not_a_removal(store):
    site = FakeSite("<html><h1>Nuovo sito</h1></html>")
    offers, errors = watcher(store, site).check([PAGE], now=NOW)
    assert offers == [] and "layout" in errors[0]


def test_watcher_network_error_does_not_raise(store):
    def boom(request):
        raise httpx.ConnectError("down")
    w = OfferWatcher(store, client=httpx.Client(transport=httpx.MockTransport(boom)),
                     sleep=lambda s: None)
    offers, errors = w.check([PAGE], now=NOW)
    assert offers == [] and "ConnectError" in errors[0]


def test_watcher_spaces_requests(store):
    pages = [PAGE, OfferPage(**{**PAGE.__dict__, "id": "spa2"})]
    slept = []
    site = FakeSite(offers_html("A"))
    OfferWatcher(store, client=httpx.Client(transport=httpx.MockTransport(site.handler)),
                 sleep=slept.append).check(pages, now=NOW)
    assert len(site.requests) == 2 and len(slept) == 1 and 0 < slept[0] <= 2.0


def test_run_offers_marks_only_after_delivery(store, monkeypatch, capsys):
    import src.cli as cli

    monkeypatch.setattr(cli, "load_offer_pages", lambda: [PAGE])
    site = FakeSite(offers_html("SHORT STAY"))
    real = cli.OfferWatcher
    monkeypatch.setattr(cli, "OfferWatcher", lambda s, **kw: real(
        s, client=httpx.Client(transport=httpx.MockTransport(site.handler)),
        sleep=lambda x: None, **kw))
    plan = argparse.Namespace(destinations=[DEST])
    settings = Settings(_env_file=None)

    sent = []

    class Channel:
        name = "test"

        def send_offers(self, offers):
            sent.append(offers)

    run_offers(argparse.Namespace(dry_run=True), settings, store, [Channel()], plan)
    assert sent == [] and "[NEW PACKAGE] Test Spa offers" in capsys.readouterr().out
    assert len(store.unalerted_offers(["spa"])) == 1

    run_offers(argparse.Namespace(dry_run=False), settings, store, [Channel()], plan)
    assert len(sent) == 1 and store.unalerted_offers(["spa"]) == []


def test_offer_messages():
    offers = [Offer(PAGE, "SHORT STAY"), Offer(PAGE, "Plan <&> Save")]
    text = format_offers_text(offers)
    assert "[NEW PACKAGE] Test Spa offers" in text and "  - SHORT STAY" in text
    assert PAGE.url in text and "15-year-old" in text
    [html] = format_offers_telegram(offers)
    assert "Plan &lt;&amp;&gt; Save" in html and f'href="{PAGE.url}"' in html


# --- named terme resorts -------------------------------------------------------

def test_resort_targets_point_at_catalogued_terme():
    catalogue = StaticCatalogue()
    resorts = load_resort_targets()
    assert len(resorts) >= 5
    for r in resorts:
        dest = catalogue.get(r["destination_id"])
        assert dest and dest["is_terme"], r
        # the 7-year-old must be allowed in the pools
        assert (dest.get("minimum_child_age_spa") or 0) <= 7, r


def test_resorts_follow_their_town_and_ranking_uses_town():
    args = argparse.Namespace(region=None, terme_only=True, destination=["saturnia"])
    dests = select_destinations(StaticCatalogue(), args, max_hours=7.0)
    assert [d.search_query for d in dests] == [None, "Terme di Saturnia Natural Destination"]
    assert dests[1].id == "saturnia" and dests[1].transit_route == dests[0].transit_route
    assert destinations_by_id(dests)["saturnia"].name == dests[0].name

    no_resorts = select_destinations(StaticCatalogue(), args, max_hours=7.0, include_resorts=False)
    assert len(no_resorts) == 1


@pytest.mark.asyncio
async def test_serpapi_named_resort_query_and_single_property_response():
    seen = []
    detail = {
        "search_metadata": {"status": "Success"},
        "type": "hotel",
        "name": "Terme di Saturnia Natural Destination",
        "property_token": "tok-saturnia",
        "hotel_class": "5-star hotel",
        "overall_rating": 4.6,
        "total_rate": {"extracted_lowest": 1450},
        "amenities": ["Spa", "Breakfast ($)"],
        "link": "https://www.termedisaturnia.it/",
    }

    def handler(request):
        seen.append(request.url.params["q"])
        return httpx.Response(200, json=detail)

    source = SerpApiGoogleHotelsSource(api_key="k", rate_limit_rps=0,
                                       http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    resort = DEST.model_copy(update={"search_query": "Terme di Saturnia Natural Destination"})
    [deal] = await source.search(resort, STAY)
    assert seen == ["Terme di Saturnia Natural Destination"]
    assert deal.property_name == "Terme di Saturnia Natural Destination"
    assert deal.price.total_eur == 1450 and deal.star_rating == 5.0
    assert deal.destination_id == "saturnia"


# --- live transit check --------------------------------------------------------

class FakeRoutes:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.requests = payload, status, []

    def handler(self, request):
        self.requests.append(request)
        return httpx.Response(self.status, json=self.payload)


def checker(store, routes):
    return TransitChecker("secret-key", store, 44.3312, 9.2138,
                          client=httpx.Client(transport=httpx.MockTransport(routes.handler)))


def test_transit_checker_request_and_cache(store):
    routes = FakeRoutes({"routes": [{"duration": "21000s"}, {"duration": "18600s"}]})
    c = checker(store, routes)
    assert c.fastest_minutes(DEST, date(2026, 11, 6)) == 310
    assert c.fastest_minutes(DEST, date(2026, 11, 6)) == 310
    assert len(routes.requests) == 1

    req = routes.requests[0]
    body = json.loads(req.content)
    assert body["travelMode"] == "TRANSIT"
    assert body["departureTime"] == "2026-11-06T14:00:00+01:00"
    assert body["destination"]["location"]["latLng"] == {"latitude": 42.648, "longitude": 11.512}
    assert req.headers["X-Goog-Api-Key"] == "secret-key"
    assert "secret-key" not in str(req.url)


def test_transit_cache_expires(store):
    store.save_transit_minutes("saturnia", date(2026, 11, 6), 300, now=NOW - timedelta(days=31))
    routes = FakeRoutes({"routes": [{"duration": "18000s"}]})
    checker(store, routes).fastest_minutes(DEST, date(2026, 11, 6))
    assert len(routes.requests) == 1


def test_transit_no_route_is_none_and_cached(store):
    routes = FakeRoutes({})
    c = checker(store, routes)
    assert c.fastest_minutes(DEST, date(2026, 11, 6)) is None
    assert c.fastest_minutes(DEST, date(2026, 11, 6)) is None
    assert len(routes.requests) == 1


def test_transit_error_has_no_key(store):
    routes = FakeRoutes({"error": {"status": "PERMISSION_DENIED"}}, status=403)
    with pytest.raises(TransitCheckError) as exc:
        checker(store, routes).fastest_minutes(DEST, date(2026, 11, 6))
    assert "secret-key" not in str(exc.value) and "403" in str(exc.value)


def test_italy_utc_offset_follows_dst():
    assert italy_utc_offset(date(2026, 3, 28)) == "+01:00"   # day before the switch
    assert italy_utc_offset(date(2026, 3, 29)) == "+02:00"
    assert italy_utc_offset(date(2026, 10, 24)) == "+02:00"
    assert italy_utc_offset(date(2026, 10, 25)) == "+01:00"


def make_alerts(*dests):
    deals = [
        Deal(id=f"d{i}", source_id="t", property_id=f"p{i}", property_name=f"Hotel {i}",
             destination_id=d.id, stay_request=STAY, room_offer=RoomOffer(max_guests=4),
             price=PriceBreakdown(total_eur=400 + i, price_per_night_eur=200), user_review_score=9)
        for i, d in enumerate(dests)
    ]
    ranked = rank_deals(deals, {d.id: d for d in dests}, max_travel_hours=7.0)
    return select_alerts(ranked, lambda _: None, date(2026, 10, 15), 0, 30, 10)


class StubChecker:
    def __init__(self, minutes):
        self.minutes = minutes

    def fastest_minutes(self, dest, day):
        value = self.minutes[dest.id]
        if isinstance(value, Exception):
            raise value
        return value


def test_verify_transit_drops_slow_and_annotates():
    far = DEST.model_copy(update={"id": "far", "name": "Far"})
    unknown = DEST.model_copy(update={"id": "unknown", "name": "Unknown"})
    alerts = make_alerts(DEST, far, unknown)
    kept = verify_transit(alerts, StubChecker({"saturnia": 290, "far": 9 * 60, "unknown": None}), 8.0)
    assert [a.ranked.destination.id for a in kept] == ["saturnia", "unknown"]
    assert kept[0].transit_note == "fastest Fri train/bus 4h50 (Google)"
    assert "check by hand" in kept[1].transit_note
    assert "4h50 (Google)" in format_text(kept)


def test_verify_transit_keeps_alerts_when_api_fails():
    other = DEST.model_copy(update={"id": "other"})
    alerts = make_alerts(DEST, other)
    kept = verify_transit(alerts, StubChecker({"saturnia": 200, "other": TransitCheckError("x")}), 8.0)
    assert len(kept) == 2 and kept[1].transit_note is None


def test_alert_text_has_manual_train_check_line():
    [a] = make_alerts(DEST)
    assert "Trains: lefrecce.it, Santa Margherita Ligure-Portofino -> Grosseto, Fri 06 Nov" in format_text([a])
