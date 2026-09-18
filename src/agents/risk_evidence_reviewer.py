from __future__ import annotations

from models.analysis_models import AdviceOutput, MarketSnapshotData, ReviewResult

from .runner import BaseAgent


class RiskEvidenceReviewer(BaseAgent):
    name = 'risk_evidence_reviewer'
    soul_file = 'risk_evidence_reviewer.md'

    def run(self, snapshot: MarketSnapshotData, advice: AdviceOutput) -> ReviewResult:
        notes = []

        # Deterministic checks
        if snapshot.freshness_minutes > 15:
            notes.append(f"ข้อมูลตลาดมีความเก่า {snapshot.freshness_minutes} นาที ควรตรวจสอบราคาเรียลไทม์")

        if not advice.reasons:
            notes.append("รายงานขาดเหตุผลเชิงประจักษ์ประกอบการพิจารณา")

        if not snapshot.sources:
            notes.append("ไม่มีแหล่งข่าวอ้างอิงประกอบรายงานนี้")

        # Check for overconfident or forbidden words
        forbidden = ['การันตี', 'กำไรแน่นอน', 'รวยเร็ว', '100%']
        for word in forbidden:
            if word in advice.summary or any(word in r for r in advice.reasons):
                notes.append(f"ตรวจพบถ้อยคำชี้นำเกินจริง ({word})")

        status = 'approve'
        if any('ตรวจพบถ้อยคำชี้นำ' in n for n in notes):
            status = 'reject'
        elif notes:
            status = 'revise'

        fallback = ReviewResult(status=status, notes=notes)
        payload = {
            'snapshot': snapshot.to_dict(),
            'advice': advice.to_dict(),
            'deterministic_notes': notes,
        }
        return self.try_ai(payload, ReviewResult, fallback)
