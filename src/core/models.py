"""Core domain models for Weekend Getaway Deals."""

from __future__ import annotations
from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl, PositiveInt, NonNegativeFloat, model_validator


class BoardType(str, Enum):
    ROOM_ONLY = "room_only"
    BREAKFAST = "breakfast"
    HALF_BOARD = "half_board"
    FULL_BOARD = "full_board"
    ALL_INCLUSIVE = "all_inclusive"


class DestinationCategory(str, Enum):
    TERME = "terme"
    SPA_RESORT = "spa_resort"
    SEASIDE = "seaside"
    LAKE = "lake"
    MOUNTAIN = "mountain"
    ART_CITY = "art_city"
    COUNTRYSIDE = "countryside"


class TransitMode(str, Enum):
    TRAIN = "train"
    BUS = "bus"
    TRAIN_PLUS_BUS = "train_plus_bus"


class AlertType(str, Enum):
    NEW_DEAL = "new_deal"
    PRICE_DROP = "price_drop"
    DIGEST = "digest"


class PartyComposition(BaseModel):
    """Specific family party: 2 adults, 2 children (15yo and 7yo)."""
    adults: PositiveInt = Field(default=2, description="Number of adults")
    children_ages: List[int] = Field(
        default=[15, 7],
        description="Ages of children. Note: 15-year-old must be treated as adult for pricing."
    )

    @property
    def total_guests(self) -> int:
        return self.adults + len(self.children_ages)

    @property
    def adults_for_pricing(self) -> int:
        """Many Italian systems treat >=14 or >=15 as adult."""
        return self.adults + sum(1 for age in self.children_ages if age >= 14)


class TransitSegment(BaseModel):
    mode: TransitMode
    operator: str = Field(description="e.g. Trenitalia, Italo, Tiemme, AMT")
    departure_station: str
    arrival_station: str
    duration_minutes: PositiveInt
    line_code: Optional[str] = None


class TransitRoute(BaseModel):
    origin: str = Field(default="Santa Margherita Ligure-Portofino")
    destination_name: str
    destination_station: str
    total_duration_minutes: PositiveInt = Field(description="Total door-to-door transit time")
    transfers: int = Field(default=0, ge=0)
    segments: List[TransitSegment] = Field(default_factory=list)
    is_bus_last_mile: bool = Field(default=False)
    bus_frequency_notes: Optional[str] = None
    estimated: bool = Field(default=False, description="True if based on catalogue estimates")

    @property
    def total_hours(self) -> float:
        return round(self.total_duration_minutes / 60.0, 2)


class Destination(BaseModel):
    id: str = Field(description="Unique slug, e.g. 'abano-terme', 'sirmione', 'bologna'")
    name: str
    region: str = Field(description="Italian region, e.g. 'Veneto', 'Toscana'")
    category: DestinationCategory
    primary_station: str = Field(description="Nearest railway station")
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    transit_route: TransitRoute
    has_thermal_baths: bool = Field(default=False)
    minimum_child_age_spa: Optional[int] = Field(
        default=None,
        description="Minimum age admitted into thermal pools/wellness centers if restricted"
    )
    notes: Optional[str] = None


class StayRequest(BaseModel):
    check_in: date
    check_out: date
    party: PartyComposition = Field(default_factory=PartyComposition)
    is_long_weekend: bool = Field(default=False)

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @model_validator(mode="after")
    def validate_dates(self) -> StayRequest:
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        if self.nights not in (2, 3):
            raise ValueError(f"Weekend stays must be 2 or 3 nights, got {self.nights}")
        return self


class RoomOffer(BaseModel):
    name: str = Field(description="Room title, e.g. 'Family Suite' or '2 x Superior Double'")
    room_count: PositiveInt = Field(default=1, description="Number of rooms booked to fit party")
    max_guests: PositiveInt = Field(description="Total capacity of the room allocation")
    board: BoardType = Field(default=BoardType.ROOM_ONLY)
    terme_included: bool = Field(default=False, description="Thermal spa access included in rate")
    terme_child_policy_compliant: bool = Field(
        default=True,
        description="False if the 7yo is excluded from spa facilities"
    )
    cancellation_policy: Optional[str] = None


class PriceBreakdown(BaseModel):
    total_eur: float = Field(gt=0, description="Total stay price for all 4 persons")
    price_per_night_eur: float = Field(gt=0)
    taxes_included: bool = Field(default=True)
    estimated_tourist_tax_eur: Optional[float] = Field(
        default=None,
        description="Tassa di soggiorno estimated for 2 nights"
    )
    original_price_eur: Optional[float] = Field(
        default=None,
        description="Baseline/strike-through price if on sale"
    )

    @property
    def discount_percent(self) -> Optional[float]:
        if self.original_price_eur and self.original_price_eur > self.total_eur:
            return round((1 - self.total_eur / self.original_price_eur) * 100, 1)
        return None


class Deal(BaseModel):
    id: str = Field(description="Hash fingerprint of source_id + property_id + dates + room")
    source_id: str = Field(description="Source identifier, e.g. 'serpapi_google_hotels'")
    property_id: str
    property_name: str
    star_rating: Optional[float] = None
    user_review_score: Optional[float] = Field(default=None, description="Normalized score 0-10")
    review_count: Optional[int] = None
    destination_id: str
    stay_request: StayRequest
    room_offer: RoomOffer
    price: PriceBreakdown
    booking_url: HttpUrl
    score: NonNegativeFloat = Field(default=0.0, description="Computed rank score")
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
