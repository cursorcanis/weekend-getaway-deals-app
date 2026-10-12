"""Weekend date generation: Friday check-in, Sunday check-out, long weekends."""

from __future__ import annotations
from datetime import date, timedelta
from typing import List, Set

from src.core.models import PartyComposition, StayRequest

FRIDAY = 4


def easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def italian_public_holidays(year: int) -> Set[date]:
    """National public holidays in Italy (excludes local patron-saint days)."""
    fixed = {
        date(year, 1, 1),    # Capodanno
        date(year, 1, 6),    # Epifania
        date(year, 4, 25),   # Liberazione
        date(year, 5, 1),    # Festa del Lavoro
        date(year, 6, 2),    # Festa della Repubblica
        date(year, 8, 15),   # Ferragosto
        date(year, 10, 4),   # San Francesco (national holiday again from 2026)
        date(year, 11, 1),   # Ognissanti
        date(year, 12, 8),   # Immacolata
        date(year, 12, 25),  # Natale
        date(year, 12, 26),  # Santo Stefano
    }
    fixed.add(easter_sunday(year) + timedelta(days=1))  # Pasquetta
    return fixed


def next_friday(today: date) -> date:
    """First Friday strictly after today (a same-day check-in is too late to plan)."""
    days_ahead = (FRIDAY - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


def upcoming_weekend_stays(
    today: date,
    count: int,
    party: PartyComposition,
    include_long_weekends: bool = True,
) -> List[StayRequest]:
    """
    One stay per upcoming weekend: Friday check-in, Sunday check-out (2 nights).
    When the Monday after is a public holiday and long weekends are enabled,
    check-out moves to Monday (3 nights) so Sunday night is covered.
    """
    stays: List[StayRequest] = []
    friday = next_friday(today)
    for _ in range(count):
        monday = friday + timedelta(days=3)
        long_weekend = include_long_weekends and monday in italian_public_holidays(monday.year)
        check_out = monday if long_weekend else friday + timedelta(days=2)
        stays.append(
            StayRequest(
                check_in=friday,
                check_out=check_out,
                party=party,
                is_long_weekend=long_weekend,
            )
        )
        friday += timedelta(days=7)
    return stays
