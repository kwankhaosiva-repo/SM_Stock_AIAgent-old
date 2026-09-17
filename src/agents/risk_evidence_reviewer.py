from __future__ import annotations

from models.analysis_models import AdviceOutput, MarketSnapshotData, ReviewResult

from .runner import BaseAgent


class RiskEvidenceReviewer(BaseAgent):
    name = 'risk_evidence_reviewer'
    soul_file = 'risk_evidence_reviewer.md'

    def run(self, snapshot: MarketSnapshotData, advice: AdviceOutput) -> ReviewResult:
        notes = []
        if snapshot.freshness_minutes > 15:
            notes.append('ข้อมูลตลาดอาจไม่ใหม่พอสำหรับการตัดสินใจทันที')
        if not advice.reasons:
            notes.append('รายงานไม่มีเหตุผลประกอบที่ตรวจสอบได้')
        if not snapshot.sources:
            notes.append('ไม่มีแหล่งข่าวในรายงานนี้')
        fallback = ReviewResult(status='revise' if notes else 'approve', notes=notes)
        payload = {'snapshot': snapshot.dict(), 'advice': advice.dict()}
        return self.try_ai(payload, ReviewResult, fallback)
