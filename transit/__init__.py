"""Transit reachability module for Weekend Getaway Deals."""

from transit.static_catalogue import (
    StaticCatalogue,
    get_catalogue,
    is_reachable,
    get_travel_time,
)

__all__ = [
    "StaticCatalogue",
    "get_catalogue",
    "is_reachable",
    "get_travel_time",
]
