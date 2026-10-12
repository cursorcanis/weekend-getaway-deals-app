"""Centralized application configuration (environment variables / .env)."""

from __future__ import annotations
from pathlib import Path
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Party (children ages as JSON in env, e.g. PARTY_CHILDREN_AGES=[15,7])
    party_adults: int = 2
    party_children_ages: List[int] = Field(default_factory=lambda: [15, 7])

    # Reachability from Santa Margherita Ligure (typical door-to-door hours)
    max_travel_hours: float = 7.0

    # Dates
    search_weekends: int = 4
    include_long_weekends: bool = True

    # Budget: total stay price for the whole family; None = no ceiling
    budget_total_eur: Optional[float] = None

    # SerpApi (paid per search)
    serpapi_api_key: Optional[str] = None
    max_searches_per_run: int = 20
    cache_ttl_hours: float = 12.0
    cache_dir: Path = PROJECT_ROOT / "data" / "cache" / "serpapi"

    # Tourist tax estimate: children younger than this are assumed exempt
    tourist_tax_exempt_under_age: int = 14


def get_settings() -> Settings:
    return Settings()
