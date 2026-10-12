"""Filtering and transparent scoring of normalized deals."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.core.models import BoardType, Deal, Destination


@dataclass
class RankedDeal:
    deal: Deal
    destination: Destination
    score: float
    flags: List[str] = field(default_factory=list)


def deal_flags(deal: Deal, destination: Destination) -> List[str]:
    """Warnings the family should see before booking."""
    flags: List[str] = []
    room = deal.room_offer
    if room.max_guests is None:
        flags.append("room for 4 not confirmed")
    elif room.max_guests < deal.stay_request.party.total_guests:
        flags.append(f"room sleeps only {room.max_guests}")
    if not room.terme_child_policy_compliant:
        flags.append(f"spa min age {destination.minimum_child_age_spa}: youngest child barred")
    if destination.transit_route.is_bus_last_mile:
        flags.append("last mile by bus")
    return flags


def score_deal(
    deal: Deal,
    destination: Destination,
    cheapest_per_night: float,
    max_travel_hours: float,
) -> float:
    """
    Score 0-100, higher is better:
      price      50  cheapest per-night price in this run / this deal's per-night price
      discount   15  Google's "% less than usual", capped at 40%
      reviews    15  review score (0-10) / 10
      travel     10  1 - travel hours / max travel hours
      extras     10  breakfast +5, spa the whole family can use +5
    """
    price = deal.price
    price_pts = 50.0 * min(1.0, cheapest_per_night / price.price_per_night_eur)
    discount_pts = 15.0 * min(price.discount_percent or 0.0, 40.0) / 40.0
    review_pts = 15.0 * (deal.user_review_score or 0.0) / 10.0
    hours = destination.transit_route.total_hours
    travel_pts = 10.0 * max(0.0, 1.0 - hours / max_travel_hours) if max_travel_hours else 0.0
    extras_pts = 0.0
    if deal.room_offer.board != BoardType.ROOM_ONLY:
        extras_pts += 5.0
    if deal.room_offer.has_spa_amenity and deal.room_offer.terme_child_policy_compliant:
        extras_pts += 5.0
    return round(price_pts + discount_pts + review_pts + travel_pts + extras_pts, 1)


def rank_deals(
    deals: List[Deal],
    destinations: Dict[str, Destination],
    max_travel_hours: float,
    budget_total_eur: Optional[float] = None,
) -> List[RankedDeal]:
    """Drop over-budget deals, keep the best price per property+dates, score and sort."""
    best: Dict[str, Deal] = {}
    for deal in deals:
        if budget_total_eur is not None and deal.price.total_eur > budget_total_eur:
            continue
        current = best.get(deal.id)
        if current is None or deal.price.total_eur < current.price.total_eur:
            best[deal.id] = deal

    if not best:
        return []

    cheapest = min(d.price.price_per_night_eur for d in best.values())
    ranked: List[RankedDeal] = []
    for deal in best.values():
        destination = destinations[deal.destination_id]
        score = score_deal(deal, destination, cheapest, max_travel_hours)
        ranked.append(
            RankedDeal(
                deal=deal.model_copy(update={"score": score}),
                destination=destination,
                score=score,
                flags=deal_flags(deal, destination),
            )
        )
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked
