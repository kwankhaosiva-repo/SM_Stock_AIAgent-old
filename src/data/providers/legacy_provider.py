from __future__ import annotations

from typing import Any, Dict

from .base import MarketDataProvider


class LegacyMarketDataProvider(MarketDataProvider):
    """Adapter around current helpers until a licensed production feed is selected."""

    name = 'legacy-yfinance-and-rss'

    def fetch(self, symbol: str) -> Dict[str, Any]:
        # Import lazily: command-line jobs and tests can use this module without
        # initializing Gemini until actual market data is requested.
        from analyzer import AnalysisEngine

        data = AnalysisEngine().fetch_data(symbol)
        if not data:
            raise ValueError(f'No market data available for {symbol}')
        return data
