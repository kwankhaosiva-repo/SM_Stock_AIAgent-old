from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    title: str
    url: str = ''
    published_at: str = ''
    source_type: str = 'news'


class MarketSnapshotData(BaseModel):
    symbol: str
    price: float
    pe_ratio: Optional[float] = None
    div_yield: Optional[float] = None
    history: List[float] = Field(default_factory=list)
    technicals: Dict[str, Any] = Field(default_factory=dict)
    sources: List[SourceItem] = Field(default_factory=list)
    provider: str = 'legacy'
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    freshness_minutes: int = 0


class AgentFinding(BaseModel):
    agent_name: str
    summary: str
    outlook: str = 'Neutral'
    evidence: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    confidence: str = 'Low'


class AdviceOutput(BaseModel):
    outlook: str = 'Neutral'
    summary: str
    reasons: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    next_watch_items: List[str] = Field(default_factory=list)
    confidence: str = 'Low'
    disclaimer: str = 'ข้อมูลนี้เป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุนเฉพาะบุคคล'


class ReviewResult(BaseModel):
    status: str = 'approve'
    notes: List[str] = Field(default_factory=list)
    corrected_advice: Optional[AdviceOutput] = None
