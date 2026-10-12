"""Tests for Static Reachability Catalogue and data/destinations.yaml."""

from pathlib import Path
import pytest
import yaml

from transit.static_catalogue import (
    StaticCatalogue,
    get_catalogue,
    is_reachable,
    get_travel_time,
)


CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "data" / "destinations.yaml"


def test_destinations_yaml_file_exists():
    """Verify that data/destinations.yaml exists and is non-empty."""
    assert CATALOGUE_PATH.exists()
    assert CATALOGUE_PATH.stat().st_size > 0


def test_destinations_yaml_valid_syntax():
    """Verify data/destinations.yaml parses cleanly as valid YAML."""
    with open(CATALOGUE_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "origin" in data
    assert "destinations" in data
    assert data["origin"]["station_name"] == "Santa Margherita Ligure-Portofino"
    assert len(data["destinations"]) >= 50


def test_destinations_required_fields():
    """Every destination must contain all required fields with realistic constraints."""
    with open(CATALOGUE_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    required_keys = {
        "id",
        "name",
        "region",
        "is_terme",
        "primary_attraction",
        "fastest_travel_time_hours",
        "typical_travel_time_hours",
        "changes",
        "transit_mode",
        "transit_operators",
        "last_mile_bus_required",
        "notes",
    }

    seen_ids = set()

    for dest in data["destinations"]:
        for key in required_keys:
            assert key in dest, f"Destination {dest.get('name', 'UNKNOWN')} missing field '{key}'"

        # Unique id slug
        dest_id = dest["id"]
        assert dest_id not in seen_ids, f"Duplicate destination id: '{dest_id}'"
        seen_ids.add(dest_id)

        # Transit bounds (must fit within 8h soft limit)
        fastest = dest["fastest_travel_time_hours"]
        typical = dest["typical_travel_time_hours"]
        assert fastest > 0, f"Invalid fastest time for {dest_id}"
        assert typical >= fastest, f"Typical time {typical} must be >= fastest {fastest} for {dest_id}"
        assert fastest <= 8.0, f"Fastest travel time {fastest} exceeds soft limit 8h for {dest_id}"
        assert typical <= 8.0, f"Typical travel time {typical} exceeds soft limit 8h for {dest_id}"

        # Transfers count
        assert dest["changes"] >= 0

        # Transit mode
        assert dest["transit_mode"] in {"train", "train+bus", "bus"}

        # Operators
        assert len(dest["transit_operators"]) > 0


def test_terme_destinations_coverage():
    """Verify that major thermal destinations from the spec are present and flagged."""
    catalogue = StaticCatalogue(CATALOGUE_PATH)
    terme_destinations = catalogue.filter(is_terme=True)
    assert len(terme_destinations) >= 15

    terme_ids = {d["id"] for d in terme_destinations}
    expected_terme = [
        "acqui-terme",
        "montecatini-terme",
        "salsomaggiore-terme",
        "abano-terme",
        "montegrotto-terme",
        "sirmione",
        "bormio",
        "merano",
        "pre-saint-didier",
        "bagno-vignoni",
        "chianciano-terme",
        "rapolano-terme",
        "saturnia",
        "casciana-terme",
        "terme-di-genova",
    ]

    for expected in expected_terme:
        assert expected in terme_ids, f"Expected terme destination '{expected}' not found in catalogue"


def test_regions_coverage():
    """Verify that all target regions are covered."""
    catalogue = StaticCatalogue(CATALOGUE_PATH)
    summary = catalogue.get_summary()

    expected_regions = {
        "Liguria",
        "Piemonte",
        "Lombardia",
        "Emilia-Romagna",
        "Toscana",
        "Veneto",
        "Trentino-Alto Adige",
        "Valle d'Aosta",
        "Umbria",
        "Lazio",
    }

    covered_regions = set(summary["by_region"].keys())
    for region in expected_regions:
        assert region in covered_regions, f"Region '{region}' has no catalogued destinations"


def test_reachability_queries():
    """Verify reachability helper methods."""
    assert is_reachable("acqui-terme", max_hours=7.0) is True
    assert is_reachable("monterosso-al-mare", max_hours=1.0) is True
    assert is_reachable("merano", max_hours=6.0) is False  # fastest ~6.8h
    assert is_reachable("merano", max_hours=7.0) is True
    assert is_reachable("non-existent-place", max_hours=10.0) is False

    t = get_travel_time("acqui-terme")
    assert t is not None and 2.0 <= t <= 2.5
