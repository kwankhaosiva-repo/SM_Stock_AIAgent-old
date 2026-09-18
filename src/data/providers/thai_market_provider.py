from __future__ import annotations

from typing import Any, Dict

from .base import MarketDataProvider
from .yahoo_provider import YahooMarketDataProvider


class ThaiMarketDataProvider(MarketDataProvider):
    """Fetches Thai market data via Settrade / Thai helpers, falling back to yfinance."""

    name: str = 'thai_market_set'

    def __init__(self):
        self._yahoo_fallback = YahooMarketDataProvider()

    def fetch(self, symbol: str) -> Dict[str, Any]:
        clean_symbol = symbol.upper().strip()
        if not clean_symbol.endswith('.BK'):
            clean_symbol = f"{clean_symbol}.BK"

        # Try Settrade / ThaiStockHelper if available
        try:
            from thai_stock_helper import SettradeHelper
            helper = SettradeHelper()
            quote = helper.get_quote(clean_symbol)
            candles = helper.get_candles(clean_symbol, limit=60)
            if quote and quote.get('price', 0) > 0:
                history = candles.get('history', []) if candles else []
                return {
                    "price": float(quote['price']),
                    "pe_ratio": float(quote.get('pe', 0)) if quote.get('pe') else None,
                    "div_yield": float(quote.get('yield', 0)) if quote.get('yield') else None,
                    "history": [float(p) for p in history if p is not None],
                    "technicals": {
                        "market_cap": "N/A",
                    },
                }
        except Exception as exc:
            print(f"[ThaiMarketProvider] Settrade helper unavailable or error: {exc}. Using Yahoo fallback.")

        # Fallback to Yahoo with .BK suffix
        return self._yahoo_fallback.fetch(clean_symbol)
