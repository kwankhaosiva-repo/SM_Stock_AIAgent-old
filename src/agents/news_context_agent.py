from __future__ import annotations

from models.analysis_models import AgentFinding, MarketSnapshotData

from .runner import BaseAgent


class NewsContextAgent(BaseAgent):
    name = 'news_context'
    soul_file = 'news_context.md'

    def run(self, snapshot: MarketSnapshotData) -> AgentFinding:
        titles = [item.title for item in snapshot.sources[:3]]
        fallback = AgentFinding(
            agent_name=self.name,
            summary='พบข่าวที่เกี่ยวข้อง' if titles else 'ไม่มีข่าวที่ตรวจสอบได้ในรอบนี้',
            outlook='Neutral',
            evidence=titles,
            risks=['ข่าวอาจไม่ครอบคลุมทุกแหล่งข้อมูล'] if not titles else [],
            confidence='Low' if not titles else 'Medium',
        )
        return self.try_ai({'snapshot': snapshot.dict()}, AgentFinding, fallback)
