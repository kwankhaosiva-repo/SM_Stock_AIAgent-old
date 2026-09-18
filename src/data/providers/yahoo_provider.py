from __future__ import annotations

from typing import Any, Dict

from .base import MarketDataProvider


class YahooMarketDataProvider(MarketDataProvider):
    """Fetches market metrics and historical daily closes using yfinance."""

    name: str = 'yahoo_finance'

    def fetch(self, symbol: str) -> Dict[str, Any]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is required for YahooMarketDataProvider") from exc

        clean_symbol = symbol.upper().strip()
        ticker = yf.Ticker(clean_symbol)

        price = 0.0
        pe_ratio = None
        div_yield = None
        market_cap = "N/A"
        history_prices = []

        try:
            hist = ticker.history(period="60d")
            if not hist.empty and 'Close' in hist:
                history_prices = [float(p) for p in hist['Close'].dropna().tolist()]
                if history_prices:
                    price = history_prices[-1]
        except Exception as exc:
            print(f"[YahooProvider] Error fetching history for {clean_symbol}: {exc}")

        try:
            info = ticker.info or {}
            current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            if current_price:
                price = float(current_price)

            pe = info.get('trailingPE') or info.get('forwardPE')
            if pe and str(pe) not in ('N/A', 'None'):
                pe_ratio = float(pe)

            yd = info.get('dividendYield')
            if yd is not None and str(yd) not in ('N/A', 'None'):
                div_yield = float(yd) * 100 if float(yd) < 1.0 else float(yd)

            cap = info.get('marketCap')
            if cap:
                market_cap = f"{cap / 1e6:,.2f} M"
        except Exception as exc:
            print(f"[YahooProvider] Error fetching info for {clean_symbol}: {exc}")

        if price <= 0 and history_prices:
            price = history_prices[-1]

        if price <= 0:
            raise ValueError(f"Could not retrieve valid price for {clean_symbol}")

        return {
            "price": price,
            "pe_ratio": pe_ratio,
            "div_yield": div_yield,
            "history": history_prices,
            "market_cap": market_cap,
            "technicals": {
                "market_cap": market_cap,
            },
        }
