"""Turn alerts into plain-text and Telegram-HTML messages."""

from __future__ import annotations
from html import escape
from typing import List

from src.core.models import AlertType
from src.engine.alerts import Alert
from src.sources.terme_offers import Offer

# Telegram rejects messages over 4096 characters.
TELEGRAM_MAX_CHARS = 4000


def subject_line(alerts: List[Alert]) -> str:
    drops = sum(1 for a in alerts if a.kind == AlertType.PRICE_DROP)
    new = len(alerts) - drops
    parts = []
    if new:
        parts.append(f"{new} new")
    if drops:
        parts.append(f"{drops} cheaper")
    return f"Weekend deals: {', '.join(parts)}"


def _facts(alert: Alert) -> dict:
    r = alert.ranked
    d, p, stay = r.deal, r.deal.price, r.deal.stay_request
    head = "PRICE DROP" if alert.kind == AlertType.PRICE_DROP else "NEW"
    price = f"EUR {p.total_eur:.0f} total for the family (EUR {p.price_per_night_eur:.0f}/night)"
    if alert.previous_price_eur is not None:
        price += f", was EUR {alert.previous_price_eur:.0f}"
    if p.estimated_tourist_tax_eur:
        price += f" + ~EUR {p.estimated_tourist_tax_eur:.0f} tourist tax"
    extras = [d.room_offer.board.value.replace("_", " ")]
    if d.room_offer.has_spa_amenity:
        extras.append("spa")
    if p.discount_percent:
        extras.append(f"{p.discount_percent:.0f}% below usual")
    if d.user_review_score:
        extras.append(f"rated {d.user_review_score:.1f}/10")
    route = r.destination.transit_route
    travel = f"~{route.total_hours:.1f}h by train/bus"
    if alert.transit_note:
        travel += f"; {alert.transit_note}"
    return {
        "head": head,
        "name": d.property_name + (f" {d.star_rating:.0f}*" if d.star_rating else ""),
        "where": f"{r.destination.name}, {r.destination.region} | {travel}",
        # Trenitalia can't be queried automatically (its terms forbid it): check by hand.
        "trains": f"Trains: lefrecce.it, {route.origin} -> {route.destination_station}, "
                  f"{stay.check_in:%a %d %b}",
        "when": f"{stay.check_in:%a %d %b} -> {stay.check_out:%a %d %b} ({stay.nights} nights)",
        "price": price,
        "extras": ", ".join(extras),
        "flags": "; ".join(r.flags),
        "score": f"{r.score:.0f}",
        "url": str(d.booking_url) if d.booking_url else "",
    }


def format_text(alerts: List[Alert]) -> str:
    blocks = []
    for a in alerts:
        f = _facts(a)
        lines = [
            f"[{f['head']}] {f['name']}  (score {f['score']})",
            f"  {f['where']}",
            f"  {f['when']}",
            f"  {f['price']}",
            f"  {f['extras']}",
            f"  {f['trains']}",
        ]
        if f["flags"]:
            lines.append(f"  ! {f['flags']}")
        if f["url"]:
            lines.append(f"  {f['url']}")
        blocks.append("\n".join(lines))
    footer = ("Prices are for 2 adults + children 15 and 7; check the room really sleeps 4 "
              "before booking.")
    return "\n\n".join(blocks + [footer])


def _telegram_block(alert: Alert) -> str:
    f = {k: escape(v) for k, v in _facts(alert).items()}
    name = f"<a href=\"{f['url']}\">{f['name']}</a>" if f["url"] else f["name"]
    lines = [
        f"<b>{f['head']}</b> {name} (score {f['score']})",
        f["where"],
        f["when"],
        f"<b>{f['price']}</b>",
        f["extras"],
        f["trains"],
    ]
    if f["flags"]:
        lines.append(f"⚠ {f['flags']}")
    return "\n".join(lines)


def format_telegram(alerts: List[Alert]) -> List[str]:
    """HTML messages, each under Telegram's size limit."""
    return _split_telegram(f"<b>{escape(subject_line(alerts))}</b>",
                           [_telegram_block(a) for a in alerts])


def _split_telegram(header: str, blocks: List[str]) -> List[str]:
    messages: List[str] = []
    current = header
    for block in blocks:
        if len(current) + 2 + len(block) > TELEGRAM_MAX_CHARS:
            messages.append(current)
            current = block
        else:
            current += "\n\n" + block
    messages.append(current)
    return messages


# --- terme offer pages -------------------------------------------------------

OFFERS_FOOTER = ("Package titles only: these pages show per-person prices for 2 adults, or none. "
                 "Check the family terms (the 15-year-old may pay as an adult) on the site.")


def offers_subject(offers: List[Offer]) -> str:
    return f"Terme packages: {len(offers)} new"


def _offers_by_page(offers: List[Offer]):
    pages = {}
    for o in offers:
        pages.setdefault(o.page, []).append(o.title)
    return pages.items()


def format_offers_text(offers: List[Offer]) -> str:
    blocks = []
    for page, titles in _offers_by_page(offers):
        lines = [f"[NEW PACKAGE] {page.name}"] + [f"  - {t}" for t in titles] + [f"  {page.url}"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks + [OFFERS_FOOTER])


def format_offers_telegram(offers: List[Offer]) -> List[str]:
    blocks = [
        "\n".join([f"<a href=\"{escape(page.url)}\">{escape(page.name)}</a>"]
                  + [f"• {escape(t)}" for t in titles])
        for page, titles in _offers_by_page(offers)
    ]
    return _split_telegram(f"<b>{escape(offers_subject(offers))}</b>",
                           blocks + [escape(OFFERS_FOOTER)])


