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

    # Also search the named terme resorts in data/terme_resorts.yaml (one search each per weekend)
    include_resort_targets: bool = True

    # Terme offer pages (data/terme_offer_pages.yaml): alert on new package titles.
    # Each page is fetched at most once per offers_fetch_interval_hours.
    terme_offers_enabled: bool = True
    offers_fetch_interval_hours: float = 12.0

    # Live train/bus check before alerting (Google Routes API, transit mode). Off unless
    # the key is set. Deals whose fastest Friday journey exceeds max_travel_hours_soft are
    # not alerted. Results are cached for transit_cache_days.
    google_maps_api_key: Optional[str] = None
    max_travel_hours_soft: float = 8.0
    friday_departure_time: str = "14:00"
    transit_cache_days: int = 30

    # Tourist tax estimate: children younger than this are assumed exempt
    tourist_tax_exempt_under_age: int = 14

    # Continuous mode (--daemon). Each tick spends up to max_searches_per_run searches,
    # rotating through the full (destination, weekend) list across ticks.
    db_path: Path = PROJECT_ROOT / "data" / "deals.db"
    poll_interval_hours: float = 12.0
    poll_jitter_minutes: float = 15.0

    # Alerts: only deals scoring at least this, and re-alert only after a drop this large
    alert_min_score: float = 60.0
    alert_min_price_drop_eur: float = 30.0
    alert_max_per_message: int = 10

    # Telegram: alerts are sent when both are set
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # Email: alerts are sent when SMTP_HOST and ALERT_EMAIL_TO are set (comma-separated list)
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    alert_email_from: Optional[str] = None
    alert_email_to: Optional[str] = None


def get_settings() -> Settings:
    return Settings()
