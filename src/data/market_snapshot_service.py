from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from config import Config
import store
from models.analysis_models import MarketSnapshotData, SourceItem

from .providers import (
    LegacyMarketDataProvider,
    MarketDataProvider,
    NewsDataProvider,
    NewsProvider,
    ProviderSkip,
    RelayMarketDataProvider,
    SettradeOpenDataProvider,
    ThaiMarketDataProvider,
    YahooMarketDataProvider,
)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MarketSnapshotService:
    def __init__(
        self,
        market_provider: Optional[MarketDataProvider] = None,
        news_provider: Optional[NewsDataProvider] = None,
        db_session=None,
    ):
        self._market_provider = market_provider
        self._news_provider = news_provider or NewsProvider()
        self._yahoo_provider = YahooMarketDataProvider()
        self._thai_provider = ThaiMarketDataProvider()
        self._settrade_provider = SettradeOpenDataProvider()
        self._relay_provider = RelayMarketDataProvider()

    def _resolve_market_provider(self, symbol: str) -> MarketDataProvider:
        """Single-provider resolution kept for explicit injection/tests.
        For automatic resolution, _fetch_with_fallback walks the chain."""
        if self._market_provider is not None:
            return self._market_provider
        clean_symbol = symbol.upper().strip()
        if clean_symbol.endswith('.BK'):
            return self._thai_provider
        return self._yahoo_provider

    def _provider_chain(self, symbol: str):
        """Anti-block fallback chain.

        Thai (.BK): official Settrade feed -> home relay (residential IP)
                    -> Settrade helper/yfinance -> plain yfinance
        Global:     home relay -> yfinance
        A provider raising ProviderSkip (no key, wrong symbol type, blocked)
        falls through to the next one.
        """
        if self._market_provider is not None:
            return [self._market_provider]
        clean_symbol = symbol.upper().strip()
        if clean_symbol.endswith('.BK'):
            return [
                self._settrade_provider,
                self._relay_provider,
                self._thai_provider,
                self._yahoo_provider,
            ]
        return [self._relay_provider, self._yahoo_provider]

    def _fetch_with_fallback(self, symbol: str) -> tuple[Dict[str, Any], str]:
        errors: list[str] = []
        for provider in self._provider_chain(symbol):
            try:
                return provider.fetch(symbol), provider.name
            except ProviderSkip as exc:
                print(f'[SnapshotService] {provider.name} skip: {exc}')
            except Exception as exc:
                errors.append(f'{provider.name}: {exc}')
                print(f'[SnapshotService] {provider.name} failed: {exc}')
        raise ValueError(
            f'All market data providers failed for {symbol}: ' + ' | '.join(errors)
        )

    def get_or_collect(self, symbol: str) -> Tuple[MarketSnapshotData, Optional[str]]:
        symbol = symbol.upper().strip()
        # 1. Check for valid cached snapshot reusable across all users
        cached = store.get_valid_snapshot(symbol)
        if cached:
            snapshot = MarketSnapshotData.from_dict(cached['data'])
            collected_at = cached['collected_at']
            if collected_at.tzinfo is None:
                collected_at = collected_at.replace(tzinfo=timezone.utc)
            snapshot.freshness_minutes = max(
                0, int((datetime.now(timezone.utc) - collected_at).total_seconds() // 60)
            )
            return snapshot, cached['id']

        # 2. Collect fresh data via the anti-block provider chain
        raw, provider_name = self._fetch_with_fallback(symbol)

        # Collect news sources
        news_sources = []
        try:
            news_sources = self._news_provider.fetch_news(symbol)
        except Exception as exc:
            print(f"[SnapshotService] News fetch warning for {symbol}: {exc}")

        snapshot = self._build_snapshot(symbol, raw, news_sources, provider_name)

        ttl_minutes = getattr(Config, 'MARKET_SNAPSHOT_TTL_MINUTES', 15)
        snap_id = store.save_snapshot(
            symbol, snapshot.to_dict(), provider_name, ttl_minutes,
        )
        store.save_source_documents(snap_id, [
            {
                'title': source.title,
                'url': source.url,
                'published_at': source.published_at,
                'source_type': source.source_type,
            }
            for source in snapshot.sources
        ])
        return snapshot, snap_id

    def _build_snapshot(
        self,
        symbol: str,
        raw: Dict[str, Any],
        news_sources: list[SourceItem],
        provider_name: str,
    ) -> MarketSnapshotData:
        from analysis.indicators import calculate_indicators

        history = [float(x) for x in raw.get('history', []) if x is not None]
        technicals = raw.get('technicals') or {}

        # Precompute indicators from historical candles if available
        if history:
            computed_indicators = calculate_indicators(history)
            for k, v in computed_indicators.items():
                if k not in technicals or technicals[k] in ('N/A', '-', None):
                    technicals[k] = v

        sources = list(news_sources)
        # Also incorporate raw news items if passed in raw dict
        if not sources and 'news' in raw:
            for item in raw['news']:
                if isinstance(item, dict):
                    sources.append(
                        SourceItem(
                            title=str(item.get('headline') or item.get('title') or 'Untitled news'),
                            url=str(item.get('url') or ''),
                            published_at=str(item.get('published_at') or ''),
                            source_type='news',
                        )
                    )
                elif item:
                    sources.append(SourceItem(title=str(item)))

        return MarketSnapshotData(
            symbol=symbol,
            price=float(raw.get('price') or 0.0),
            pe_ratio=self._optional_float(raw.get('pe_ratio')),
            div_yield=self._optional_float(raw.get('div_yield')),
            history=history,
            technicals=technicals,
            sources=sources,
            provider=provider_name,
            collected_at=_utcnow_naive(),
            freshness_minutes=0,
        )

    @staticmethod
    def _optional_float(value):
        try:
            return float(value) if value not in (None, '', 'N/A', '-') else None
        except (TypeError, ValueError):
            return None
