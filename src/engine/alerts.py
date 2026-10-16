"""Which ranked deals are worth an alert: new ones, or ones meaningfully cheaper than last alerted."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Callable, List, Optional

from src.core.models import AlertType
from src.engine.ranking import RankedDeal


@dataclass
class Alert:
    ranked: RankedDeal
    kind: AlertType
    previous_price_eur: Optional[float] = None
    # Result of the live train/bus check, e.g. "fastest Fri train/bus 4h50 (Google)"
    transit_note: Optional[str] = None


def select_alerts(
    ranked: List[RankedDeal],
    last_alerted_price: Callable[[str], Optional[float]],
    today: date,
    min_score: float,
    min_price_drop_eur: float,
    max_alerts: int,
) -> List[Alert]:
    """
    ranked is best-first. A deal is alerted when its score is at least min_score and either
    it was never alerted (NEW_DEAL), or its price is at least min_price_drop_eur below the
    price in its last alert (PRICE_DROP). Stays starting today or earlier are skipped.
    """
    alerts: List[Alert] = []
    for r in ranked:
        if len(alerts) >= max_alerts:
            break
        if r.score < min_score or r.deal.stay_request.check_in <= today:
            continue
        previous = last_alerted_price(r.deal.id)
        price = r.deal.price.total_eur
        if previous is None:
            alerts.append(Alert(r, AlertType.NEW_DEAL))
        elif previous - price >= min_price_drop_eur:
            alerts.append(Alert(r, AlertType.PRICE_DROP, previous_price_eur=previous))
    return alerts
