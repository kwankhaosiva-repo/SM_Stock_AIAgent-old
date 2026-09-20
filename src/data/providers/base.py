from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from models.analysis_models import SourceItem


class ProviderSkip(Exception):
    """Raised by a provider that cannot serve this request; the resolver
    silently falls through to the next provider in the chain."""


class MarketDataProvider(ABC):
    """Abstract base provider for equity price, fundamental, and historical data."""

    name: str = 'base_market_provider'

    @abstractmethod
    def fetch(self, symbol: str) -> Dict[str, Any]:
        """Return dict with price, pe_ratio, div_yield, history (prices list), technicals."""
        raise NotImplementedError


class NewsDataProvider(ABC):
    """Abstract base provider for news and macro context."""

    name: str = 'base_news_provider'

    @abstractmethod
    def fetch_news(self, symbol: str) -> List[SourceItem]:
        """Return structured list of SourceItems for company and macro news."""
        raise NotImplementedError
