from __future__ import annotations

from typing import Dict, List, Optional

from models.analysis_models import AdviceOutput, AgentFinding, MarketSnapshotData

from .runner import BaseAgent


class PersonalizedAdviceAgent(BaseAgent):
    name = 'personalized_advice'
    soul_file = 'personalized_advice.md'

    def run(
        self,
        snapshot: MarketSnapshotData,
        news: AgentFinding,
        analysis: AgentFinding,
        profile: Dict[str, str],
        review_notes: Optional[List[str]] = None,
    ) -> AdviceOutput:
        # Build deterministic fallback
        combined_reasons = []
        if analysis.evidence:
            combined_reasons.extend(analysis.evidence[:2])
        if news.evidence:
            combined_reasons.append(news.evidence[0])
        if not combined_reasons:
            combined_reasons = [f"ราคาอ้างอิง: {snapshot.price:,.2f}"]

        combined_risks = list(dict.fromkeys(analysis.risks + news.risks))
        if not combined_risks:
            combined_risks = ['ควรติดตามภาวะตลาดและข่าวสารบริษัทอย่างสม่ำเสมอ']

        outlook = analysis.outlook if analysis.outlook in ('Positive', 'Neutral', 'Cautious') else 'Neutral'

        fallback = AdviceOutput(
            outlook=outlook,
            summary=f"มุมมอง {outlook}: {analysis.summary}",
            reasons=combined_reasons[:3],
            risks=combined_risks[:3],
            next_watch_items=[
                'ติดตามรายงานผลประกอบการและแถลงการณ์ของผู้บริหาร',
                'ตรวจสอบระดับราคาเทียบกับแนวรับและแนวต้านสำคัญ',
            ],
            confidence=analysis.confidence if analysis.confidence != 'Low' else news.confidence,
        )

        # If the reviewer asked for revisions, fold the notes into the risks and
        # re-synthesize with them surfaced so the LLM corrects the advice.
        revision_context = list(review_notes or [])
        if revision_context:
            fallback.risks = list(dict.fromkeys(fallback.risks + revision_context))[:3]

        payload = {
            'symbol': snapshot.symbol,
            'snapshot': snapshot.to_dict(),
            'news_finding': news.to_dict(),
            'analysis_finding': analysis.to_dict(),
            'user_profile': profile,
        }
        if revision_context:
            payload['reviewer_revision_notes'] = revision_context
            payload['revision_instruction'] = (
                'ผู้ตรวจสอบขอให้ปรับปรุงคำแนะนำก่อนหน้า โปรดแก้ไขข้อความให้ตรงกับข้อติดใน reviewer_revision_notes และส่งคืน JSON ใหม่'
            )
        return self.try_ai(payload, AdviceOutput, fallback)
