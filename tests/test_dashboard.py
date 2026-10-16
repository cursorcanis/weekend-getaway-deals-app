"""Tests for the read-only local dashboard."""

from datetime import date, datetime, timedelta, timezone

import pytest

from src.core.config import Settings
from src.dashboard import render_dashboard
from src.storage.store import DealStore
from tests.test_alerts import STAY, make_deal

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 13)


@pytest.fixture
def store():
    with DealStore(":memory:") as s:
        yield s


def render(store, **settings):
    return render_dashboard(store, Settings(_env_file=None, **settings), TODAY, now=NOW)


def test_lists_fresh_upcoming_deals_with_lowest_price(store):
    store.record_observations([make_deal(total=400, url="https://example.com/h")], now=NOW - timedelta(hours=5))
    store.record_observations([make_deal(total=450, url="https://example.com/h")], now=NOW - timedelta(hours=2))
    html = render(store)
    assert "Hotel Test" in html and 'href="https://example.com/h"' in html
    assert "EUR 450" in html and "low EUR 400" in html
    assert "2h ago" in html
    assert "2 adults + children aged 15, 7" in html


def test_hides_stale_and_past_deals(store):
    store.record_observations([make_deal("old", name="Stale Hotel")], now=NOW - timedelta(days=5))
    past = STAY.model_copy(update={"check_in": date(2026, 10, 9), "check_out": date(2026, 10, 11)})
    store.record_observations([make_deal("past", name="Past Hotel", stay=past)], now=NOW)
    html = render(store)
    assert "Stale Hotel" not in html and "Past Hotel" not in html
    assert "No deals seen" in html


def test_budget_from_settings_applies(store):
    store.record_observations([make_deal(total=900, name="Pricey")], now=NOW)
    assert "Pricey" not in render(store, budget_total_eur=500)


def test_scraped_text_is_escaped(store):
    store.record_observations([make_deal(name="<script>x</script>")], now=NOW)
    store.record_offers("saturnia-resort", [("k", "<img src=x onerror=alert(1)>")], now=NOW)
    html = render(store)
    assert "<script>x" not in html and "&lt;script&gt;" in html
    assert "<img" not in html
    assert "Terme di Saturnia resort" in html  # page name and link from terme_offer_pages.yaml
