from __future__ import annotations

from models.analysis_models import AgentFinding, MarketSnapshotData

from .runner import BaseAgent


class NewsContextAgent(BaseAgent):
    name = 'news_context'
    soul_file = 'news_context.md'

    def run(self, snapshot: MarketSnapshotData) -> AgentFinding:
        sources = snapshot.sources[:5]
        evidence = []
        for s in sources:
            label = f"{s.title}"
            if s.url:
                label += f" ({s.url})"
            evidence.append(label)

        fallback = AgentFinding(
            agent_name=self.name,
            summary='พบข่าวที่เกี่ยวข้องกับบริษัทและสภาวะตลาด' if evidence else 'ไม่มีข่าวสารที่ตรวจสอบได้ในรอบนี้',
            outlook='Neutral',
            evidence=evidence[:3],
            risks=['ข่าวสารอาจยังไม่ครอบคลุมเหตุการณ์ล่าสุดทั้งหมด'] if evidence else ['ไม่มีแหล่งข่าวสนับสนุนในรอบวิเคราะห์นี้'],
            confidence='Medium' if evidence else 'Low',
        )

        payload = {
            'symbol': snapshot.symbol,
            'sources': [s.to_dict() for s in sources],
            'collected_at': str(snapshot.collected_at),
        }
        return self.try_ai(payload, AgentFinding, fallback)
