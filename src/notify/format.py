"""Turn alerts into plain-text and Telegram-HTML messages."""

from __future__ import annotations
from html import escape
from typing import List

from src.core.models import AlertType
from src.engine.alerts import Alert

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
    return {
        "head": head,
        "name": d.property_name + (f" {d.star_rating:.0f}*" if d.star_rating else ""),
        "where": f"{r.destination.name}, {r.destination.region} | "
                 f"~{r.destination.transit_route.total_hours:.1f}h by train/bus",
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
    ]
    if f["flags"]:
        lines.append(f"⚠ {f['flags']}")
    return "\n".join(lines)


def format_telegram(alerts: List[Alert]) -> List[str]:
    """HTML messages, each under Telegram's size limit."""
    messages: List[str] = []
    current = f"<b>{escape(subject_line(alerts))}</b>"
    for alert in alerts:
        block = _telegram_block(alert)
        if len(current) + 2 + len(block) > TELEGRAM_MAX_CHARS:
            messages.append(current)
            current = block
        else:
            current += "\n\n" + block
    messages.append(current)
    return messages
