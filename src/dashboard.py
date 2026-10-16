"""Read-only local dashboard of the deals and terme packages in data/deals.db.

Served on 127.0.0.1 only, standard library, no external requests: open it in a
browser on the same PC. Deals are re-ranked with the same rules as the alerts.
"""

from __future__ import annotations
import logging
from datetime import date, datetime, timedelta, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional

from src.core.config import Settings
from src.core.models import Destination
from src.engine.ranking import rank_deals
from src.sources.terme_offers import load_offer_pages
from src.storage.store import DealStore
from transit.static_catalogue import StaticCatalogue

logger = logging.getLogger(__name__)

# Prices older than this are probably gone; the 12h poll refreshes the rest.
FRESH_DAYS = 3

STYLE = """
:root { --bg:#fafaf7; --fg:#1d1d1b; --muted:#6b6b66; --line:#e2e1da; --accent:#0b6e4f; --warn:#a35200; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161615; --fg:#ecebe6; --muted:#9a9993; --line:#33332f; --accent:#4fc59a; --warn:#f0a35e; }
}
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
       font:15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 32px 0 8px; }
.muted { color: var(--muted); } .warn { color: var(--warn); }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-size: 13px; color: var(--muted); font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
a { color: var(--accent); }
"""


def _destinations(catalogue: StaticCatalogue) -> Dict[str, Destination]:
    return {d["id"]: catalogue.to_destination(d) for d in catalogue.all_destinations}


def _ago(then: datetime, now: datetime) -> str:
    hours = (now - then).total_seconds() / 3600
    return f"{hours:.0f}h ago" if hours < 48 else f"{hours / 24:.0f}d ago"


def render_dashboard(store: DealStore, settings: Settings, today: date,
                     now: Optional[datetime] = None,
                     catalogue: Optional[StaticCatalogue] = None) -> str:
    now = now or datetime.now(timezone.utc)
    catalogue = catalogue or StaticCatalogue()
    rows = store.upcoming_deals(today, now - timedelta(days=FRESH_DAYS))
    seen = {d.id: (last_seen, lowest) for d, last_seen, lowest in rows}
    ranked = rank_deals([d for d, _, _ in rows], _destinations(catalogue),
                        settings.max_travel_hours, settings.budget_total_eur)

    deal_rows: List[str] = []
    for r in ranked:
        d, p, stay = r.deal, r.deal.price, r.deal.stay_request
        last_seen, lowest = seen[d.id]
        name = escape(d.property_name)
        if d.booking_url:
            name = f'<a href="{escape(str(d.booking_url))}" rel="noreferrer">{name}</a>'
        low = (f'<br><span class="muted">low EUR {lowest:.0f}</span>'
               if lowest < p.total_eur - 0.5 else "")
        extras = [d.room_offer.board.value.replace("_", " ")]
        if d.room_offer.has_spa_amenity:
            extras.append("spa")
        if p.discount_percent:
            extras.append(f"{p.discount_percent:.0f}% below usual")
        if d.user_review_score:
            extras.append(f"{d.user_review_score:.1f}/10")
        flags = f'<br><span class="warn">{escape("; ".join(r.flags))}</span>' if r.flags else ""
        deal_rows.append(
            f"<tr><td class=num>{r.score:.0f}</td>"
            f"<td>{name}<br><span class=muted>{escape(', '.join(extras))}</span>{flags}</td>"
            f"<td>{escape(r.destination.name)}<br><span class=muted>"
            f"~{r.destination.transit_route.total_hours:.1f}h train/bus</span></td>"
            f"<td>{stay.check_in:%a %d %b} &rarr; {stay.check_out:%a %d %b}</td>"
            f"<td class=num>EUR {p.total_eur:.0f}<br><span class=muted>"
            f"{p.price_per_night_eur:.0f}/night</span>{low}</td>"
            f"<td class=muted>{_ago(last_seen, now)}</td></tr>"
        )

    pages = {p.id: p for p in load_offer_pages()}
    offer_rows = []
    for page_id, title, first_seen, last_seen in store.recent_offers():
        page = pages.get(page_id)
        where = (f'<a href="{escape(page.url)}" rel="noreferrer">{escape(page.name)}</a>'
                 if page else escape(page_id))
        offer_rows.append(
            f"<tr><td>{escape(title)}</td><td>{where}</td>"
            f"<td class=muted>{_ago(datetime.fromisoformat(first_seen), now)}</td>"
            f"<td class=muted>{_ago(datetime.fromisoformat(last_seen), now)}</td></tr>"
        )

    party = settings_party(settings)
    deals_html = (
        "<div class=table-wrap><table><tr><th>Score</th><th>Hotel</th><th>Where</th>"
        "<th>Dates</th><th>Family total</th><th>Seen</th></tr>"
        + "".join(deal_rows) + "</table></div>"
        if deal_rows else
        f"<p class=muted>No deals seen in the last {FRESH_DAYS} days. "
        "Run <code>python -m src.cli --once</code>.</p>"
    )
    offers_html = (
        "<div class=table-wrap><table><tr><th>Package</th><th>Site</th><th>First seen</th>"
        "<th>Last seen</th></tr>" + "".join(offer_rows) + "</table></div>"
        if offer_rows else "<p class=muted>No terme packages recorded yet.</p>"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weekend Deals</title><style>{STYLE}</style></head>
<body><main>
<h1>Weekend deals</h1>
<p class=muted>{escape(party)} &middot; Fri&ndash;Sun from Santa Margherita Ligure &middot;
max ~{settings.max_travel_hours:g}h by train/bus &middot; updated {now.astimezone():%d %b %H:%M}</p>
<h2>Deals ({len(deal_rows)})</h2>
{deals_html}
<p class=muted>Prices are for the whole family; check the room really sleeps 4 and how the
15-year-old is charged before booking.</p>
<h2>Terme packages</h2>
{offers_html}
</main></body></html>"""


def settings_party(settings: Settings) -> str:
    ages = ", ".join(str(a) for a in settings.party_children_ages)
    return f"{settings.party_adults} adults + children aged {ages}"


def serve(settings: Settings, port: int = 8765) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            with DealStore(settings.db_path) as store:
                body = render_dashboard(store, settings, date.today()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args) -> None:
            logger.debug(fmt, *args)

    # Loopback only: the dashboard has no authentication.
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Dashboard on http://127.0.0.1:{port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
