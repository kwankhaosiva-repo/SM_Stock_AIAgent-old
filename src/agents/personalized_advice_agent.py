from __future__ import annotations

from typing import Dict

from models.analysis_models import AdviceOutput, AgentFinding, MarketSnapshotData

from .runner import BaseAgent


class PersonalizedAdviceAgent(BaseAgent):
    name = 'personalized_advice'
    soul_file = 'personalized_advice.md'

    def run(self, snapshot: MarketSnapshotData, news: AgentFinding, analysis: AgentFinding, profile: Dict[str, str]) -> AdviceOutput:
        reasons = (analysis.evidence + news.evidence)[:3]
        fallback = AdviceOutput(
            outlook=analysis.outlook,
            summary=f'มุมมอง {analysis.outlook}: {analysis.summary}',
            reasons=reasons,
            risks=list(dict.fromkeys(analysis.risks + news.risks))[:3],
            next_watch_items=['ติดตามผลประกอบการหรือข่าวสารที่มีผลต่อธุรกิจ', 'ตรวจสอบราคากับระดับความเสี่ยงที่ตั้งไว้'],
            confidence=analysis.confidence,
        )
        payload = {
            'snapshot': snapshot.dict(),
            'news_finding': news.dict(),
            'analysis_finding': analysis.dict(),
            'user_profile': profile,
        }
        return self.try_ai(payload, AdviceOutput, fallback)
