from __future__ import annotations

from analysis.indicators import infer_trend
from models.analysis_models import AgentFinding, MarketSnapshotData

from .runner import BaseAgent


class FundamentalTechnicalAgent(BaseAgent):
    name = 'fundamental_technical'
    soul_file = 'fundamental_technical.md'

    def run(self, snapshot: MarketSnapshotData) -> AgentFinding:
        trend = infer_trend(snapshot.price, snapshot.technicals)
        evidence = [f'ราคา: {snapshot.price:,.2f}']
        for label, key in [('RSI(14)', 'rsi'), ('SMA(50)', 'sma50'), ('P/E', 'pe_ratio'), ('Yield', 'div_yield')]:
            value = getattr(snapshot, key, None) if key in ('pe_ratio', 'div_yield') else snapshot.technicals.get(key)
            if value not in (None, '', 'N/A', '-'):
                evidence.append(f'{label}: {value}')
        fallback = AgentFinding(
            agent_name=self.name,
            summary=f'แนวโน้มเชิงเทคนิคอยู่ในระดับ {trend} ตามข้อมูลที่มี',
            outlook=trend,
            evidence=evidence,
            risks=['ตัวชี้วัดทางเทคนิคไม่ทำนายราคาในอนาคต'],
            confidence='Medium' if len(evidence) >= 3 else 'Low',
        )
        return self.try_ai({'snapshot': snapshot.dict()}, AgentFinding, fallback)
