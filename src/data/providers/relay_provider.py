"""Local data-relay provider.

Forwards market-data requests to a small agent running on a residential
machine (Cloudflare Tunnel URL in DATA_RELAY_URL). Residential IPs are not
subject to Yahoo's datacenter rate limiting, so this acts as the anti-block
fallback for both Thai and global symbols.
"""
from __future__ import annotations

from typing import Any, Dict

import requests

from config import Config

from .base import MarketDataProvider, ProviderSkip


class RelayMarketDataProvider(MarketDataProvider):
    """Fetch market data through the user's home relay agent."""

    name = 'local_relay'

    def fetch(self, symbol: str) -> Dict[str, Any]:
        base = (Config.DATA_RELAY_URL or '').rstrip('/')
        if not base:
            raise ProviderSkip('DATA_RELAY_URL not configured')

        try:
            resp = requests.get(
                f'{base}/quote/{symbol.upper().strip()}',
                timeout=25,
            )
        except requests.RequestException as exc:
            raise ProviderSkip(f'relay unreachable: {exc}') from exc

        if resp.status_code != 200:
            raise ProviderSkip(f'relay HTTP {resp.status_code}')

        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderSkip('relay returned invalid JSON') from exc

        if not data or not data.get('price'):
            raise ProviderSkip('relay returned no price')

        return {
            'price': float(data['price']),
            'pe_ratio': data.get('pe_ratio'),
            'div_yield': data.get('div_yield'),
            'history': [float(p) for p in (data.get('history') or []) if p is not None],
            'technicals': data.get('technicals') or {},
        }
