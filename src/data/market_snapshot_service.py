from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from config import Config
from database import MarketSnapshot, SessionLocal, SourceDocument
from models.analysis_models import MarketSnapshotData, SourceItem

from .providers import LegacyMarketDataProvider, MarketDataProvider


class MarketSnapshotService:
    def __init__(self, provider: Optional[MarketDataProvider] = None, db_session=None):
        self.provider = provider or LegacyMarketDataProvider()
        self.db = db_session

    def get_or_collect(self, symbol: str) -> tuple[MarketSnapshotData, Optional[int]]:
        symbol = symbol.upper().strip()
        owns_session = self.db is None
        db = self.db or SessionLocal()
        try:
            now = datetime.utcnow()
            cached = (
                db.query(MarketSnapshot)
                .filter(MarketSnapshot.symbol == symbol, MarketSnapshot.expires_at > now)
                .order_by(MarketSnapshot.collected_at.desc())
                .first()
            )
            if cached:
                snapshot = self._from_record(cached)
                snapshot.freshness_minutes = max(0, int((now - cached.collected_at).total_seconds() // 60))
                return snapshot, cached.id

            raw = self.provider.fetch(symbol)
            snapshot = self._build_snapshot(symbol, raw)
            record = MarketSnapshot(
                symbol=symbol,
                provider=self.provider.name,
                data_json=json.dumps(snapshot.dict(), default=str),
                collected_at=snapshot.collected_at,
                expires_at=snapshot.collected_at + timedelta(minutes=Config.MARKET_SNAPSHOT_TTL_MINUTES),
            )
            db.add(record)
            db.flush()
            for source in snapshot.sources:
                db.add(SourceDocument(
                    snapshot_id=record.id,
                    title=source.title,
                    url=source.url,
                    published_at=source.published_at,
                    source_type=source.source_type,
                ))
            db.commit()
            return snapshot, record.id
        finally:
            if owns_session:
                db.close()

    def _from_record(self, record: MarketSnapshot) -> MarketSnapshotData:
        payload = json.loads(record.data_json)
        return MarketSnapshotData.parse_obj(payload)

    def _build_snapshot(self, symbol: str, raw: Dict[str, Any]) -> MarketSnapshotData:
        sources = []
        for item in raw.get('news', []):
            if isinstance(item, dict):
                sources.append(SourceItem(
                    title=str(item.get('headline') or item.get('title') or 'Untitled news'),
                    url=str(item.get('url') or ''),
                    published_at=str(item.get('published_at') or item.get('summary') or ''),
                ))
            elif item:
                sources.append(SourceItem(title=str(item)))
        return MarketSnapshotData(
            symbol=symbol,
            price=float(raw.get('price') or 0),
            pe_ratio=self._optional_float(raw.get('pe_ratio')),
            div_yield=self._optional_float(raw.get('div_yield')),
            history=[float(x) for x in raw.get('history', []) if x is not None],
            technicals=raw.get('technicals') or {},
            sources=sources,
            provider=self.provider.name,
        )

    @staticmethod
    def _optional_float(value):
        try:
            return float(value) if value not in (None, '', 'N/A') else None
        except (TypeError, ValueError):
            return None
