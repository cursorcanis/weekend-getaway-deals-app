"""Static Reachability Catalogue Engine.

Origin: Santa Margherita Ligure–Portofino railway station.
Provides verified public transit travel times and reachability checks
against data/destinations.yaml.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


DEFAULT_CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "data" / "destinations.yaml"


class StaticCatalogue:
    """In-memory index and query engine for catalogued Italian destinations."""

    def __init__(self, catalogue_path: Optional[Path | str] = None) -> None:
        self.path = Path(catalogue_path or DEFAULT_CATALOGUE_PATH)
        self._raw_data: Dict[str, Any] = {}
        self._destinations_by_id: Dict[str, Dict[str, Any]] = {}
        self._origin_info: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        """Load or reload the destinations YAML file into memory."""
        if not self.path.exists():
            raise FileNotFoundError(f"Catalogue file not found at: {self.path}")

        with open(self.path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self._raw_data = data
        self._origin_info = data.get("origin", {})
        destinations = data.get("destinations", [])
        self._destinations_by_id = {d["id"]: d for d in destinations if "id" in d}

    @property
    def origin(self) -> Dict[str, Any]:
        """Return origin station metadata."""
        return self._origin_info

    @property
    def all_destinations(self) -> List[Dict[str, Any]]:
        """Return all catalogued destinations."""
        return list(self._destinations_by_id.values())

    def get(self, destination_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve destination details by unique slug id."""
        return self._destinations_by_id.get(destination_id)

    @functools.lru_cache(maxsize=256)
    def get_travel_time(self, destination_id: str, use_fastest: bool = False) -> Optional[float]:
        """Get cached typical (or fastest) travel time in hours from Santa Margherita Ligure."""
        dest = self.get(destination_id)
        if not dest:
            return None
        key = "fastest_travel_time_hours" if use_fastest else "typical_travel_time_hours"
        return float(dest.get(key, 0.0))

    def is_reachable(self, destination_id: str, max_hours: float = 7.0) -> bool:
        """Check whether destination is reachable within the configured travel time limit."""
        t = self.get_travel_time(destination_id, use_fastest=True)
        if t is None:
            return False
        return t <= max_hours

    def filter(
        self,
        region: Optional[str] = None,
        is_terme: Optional[bool] = None,
        category: Optional[str] = None,
        max_hours: Optional[float] = None,
        last_mile_bus_required: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Filter destinations by region, terme status, category, max travel hours, etc."""
        results = []
        for dest in self.all_destinations:
            if region and dest.get("region", "").lower() != region.lower():
                continue
            if is_terme is not None and dest.get("is_terme") != is_terme:
                continue
            if category and dest.get("category", "").lower() != category.lower():
                continue
            if last_mile_bus_required is not None and dest.get("last_mile_bus_required") != last_mile_bus_required:
                continue
            if max_hours is not None:
                typical = float(dest.get("typical_travel_time_hours", 999.0))
                fastest = float(dest.get("fastest_travel_time_hours", 999.0))
                if min(typical, fastest) > max_hours:
                    continue
            results.append(dest)
        return results

    def get_summary(self) -> Dict[str, Any]:
        """Generate high-level counts and breakdown by region and category."""
        by_region: Dict[str, int] = {}
        terme_by_region: Dict[str, int] = {}
        by_category: Dict[str, int] = {}

        total = len(self._destinations_by_id)
        terme_count = 0

        for dest in self.all_destinations:
            reg = dest.get("region", "Unknown")
            cat = dest.get("category", "unknown")
            is_terme = dest.get("is_terme", False)

            by_region[reg] = by_region.get(reg, 0) + 1
            by_category[cat] = by_category.get(cat, 0) + 1

            if is_terme:
                terme_count += 1
                terme_by_region[reg] = terme_by_region.get(reg, 0) + 1

        return {
            "total_destinations": total,
            "terme_count": terme_count,
            "non_terme_count": total - terme_count,
            "by_region": by_region,
            "terme_by_region": terme_by_region,
            "by_category": by_category,
        }


# Global singleton instance
_default_catalogue: Optional[StaticCatalogue] = None


def get_catalogue() -> StaticCatalogue:
    """Return the global StaticCatalogue singleton instance."""
    global _default_catalogue
    if _default_catalogue is None:
        _default_catalogue = StaticCatalogue()
    return _default_catalogue


def is_reachable(destination_id: str, max_hours: float = 7.0) -> bool:
    """Convenience function: check if destination is reachable in <= max_hours."""
    return get_catalogue().is_reachable(destination_id, max_hours=max_hours)


def get_travel_time(destination_id: str, use_fastest: bool = False) -> Optional[float]:
    """Convenience function: get typical travel time in hours."""
    return get_catalogue().get_travel_time(destination_id, use_fastest=use_fastest)
