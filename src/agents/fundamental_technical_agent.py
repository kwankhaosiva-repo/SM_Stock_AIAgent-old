from __future__ import annotations

from analysis.indicators import infer_trend
from models.analysis_models import AgentFinding, MarketSnapshotData

from .runner import BaseAgent


class FundamentalTechnicalAgent(BaseAgent):
    name = 'fundamental_technical'
    soul_file = 'fundamental_technical.md'

    def run(self, snapshot: MarketSnapshotData) -> AgentFinding:
        trend = infer_trend(snapshot.price, snapshot.technicals)
        evidence = [f'ราคาล่าสุด: {snapshot.price:,.2f}']

        labels = [
            ('RSI(14)', 'rsi'),
            ('SMA(20)', 'sma20'),
            ('SMA(50)', 'sma50'),
            ('ความผันผวน 30 วัน', 'volatility'),
            ('แนวรับ', 'support'),
            ('แนวต้าน', 'resistance'),
            ('P/E', 'pe_ratio'),
            ('อัตราเงินปันผล', 'div_yield'),
        ]

        for label, key in labels:
            if key in ('pe_ratio', 'div_yield'):
                val = getattr(snapshot, key, None)
                if val is not None and val != 0:
                    unit = "%" if key == 'div_yield' else " เท่า"
                    evidence.append(f'{label}: {val:.2f}{unit}')
            else:
                val = snapshot.technicals.get(key)
                if val not in (None, '', 'N/A', '-'):
                    evidence.append(f'{label}: {val}')

        fallback = AgentFinding(
            agent_name=self.name,
            summary=f'มุมมองทางเทคนิคและปัจจัยพื้นฐานประเมินอยู่ในระดับ {trend} ตามสถิติและตัวชี้วัดปัจจุบัน',
            outlook=trend,
            evidence=evidence[:4],
            risks=['ตัวชี้วัดทางสถิติในอดีตไม่ได้รับประกันทิศทางราคาในอนาคต'],
            confidence='Medium' if len(evidence) >= 3 else 'Low',
        )

        payload = {
            'symbol': snapshot.symbol,
            'price': snapshot.price,
            'pe_ratio': snapshot.pe_ratio,
            'div_yield': snapshot.div_yield,
            'technicals': snapshot.technicals,
            'trend': trend,
        }
        return self.try_ai(payload, AgentFinding, fallback)
