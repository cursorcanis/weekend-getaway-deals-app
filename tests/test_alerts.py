"""Tests for persistence, alert selection, notifiers and the --once service mode."""

from datetime import date

import httpx
import pytest

from src.cli import main, plan_searches
from src.core.config import Settings
from src.core.models import (
    AlertType,
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
from src.notify import NotifierError, TelegramNotifier, notifiers_from_settings
from src.notify.channels import EmailNotifier
from src.notify.format import TELEGRAM_MAX_CHARS, format_telegram
from src.storage.store import DealStore

TODAY = date(2026, 10, 13)
STAY = StayRequest(check_in=date(2026, 10, 16), check_out=date(2026, 10, 18),
                   party=PartyComposition(adults=2, children_ages=[15, 7]))
DEST = Destination(
    id="abano-terme", name="Abano Terme", region="Veneto", category=DestinationCategory.TERME,
    primary_station="Terme Euganee",
    transit_route=TransitRoute(destination_name="Abano Terme", destination_station="Terme Euganee",
                               total_duration_minutes=300),
)


def make_deal(deal_id="d1", total=400.0, name="Hotel Test", stay=STAY, url=None) -> Deal:
    return Deal(
        id=deal_id, source_id="test", property_id=deal_id, property_name=name,
        user_review_score=8.5, destination_id=DEST.id, stay_request=stay,
        room_offer=RoomOffer(max_guests=4),
        price=PriceBreakdown(total_eur=total, price_per_night_eur=total / 2),
        booking_url=url,
    )


def ranked(*deals):
    return rank_deals(list(deals), {DEST.id: DEST}, max_travel_hours=7.0)


def alerts_for(store, *deals, min_score=0.0):
    return select_alerts(ranked(*deals), store.last_alerted_price, TODAY,
                         min_score=min_score, min_price_drop_eur=30.0, max_alerts=10)


@pytest.fixture
def store():
    with DealStore(":memory:") as s:
        yield s


# --- store ------------------------------------------------------------------

def test_store_tracks_price_history_and_lowest(store):
    store.record_observations([make_deal(total=400)])
    store.record_observations([make_deal(total=350)])
    store.record_observations([make_deal(total=380)])
    assert store.price_history("d1") == [400, 350, 380]
    row = store._conn.execute(
        "SELECT last_price_eur, lowest_price_eur FROM deals WHERE deal_id='d1'").fetchone()
    assert row == (380, 350)


def test_meta_roundtrip(store):
    assert store.get_meta("k") is None
    store.set_meta("k", "1")
    store.set_meta("k", "2")
    assert store.get_meta("k") == "2"


# --- alert rules ------------------------------------------------------------

def test_new_deal_alerted_once(store):
    [a] = alerts_for(store, make_deal())
    assert a.kind == AlertType.NEW_DEAL
    store.record_alert("d1", a.kind.value, 400)
    assert alerts_for(store, make_deal()) == []


def test_small_drop_not_alerted_big_drop_is(store):
    store.record_alert("d1", "new_deal", 400)
    assert alerts_for(store, make_deal(total=380)) == []  # only EUR 20 cheaper
    [a] = alerts_for(store, make_deal(total=360))
    assert a.kind == AlertType.PRICE_DROP and a.previous_price_eur == 400


def test_drop_measured_against_last_alerted_price(store):
    store.record_alert("d1", "new_deal", 400)
    store.record_alert("d1", "price_drop", 360)
    assert alerts_for(store, make_deal(total=350)) == []  # 10 below last alert
    assert len(alerts_for(store, make_deal(total=330))) == 1


def test_price_rise_not_alerted(store):
    store.record_alert("d1", "new_deal", 400)
    assert alerts_for(store, make_deal(total=500)) == []


def test_low_score_and_past_stays_skipped(store):
    assert alerts_for(store, make_deal(), min_score=101) == []
    past = StayRequest(check_in=date(2026, 10, 9), check_out=date(2026, 10, 11))
    assert alerts_for(store, make_deal(stay=past)) == []


def test_max_alerts_keeps_best(store):
    deals = [make_deal(f"d{i}", total=300 + 50 * i) for i in range(5)]
    picked = select_alerts(ranked(*deals), store.last_alerted_price, TODAY,
                           min_score=0, min_price_drop_eur=30, max_alerts=2)
    assert [a.ranked.deal.id for a in picked] == ["d0", "d1"]


# --- search rotation --------------------------------------------------------

def test_plan_rotation_covers_every_pair():
    dests = [DEST.model_copy(update={"id": f"x{i}"}) for i in range(5)]
    seen, offset = set(), 0
    for _ in range(3):
        pairs, _ = plan_searches(dests, [STAY], max_searches=2, offset=offset)
        offset += len(pairs)
        seen.update(d.id for d, _ in pairs)
    assert seen == {f"x{i}" for i in range(5)}


# --- formatting and channels ------------------------------------------------

def test_telegram_html_escapes_scraped_text_and_splits(store):
    evil = make_deal(name="<script>x</script> & Spa", url="https://example.com/?a=1&b=<2>")
    [a] = alerts_for(store, evil)
    [msg] = format_telegram([a])
    assert "<script>" not in msg
    assert "&lt;script&gt;x&lt;/script&gt; &amp; Spa" in msg
    assert 'href="https://example.com/?a=1&amp;b=%3C2%3E"' in msg

    many = [a] * 40
    msgs = format_telegram(many)
    assert len(msgs) > 1 and all(len(m) <= TELEGRAM_MAX_CHARS for m in msgs)


def test_telegram_errors_never_contain_token(store):
    [a] = alerts_for(store, make_deal())
    token = "123:SECRET-TOKEN"

    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    n = TelegramNotifier(token, "42", client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(NotifierError) as exc:
        n.send([a])
    assert "SECRET" not in str(exc.value)

    bad = httpx.MockTransport(lambda r: httpx.Response(401, json={"description": "Unauthorized"}))
    n = TelegramNotifier(token, "42", client=httpx.Client(transport=bad))
    with pytest.raises(NotifierError) as exc:
        n.send([a])
    assert "401" in str(exc.value) and "SECRET" not in str(exc.value)


def test_telegram_sends_html_to_chat(store):
    [a] = alerts_for(store, make_deal())
    sent = []

    def ok(request):
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    TelegramNotifier("t", "42", client=httpx.Client(transport=httpx.MockTransport(ok))).send([a])
    body = sent[0].read().decode()
    assert '"chat_id":"42"' in body.replace(" ", "") and '"parse_mode":"HTML"' in body.replace(" ", "")


def test_email_message(store):
    [a] = alerts_for(store, make_deal())
    msg = EmailNotifier("smtp.example.com", 587, None, None, "me@example.com",
                        ["a@example.com", "b@example.com"]).build_message([a])
    assert msg["Subject"] == "Weekend deals: 1 new"
    assert msg["To"] == "a@example.com, b@example.com"
    assert "Hotel Test" in msg.get_content() and "EUR 400 total" in msg.get_content()


def test_channels_enabled_only_when_configured():
    assert notifiers_from_settings(Settings(_env_file=None)) == []
    s = Settings(_env_file=None, telegram_bot_token="t", telegram_chat_id="1",
                 smtp_host="smtp.example.com", alert_email_to="a@example.com, b@example.com")
    chans = notifiers_from_settings(s)
    assert [c.name for c in chans] == ["telegram", "email"]
    assert chans[1].recipients == ["a@example.com", "b@example.com"]


# --- --once end to end (offline demo) ----------------------------------------

def test_once_alerts_then_dedups(tmp_path, monkeypatch, capsys):
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST", "ALERT_EMAIL_TO"):
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "deals.db"))

    assert main(["--demo", "--once"]) == 0
    first = capsys.readouterr().out
    assert "[NEW] Hotel Terme Bologna" in first

    assert main(["--demo", "--once"]) == 0
    assert "[NEW]" not in capsys.readouterr().out
    assert (tmp_path / "demo.db").exists()


def test_dry_run_does_not_mark_sent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "deals.db"))
    assert main(["--demo", "--once", "--dry-run"]) == 0
    assert main(["--demo", "--once", "--dry-run"]) == 0
    assert capsys.readouterr().out.count("[NEW] Hotel Terme Bologna") == 2


def test_failed_delivery_is_retried_next_run(tmp_path, monkeypatch):
    import src.cli as cli

    class Broken:
        name = "broken"

        def send(self, alerts):
            raise NotifierError("down")

    monkeypatch.setenv("DB_PATH", str(tmp_path / "deals.db"))
    monkeypatch.setattr(cli, "notifiers_from_settings", lambda s: [Broken()])
    assert main(["--demo", "--once"]) == 0
    with DealStore(tmp_path / "demo.db") as s:
        assert s._conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0] == 0
        assert s._conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 2


def test_verbose_does_not_log_request_urls(tmp_path, monkeypatch, caplog):
    import logging

    monkeypatch.setenv("DB_PATH", str(tmp_path / "deals.db"))
    with caplog.at_level(logging.INFO):
        assert main(["--demo", "--once", "--dry-run", "-v"]) == 0
    assert "api_key" not in caplog.text and "demo-offline" not in caplog.text


def test_dry_run_requires_service_mode():
    with pytest.raises(SystemExit):
        main(["--demo", "--dry-run"])
