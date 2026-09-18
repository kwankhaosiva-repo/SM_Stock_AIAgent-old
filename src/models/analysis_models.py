from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CompatibleBaseModel(BaseModel):
    """Base model that supports both Pydantic v1 and v2 methods."""

    def to_dict(self) -> Dict[str, Any]:
        if hasattr(self, 'model_dump'):
            return self.model_dump()
        return self.dict()

    # Pydantic v2 deprecation shim for callers expecting .dict()
    def dict(self, *args, **kwargs) -> Dict[str, Any]:
        if hasattr(self, 'model_dump'):
            return self.model_dump(*args, **kwargs)
        return super().dict(*args, **kwargs)

    @classmethod
    def from_dict(cls, data: Any):
        if hasattr(cls, 'model_validate'):
            return cls.model_validate(data)
        return cls.parse_obj(data)

    @classmethod
    def parse_obj(cls, obj: Any):
        if hasattr(cls, 'model_validate'):
            return cls.model_validate(obj)
        return super().parse_obj(obj)


class SourceItem(CompatibleBaseModel):
    title: str
    url: str = ''
    published_at: str = ''
    source_type: str = 'news'
    relevance: str = ''


class MarketSnapshotData(CompatibleBaseModel):
    symbol: str
    price: float
    pe_ratio: Optional[float] = None
    div_yield: Optional[float] = None
    history: List[float] = Field(default_factory=list)
    technicals: Dict[str, Any] = Field(default_factory=dict)
    sources: List[SourceItem] = Field(default_factory=list)
    provider: str = 'legacy'
    collected_at: datetime = Field(default_factory=_utcnow)
    freshness_minutes: int = 0


class AgentFinding(CompatibleBaseModel):
    agent_name: str
    summary: str
    outlook: str = 'Neutral'  # Positive, Neutral, Cautious
    evidence: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    confidence: str = 'Low'  # High, Medium, Low


class AdviceOutput(CompatibleBaseModel):
    outlook: str = 'Neutral'  # Positive, Neutral, Cautious
    summary: str
    reasons: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    next_watch_items: List[str] = Field(default_factory=list)
    confidence: str = 'Low'  # High, Medium, Low
    disclaimer: str = 'ข้อมูลนี้เป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุนเฉพาะบุคคล'


class ReviewResult(CompatibleBaseModel):
    status: str = 'approve'  # approve, revise, reject
    notes: List[str] = Field(default_factory=list)
    corrected_advice: Optional[AdviceOutput] = None


class DailyDigestData(CompatibleBaseModel):
    summary: str
    attention_count: int = 0
    top_stocks: List[Dict[str, Any]] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_utcnow)
