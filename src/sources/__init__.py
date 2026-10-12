"""Deal source adapters module."""

from src.sources.base import BaseDealSource, DealSourceException
from src.sources.serpapi import SerpApiGoogleHotelsSource
from src.sources.terme_stub import DirectTermeScraperSource

__all__ = [
    "BaseDealSource",
    "DealSourceException",
    "SerpApiGoogleHotelsSource",
    "DirectTermeScraperSource",
]
