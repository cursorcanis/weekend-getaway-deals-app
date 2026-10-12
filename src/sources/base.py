"""Base contract for hotel and thermal bath deal source adapters."""

from abc import ABC, abstractmethod
from typing import List
from src.core.models import Deal, Destination, StayRequest


class DealSourceException(Exception):
    """Base exception for source adapter failures."""
    pass


class BaseDealSource(ABC):
    """Abstract interface for all hotel and terme data sources."""

    def __init__(self, name: str, rate_limit_rps: float = 1.0) -> None:
        self.name = name
        self.rate_limit_rps = rate_limit_rps

    @abstractmethod
    async def search(
        self,
        destination: Destination,
        stay: StayRequest
    ) -> List[Deal]:
        """
        Search offers for a given destination and stay dates for the family party.

        Args:
            destination: Target destination containing geographic and station details.
            stay: Check-in, check-out dates and party composition.

        Returns:
            A list of validated, normalized Deal domain instances.

        Raises:
            DealSourceException: When rate limits, network timeouts, or schema mismatches occur.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify API keys, credentials, or connectivity."""
        pass
