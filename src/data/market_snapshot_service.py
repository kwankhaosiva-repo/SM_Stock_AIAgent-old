from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from config import Config
from database import MarketSnapshot, SessionLocal, SourceDocument
from models.analysis_models import MarketSnapshotData, SourceItem

from .providers import (
    LegacyMarketDataProvider,
    MarketDataProvider,
    NewsDataProvider,
    NewsProvider,
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
        self.db = db_session

    def _resolve_market_provider(self, symbol: str) -> MarketDataProvider:
        if self._market_provider is not None:
            return self._market_provider
        clean_symbol = symbol.upper().strip()
        if clean_symbol.endswith('.BK'):
            return self._thai_provider
        return self._yahoo_provider

    def get_or_collect(self, symbol: str) -> Tuple[MarketSnapshotData, Optional[int]]:
        symbol = symbol.upper().strip()
        owns_session = self.db is None
        db = self.db or SessionLocal()
        try:
            now = _utcnow_naive()
            # 1. Check for valid cached snapshot reusable across all users
            cached = (
                db.query(MarketSnapshot)
                .filter(MarketSnapshot.symbol == symbol, MarketSnapshot.expires_at > now)
                .order_by(MarketSnapshot.collected_at.desc())
                .first()
            )
            if cached:
                snapshot = self._from_record(cached)
                snapshot.freshness_minutes = max(
                    0, int((now - cached.collected_at).total_seconds() // 60)
                )
                return snapshot, cached.id

            # 2. Collect fresh data
            provider = self._resolve_market_provider(symbol)
            raw = provider.fetch(symbol)

            # Collect news sources
            news_sources = []
            try:
                news_sources = self._news_provider.fetch_news(symbol)
            except Exception as exc:
                print(f"[SnapshotService] News fetch warning for {symbol}: {exc}")

            snapshot = self._build_snapshot(symbol, raw, news_sources, provider.name)
            
            # Save to database
            ttl_minutes = getattr(Config, 'MARKET_SNAPSHOT_TTL_MINUTES', 15)
            collected_at_naive = _utcnow_naive()
            record = MarketSnapshot(
                symbol=symbol,
                provider=provider.name,
                data_json=json.dumps(snapshot.to_dict(), default=str),
                collected_at=collected_at_naive,
                expires_at=collected_at_naive + timedelta(minutes=ttl_minutes),
            )
            db.add(record)
            db.flush()

            for source in snapshot.sources:
                db.add(
                    SourceDocument(
                        snapshot_id=record.id,
                        title=source.title,
                        url=source.url,
                        published_at=source.published_at,
                        source_type=source.source_type,
                    )
                )
            db.commit()
            return snapshot, record.id
        finally:
            if owns_session:
                db.close()

    def _from_record(self, record: MarketSnapshot) -> MarketSnapshotData:
        payload = json.loads(record.data_json)
        return MarketSnapshotData.from_dict(payload)

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
