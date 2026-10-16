"""Deal source adapters module."""

from src.sources.base import BaseDealSource, DealSourceException
from src.sources.serpapi import SerpApiGoogleHotelsSource

__all__ = [
    "BaseDealSource",
    "DealSourceException",
    "SerpApiGoogleHotelsSource",
]
