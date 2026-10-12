"""Tests for weekend date rules, ranking and the CLI."""

from datetime import date

from src.cli import main
from src.core.models import (
    BoardType,
    Deal,
    Destination,
    DestinationCategory,
    PartyComposition,
    PriceBreakdown,
    RoomOffer,
    StayRequest,
    TransitRoute,
)
from src.engine.date_rules import (
    easter_sunday,
    italian_public_holidays,
    next_friday,
    upcoming_weekend_stays,
)
from src.engine.ranking import rank_deals

PARTY = PartyComposition(adults=2, children_ages=[15, 7])


# --- date rules -------------------------------------------------------------

def test_next_friday_is_strictly_after_today():
    assert next_friday(date(2026, 10, 12)) == date(2026, 10, 16)  # Monday
    assert next_friday(date(2026, 10, 16)) == date(2026, 10, 23)  # Friday itself
    assert next_friday(date(2026, 10, 17)) == date(2026, 10, 23)  # Saturday


def test_regular_weekends_are_friday_to_sunday():
    stays = upcoming_weekend_stays(date(2026, 10, 12), 4, PARTY)
    assert [s.check_in for s in stays] == [
        date(2026, 10, 16), date(2026, 10, 23), date(2026, 10, 30), date(2026, 11, 6)
    ]
    for s in stays:
        assert s.check_in.weekday() == 4
        assert s.check_out.weekday() == 6
        assert s.nights == 2
        assert s.party.children_ages == [15, 7]


def test_easter():
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert easter_sunday(2027) == date(2027, 3, 28)
    assert date(2027, 3, 29) in italian_public_holidays(2027)  # Pasquetta


def test_holiday_monday_extends_to_three_nights():
    # Pasquetta 2027 is Monday 29 March
    stays = upcoming_weekend_stays(date(2027, 3, 22), 1, PARTY)
    assert stays[0].check_in == date(2027, 3, 26)
    assert stays[0].check_out == date(2027, 3, 29)
    assert stays[0].nights == 3 and stays[0].is_long_weekend


def test_long_weekends_can_be_disabled():
    stays = upcoming_weekend_stays(date(2027, 3, 22), 1, PARTY, include_long_weekends=False)
    assert stays[0].nights == 2 and not stays[0].is_long_weekend


# --- ranking ----------------------------------------------------------------

def make_dest(dest_id="a", hours=3.0, min_age=None) -> Destination:
    return Destination(
        id=dest_id,
        name=dest_id.upper(),
        region="Toscana",
        category=DestinationCategory.TERME,
        primary_station="X",
        transit_route=TransitRoute(
            destination_name=dest_id, destination_station="X",
            total_duration_minutes=int(hours * 60),
        ),
        minimum_child_age_spa=min_age,
    )


def make_deal(deal_id, total, dest_id="a", rating=8.0, spa=False, compliant=True) -> Deal:
    stay = StayRequest(check_in=date(2026, 11, 6), check_out=date(2026, 11, 8), party=PARTY)
    return Deal(
        id=deal_id, source_id="test", property_id=deal_id, property_name=deal_id,
        user_review_score=rating, destination_id=dest_id, stay_request=stay,
        room_offer=RoomOffer(board=BoardType.BREAKFAST, has_spa_amenity=spa,
                             terme_child_policy_compliant=compliant),
        price=PriceBreakdown(total_eur=total, price_per_night_eur=total / 2),
    )


def test_budget_filter_and_ordering():
    dests = {"a": make_dest("a")}
    ranked = rank_deals(
        [make_deal("cheap", 300), make_deal("pricey", 900), make_deal("over", 2000)],
        dests, max_travel_hours=7.0, budget_total_eur=1000,
    )
    assert [r.deal.id for r in ranked] == ["cheap", "pricey"]
    assert ranked[0].score > ranked[1].score
    assert ranked[0].deal.score == ranked[0].score


def test_same_deal_seen_twice_keeps_lowest_price():
    ranked = rank_deals(
        [make_deal("x", 500), make_deal("x", 450)], {"a": make_dest("a")}, max_travel_hours=7.0
    )
    assert len(ranked) == 1 and ranked[0].deal.price.total_eur == 450


def test_flags_unconfirmed_room_and_barred_child():
    ranked = rank_deals(
        [make_deal("x", 500, spa=True, compliant=False)],
        {"a": make_dest("a", min_age=14)}, max_travel_hours=7.0,
    )
    flags = ranked[0].flags
    assert "room for 4 not confirmed" in flags
    assert any("youngest child barred" in f for f in flags)


# --- CLI --------------------------------------------------------------------

def test_cli_demo_runs_offline(capsys):
    assert main(["--demo"]) == 0
    out = capsys.readouterr().out
    assert "Hotel Terme Bologna" in out
    assert "room for 4 not confirmed" in out


def test_cli_plan_respects_search_cap(capsys):
    assert main(["--plan", "--terme-only", "--max-searches", "5"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 5


def test_cli_without_key_exits_cleanly(monkeypatch, capsys):
    monkeypatch.setenv("SERPAPI_API_KEY", "")
    assert main(["--destination", "acqui-terme"]) == 2
    assert "SERPAPI_API_KEY is not set" in capsys.readouterr().err
