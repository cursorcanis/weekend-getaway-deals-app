"""Command-line entry point: search upcoming weekends once and print ranked deals.

    python -m src.cli --plan               # show what would be searched (no API calls)
    python -m src.cli --demo               # run on the recorded sample response (no API key)
    python -m src.cli --terme-only         # live search (needs SERPAPI_API_KEY)
    python -m src.cli --once               # one search + store + alert new/cheaper deals
    python -m src.cli --daemon             # repeat --once every POLL_INTERVAL_HOURS
    add --dry-run to print alerts instead of sending them (nothing is marked as alerted)
"""

from __future__ import annotations
import argparse
import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.config import PROJECT_ROOT, Settings, get_settings
from src.core.models import Deal, Destination, PartyComposition, StayRequest
from src.engine.alerts import Alert, select_alerts
from src.engine.date_rules import upcoming_weekend_stays
from src.engine.ranking import RankedDeal, rank_deals
from src.notify import ConsoleNotifier, Notifier, NotifierError, notifiers_from_settings
from src.sources.base import DealSourceException
from src.sources.serpapi import SerpApiGoogleHotelsSource
from src.storage.store import DealStore
from transit.static_catalogue import StaticCatalogue

logger = logging.getLogger("getaway")

DEMO_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "serpapi" / "abano_terme_sample.json"
DEMO_DESTINATION = "abano-terme"
DEMO_STAY = (date(2026, 11, 6), date(2026, 11, 8))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Find weekend hotel and terme deals reachable by train/bus from Santa Margherita Ligure.",
    )
    p.add_argument("--weekends", type=int, help="number of upcoming weekends to search")
    p.add_argument("--max-hours", type=float, help="max typical train/bus travel time in hours")
    p.add_argument("--terme-only", action="store_true", help="only thermal-bath destinations")
    p.add_argument("--region", help="only this region, e.g. Toscana")
    p.add_argument("--destination", action="append", metavar="ID",
                   help="only this destination id (repeatable), e.g. abano-terme")
    p.add_argument("--budget", type=float, help="max total stay price for the family, EUR")
    p.add_argument("--max-searches", type=int, help="cap on paid API searches this run")
    p.add_argument("--top", type=int, default=15, help="how many deals to print (default 15)")
    p.add_argument("--plan", action="store_true", help="print the search plan and exit, no API calls")
    p.add_argument("--demo", action="store_true",
                   help="use the recorded sample response for Abano Terme instead of the live API")
    p.add_argument("--json", action="store_true", help="print deals as JSON")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true",
                      help="search once, store results, alert new or cheaper deals")
    mode.add_argument("--daemon", action="store_true",
                      help="keep running: --once every POLL_INTERVAL_HOURS (Ctrl+C to stop)")
    p.add_argument("--dry-run", action="store_true",
                   help="with --once/--daemon: print alerts instead of sending, don't mark them sent")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def select_destinations(
    catalogue: StaticCatalogue, args: argparse.Namespace, max_hours: float
) -> List[Destination]:
    entries = catalogue.filter(
        region=args.region,
        is_terme=True if args.terme_only else None,
        max_hours=max_hours,
    )
    if args.destination:
        wanted = set(args.destination)
        unknown = wanted - {d["id"] for d in catalogue.all_destinations}
        if unknown:
            raise SystemExit(f"Unknown destination id(s): {', '.join(sorted(unknown))}")
        entries = [d for d in entries if d["id"] in wanted]
    entries.sort(key=lambda d: float(d["typical_travel_time_hours"]))
    return [catalogue.to_destination(d) for d in entries]


def plan_searches(
    destinations: List[Destination], stays: List[StayRequest], max_searches: int, offset: int = 0
) -> Tuple[List[Tuple[Destination, StayRequest]], int]:
    """
    Nearest weekend first, nearest destinations first, capped at max_searches.
    offset rotates the starting point so repeated runs eventually cover every pair.
    """
    all_pairs = [(dest, stay) for stay in stays for dest in destinations]
    if all_pairs and offset:
        start = offset % len(all_pairs)
        all_pairs = all_pairs[start:] + all_pairs[:start]
    return all_pairs[:max_searches], max(0, len(all_pairs) - max_searches)


async def run_searches(
    source: SerpApiGoogleHotelsSource, pairs: List[Tuple[Destination, StayRequest]]
) -> Tuple[List[Deal], List[str]]:
    deals: List[Deal] = []
    errors: List[str] = []
    for i, (dest, stay) in enumerate(pairs, 1):
        print(f"  [{i}/{len(pairs)}] {dest.name}  {stay.check_in} -> {stay.check_out}", file=sys.stderr)
        try:
            deals.extend(await source.search(dest, stay))
        except DealSourceException as exc:
            # One failing search must not stop the run.
            errors.append(f"{dest.name} {stay.check_in}: {exc}")
    return deals, errors


def format_table(ranked: List[RankedDeal], top: int) -> str:
    if not ranked:
        return "No deals found."
    lines = []
    for n, r in enumerate(ranked[:top], 1):
        d, p, stay = r.deal, r.deal.price, r.deal.stay_request
        stars = f"{d.star_rating:.0f}*" if d.star_rating else "  "
        rating = f"{d.user_review_score:.1f}/10" if d.user_review_score else "no rating"
        extras = [d.room_offer.board.value.replace("_", " ")]
        if d.room_offer.has_spa_amenity:
            extras.append("spa")
        if p.discount_percent:
            extras.append(f"{p.discount_percent:.0f}% below usual")
        tax = f" + ~EUR {p.estimated_tourist_tax_eur:.0f} tourist tax" if p.estimated_tourist_tax_eur else ""
        lines.append(
            f"{n:>2}. [{r.score:>5.1f}] {d.property_name} {stars}  ({rating})\n"
            f"      {r.destination.name}, {r.destination.region} | "
            f"~{r.destination.transit_route.total_hours:.1f}h by train/bus | "
            f"{stay.check_in:%a %d %b} -> {stay.check_out:%a %d %b} ({stay.nights} nights)\n"
            f"      EUR {p.total_eur:.0f} total (EUR {p.price_per_night_eur:.0f}/night){tax} | {', '.join(extras)}"
        )
        if r.flags:
            lines.append(f"      ! {'; '.join(r.flags)}")
        if d.booking_url:
            lines.append(f"      {d.booking_url}")
    return "\n".join(lines)


def to_json(ranked: List[RankedDeal], top: int) -> str:
    return json.dumps(
        [
            {
                "score": r.score,
                "flags": r.flags,
                "travel_hours": r.destination.transit_route.total_hours,
                "deal": r.deal.model_dump(mode="json"),
            }
            for r in ranked[:top]
        ],
        indent=2,
        ensure_ascii=False,
    )


def make_demo_source() -> SerpApiGoogleHotelsSource:
    """Source that answers every search with the recorded sample response."""
    import httpx

    fixture = json.loads(DEMO_FIXTURE.read_text(encoding="utf-8"))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=fixture))
    return SerpApiGoogleHotelsSource(
        api_key="demo-offline",
        rate_limit_rps=0,
        http_client=httpx.AsyncClient(transport=transport),
    )


@dataclass
class RunPlan:
    party: PartyComposition
    max_hours: float
    budget: Optional[float]
    max_searches: int
    destinations: List[Destination]
    stays: List[StayRequest]


def make_plan(args: argparse.Namespace, settings: Settings, today: date) -> RunPlan:
    party = PartyComposition(adults=settings.party_adults, children_ages=settings.party_children_ages)
    max_hours = args.max_hours or settings.max_travel_hours
    catalogue = StaticCatalogue()
    if args.demo:
        destinations = [catalogue.to_destination(catalogue.get(DEMO_DESTINATION))]
        stays = [StayRequest(check_in=DEMO_STAY[0], check_out=DEMO_STAY[1], party=party)]
    else:
        destinations = select_destinations(catalogue, args, max_hours)
        stays = upcoming_weekend_stays(
            today, args.weekends or settings.search_weekends, party,
            include_long_weekends=settings.include_long_weekends,
        )
    return RunPlan(
        party=party,
        max_hours=max_hours,
        budget=args.budget if args.budget is not None else settings.budget_total_eur,
        max_searches=args.max_searches or settings.max_searches_per_run,
        destinations=destinations,
        stays=stays,
    )


def make_source(args: argparse.Namespace, settings: Settings) -> Optional[SerpApiGoogleHotelsSource]:
    if args.demo:
        return make_demo_source()
    if not settings.serpapi_api_key:
        print("SERPAPI_API_KEY is not set. Put it in .env (see .env.example), "
              "or try --demo / --plan.", file=sys.stderr)
        return None
    return SerpApiGoogleHotelsSource(
        api_key=settings.serpapi_api_key,
        cache_dir=settings.cache_dir,
        cache_ttl_hours=settings.cache_ttl_hours,
        tax_exempt_under_age=settings.tourist_tax_exempt_under_age,
    )


def print_plan_summary(plan: RunPlan, pairs: list, skipped: int) -> None:
    party_desc = f"{plan.party.adults} adults + children aged {', '.join(map(str, plan.party.children_ages))}"
    print(f"Party: {party_desc} | max ~{plan.max_hours:g}h by train/bus from Santa Margherita Ligure",
          file=sys.stderr)
    print(f"Destinations: {len(plan.destinations)} | weekends: "
          + ", ".join(f"{s.check_in:%d %b}{' (long)' if s.is_long_weekend else ''}" for s in plan.stays),
          file=sys.stderr)
    print(f"Searches: {len(pairs)}" + (f" ({skipped} skipped by --max-searches {plan.max_searches}; "
                                        "narrow with --terme-only/--region/--destination)" if skipped else ""),
          file=sys.stderr)


def deliver(alerts: List[Alert], notifiers: List[Notifier]) -> bool:
    """Send to every channel; True if at least one channel delivered."""
    delivered = False
    for n in notifiers:
        try:
            n.send(alerts)
            delivered = True
        except NotifierError as exc:
            logger.error("%s: %s", n.name, exc)
    return delivered


SEARCH_CURSOR_KEY = "search_cursor"


def run_tick(
    args: argparse.Namespace,
    settings: Settings,
    store: DealStore,
    notifiers: List[Notifier],
    today: date,
) -> int:
    """One search -> store -> alert cycle. Returns a process exit code."""
    plan = make_plan(args, settings, today)
    cursor = int(store.get_meta(SEARCH_CURSOR_KEY) or 0)
    pairs, skipped = plan_searches(plan.destinations, plan.stays, plan.max_searches, offset=cursor)
    print_plan_summary(plan, pairs, skipped)
    if not pairs:
        print("Nothing to search: no destination matches the filters.", file=sys.stderr)
        return 1
    source = make_source(args, settings)
    if source is None:
        return 2

    deals, errors = asyncio.run(run_searches(source, pairs))
    store.set_meta(SEARCH_CURSOR_KEY, str(cursor + len(pairs)))
    store.record_observations(deals)
    ranked = rank_deals(deals, {d.id: d for d in plan.destinations}, plan.max_hours, plan.budget)
    alerts = select_alerts(
        ranked, store.last_alerted_price, today,
        min_score=settings.alert_min_score,
        min_price_drop_eur=settings.alert_min_price_drop_eur,
        max_alerts=settings.alert_max_per_message,
    )

    print(f"{len(deals)} offers seen, {len(ranked)} within budget, {len(alerts)} to alert"
          + (f", {len(errors)} search(es) failed" if errors else ""), file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)

    if alerts:
        if args.dry_run:
            ConsoleNotifier().send(alerts)
        elif deliver(alerts, notifiers):
            for a in alerts:
                store.record_alert(a.ranked.deal.id, a.kind.value, a.ranked.deal.price.total_eur)
        else:
            logger.error("No channel delivered the alerts; they will be retried next run.")
    return 0 if deals or not errors else 1


def run_service(args: argparse.Namespace, settings: Settings) -> int:
    notifiers: List[Notifier] = [] if args.dry_run else notifiers_from_settings(settings)
    if not args.dry_run and not notifiers:
        print("No alert channel configured (TELEGRAM_* or SMTP_* in .env); "
              "alerts are printed here.", file=sys.stderr)
        notifiers = [ConsoleNotifier()]
    # Demo runs keep their own history so they never mark real deals as alerted.
    db_path = settings.db_path.with_name("demo.db") if args.demo else settings.db_path

    with DealStore(db_path) as store:
        if not args.daemon:
            return run_tick(args, settings, store, notifiers, date.today())

        interval = settings.poll_interval_hours * 3600
        print(f"Running every {settings.poll_interval_hours:g}h; Ctrl+C to stop.", file=sys.stderr)
        try:
            while True:
                print(f"\n--- run at {datetime.now():%Y-%m-%d %H:%M} ---", file=sys.stderr)
                try:
                    run_tick(args, settings, store, notifiers, date.today())
                except Exception:
                    # Keep the service alive; the next run may succeed.
                    logger.exception("Run failed")
                delay = interval + random.uniform(0, settings.poll_jitter_minutes * 60)
                print(f"Next run at {datetime.now() + timedelta(seconds=delay):%Y-%m-%d %H:%M}",
                      file=sys.stderr)
                time.sleep(delay)
        except KeyboardInterrupt:
            print("Stopped.", file=sys.stderr)
            return 0


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    # httpx logs full request URLs at INFO, and those carry the SerpApi key and Telegram token.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings: Settings = get_settings()

    if (args.once or args.daemon) and (args.plan or args.json):
        raise SystemExit("--plan/--json can't be combined with --once/--daemon")
    if args.dry_run and not (args.once or args.daemon):
        raise SystemExit("--dry-run only applies to --once/--daemon")
    if args.demo:
        print("DEMO MODE: recorded sample response, not live prices.\n", file=sys.stderr)
    if args.once or args.daemon:
        return run_service(args, settings)

    plan = make_plan(args, settings, date.today())
    pairs, skipped = plan_searches(plan.destinations, plan.stays, plan.max_searches)
    print_plan_summary(plan, pairs, skipped)

    if args.plan:
        for dest, stay in pairs:
            print(f"  {stay.check_in} -> {stay.check_out}  {dest.name} ({dest.region}, "
                  f"~{dest.transit_route.total_hours:.1f}h)")
        return 0

    if not pairs:
        print("Nothing to search: no destination matches the filters.", file=sys.stderr)
        return 1

    source = make_source(args, settings)
    if source is None:
        return 2

    deals, errors = asyncio.run(run_searches(source, pairs))
    ranked = rank_deals(deals, {d.id: d for d in plan.destinations}, plan.max_hours, plan.budget)

    print("", file=sys.stderr)
    print(to_json(ranked, args.top) if args.json else format_table(ranked, args.top))
    if errors:
        print(f"\n{len(errors)} search(es) failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
    return 0 if deals or not errors else 1


if __name__ == "__main__":
    sys.exit(main())
