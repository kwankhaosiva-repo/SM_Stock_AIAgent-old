"""Settrade Open API provider for Thai-listed equities (official SET feed).

Thai-only by design: rejects non-.BK symbols so the resolver can fall through
to global providers. Skips gracefully (raises ProviderSkip) when
SETTRADE_APP_ID/SECRET are absent so the chain falls back to yfinance without
any error surfacing to users.
"""
from __future__ import annotations

from typing import Any, Dict

from config import Config

from .base import MarketDataProvider, ProviderSkip


class SettradeOpenDataProvider(MarketDataProvider):
    """Official SET market data via Settrade Open API (sandbox or live)."""

    name = 'settrade_open'

    def _context(self):
        try:
            from settrade.openapi import InvestorContext
        except ImportError as exc:
            raise ProviderSkip('settrade SDK not installed (pip install settrade)') from exc

        if not Config.SETTRADE_APP_ID or not Config.SETTRADE_APP_SECRET:
            raise ProviderSkip('SETTRADE_APP_ID/SECRET not configured')

        return InvestorContext(
            broker_id=Config.SETTRADE_BROKER_ID,
            app_code=Config.SETTRADE_APP_CODE,
            app_id=Config.SETTRADE_APP_ID,
            app_secret=Config.SETTRADE_APP_SECRET,
            is_auto_queue=not Config.SETTRADE_IS_SANDBOX,
        )

    def fetch(self, symbol: str) -> Dict[str, Any]:
        clean = symbol.upper().strip()
        if not clean.endswith('.BK'):
            # Thai-only provider: let other providers handle global symbols.
            raise ProviderSkip('non-Thai symbol')

        ctx = self._context()

        quote = self._get_quote(ctx, clean)
        history = self._get_history(ctx, clean)

        price = float(quote.get('last_price') or 0.0)
        if price <= 0 and history:
            price = history[-1]
        if price <= 0:
            raise ProviderSkip('no valid price from Settrade')

        return {
            'price': price,
            'pe_ratio': self._optional_float(quote.get('pe')),
            'div_yield': self._optional_float(quote.get('yield')),
            'history': history,
            'technicals': {'market_cap': 'N/A'},
        }

    # ------------------------------------------------------------------ API

    def _get_quote(self, ctx, symbol: str) -> Dict[str, Any]:
        try:
            # Market Report API: last price + fundamentals per symbol.
            resp = ctx.market_report.get_sec_info(symbol=symbol.replace('.BK', ''))
            data = resp.data if hasattr(resp, 'data') else resp
            if isinstance(data, list) and data:
                data = data[0]
            if not isinstance(data, dict):
                return {}
            return {
                'last_price': data.get('last_price') or data.get('lastPrice') or data.get('price'),
                'pe': data.get('p_e') or data.get('pe'),
                'yield': data.get('yield'),
            }
        except Exception as exc:
            print(f'[SettradeOpen] sec_info error for {symbol}: {exc}')
            return {}

    def _get_history(self, ctx, symbol: str, limit: int = 60) -> list:
        try:
            resp = ctx.market_report.get_candlestick(
                symbol=symbol.replace('.BK', ''),
                interval='1d', server_type='M', group_type='E', period=limit,
            )
            data = resp.data if hasattr(resp, 'data') else resp
            candles = data if isinstance(data, list) else (data or {}).get('candlestick', [])
            closes = []
            for candle in candles:
                close = candle.get('c') if isinstance(candle, dict) else None
                if close is not None:
                    closes.append(float(close))
            return closes
        except Exception as exc:
            print(f'[SettradeOpen] candlestick error for {symbol}: {exc}')
            return []

    @staticmethod
    def _optional_float(value):
        try:
            return float(value) if value not in (None, '', 'N/A', '-', 0) else None
        except (TypeError, ValueError):
            return None
