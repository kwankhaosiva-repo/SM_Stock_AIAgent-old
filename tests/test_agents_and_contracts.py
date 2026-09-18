import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from agents import (
    FundamentalTechnicalAgent,
    NewsContextAgent,
    PersonalizedAdviceAgent,
    RiskEvidenceReviewer,
)
from models.analysis_models import (
    AdviceOutput,
    AgentFinding,
    MarketSnapshotData,
    ReviewResult,
    SourceItem,
)


class MockLLMService:
    def __init__(self, canned_response=None):
        self.canned = canned_response

    def generate_json(self, _prompt, _payload):
        return self.canned


class AgentsAndContractsTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = MarketSnapshotData(
            symbol='TEST',
            price=150.0,
            pe_ratio=18.5,
            div_yield=3.2,
            history=[100.0 + i for i in range(30)],
            technicals={'rsi': '65.20', 'sma50': '140.00', 'volatility': '15.4%'},
            sources=[
                SourceItem(title='Earnings report beat forecast', url='https://example.com/1'),
                SourceItem(title='Dividend announced', url='https://example.com/2'),
            ],
            freshness_minutes=5,
        )

    def test_news_agent_fallback_and_ai_parsing(self):
        # Offline fallback
        offline_agent = NewsContextAgent(MockLLMService(None))
        res_offline = offline_agent.run(self.snapshot)
        self.assertIsInstance(res_offline, AgentFinding)
        self.assertTrue(len(res_offline.evidence) >= 2)

        # AI simulated output
        ai_response = {
            'agent_name': 'news_context',
            'summary': 'บริษัทรายงานกำไรเติบโตเด่นชัด',
            'outlook': 'Positive',
            'evidence': ['กำไรโต 20%'],
            'risks': ['ต้นทุนพลังงาน'],
            'confidence': 'High',
        }
        ai_agent = NewsContextAgent(MockLLMService(ai_response))
        res_ai = ai_agent.run(self.snapshot)
        self.assertEqual(res_ai.outlook, 'Positive')
        self.assertEqual(res_ai.confidence, 'High')

    def test_fundamental_technical_agent(self):
        agent = FundamentalTechnicalAgent(MockLLMService(None))
        res = agent.run(self.snapshot)
        self.assertIsInstance(res, AgentFinding)
        self.assertIn(res.outlook, ('Positive', 'Neutral', 'Cautious'))
        self.assertTrue(any('150.00' in e for e in res.evidence))

    def test_personalized_advice_agent(self):
        news = AgentFinding(
            agent_name='news_context',
            summary='ข่าวเชิงบวก',
            outlook='Positive',
            evidence=['ข่าวผลประกอบการเติบโต'],
        )
        tech = AgentFinding(
            agent_name='fundamental_technical',
            summary='เทคนิคขาขึ้น',
            outlook='Positive',
            evidence=['ราคาเหนือ SMA50', 'RSI 65'],
        )
        agent = PersonalizedAdviceAgent(MockLLMService(None))
        profile = {'core_strategy': 'Value', 'risk_appetite': 'Medium'}
        advice = agent.run(self.snapshot, news, tech, profile)

        self.assertIsInstance(advice, AdviceOutput)
        self.assertEqual(advice.outlook, 'Positive')
        self.assertTrue(len(advice.reasons) >= 1)
        self.assertTrue(len(advice.next_watch_items) >= 1)

    def test_risk_reviewer_flags_forbidden_words_and_stale_data(self):
        # Stale data flag
        stale_snapshot = self.snapshot.model_copy() if hasattr(self.snapshot, 'model_copy') else self.snapshot.copy()
        stale_snapshot.freshness_minutes = 30

        reviewer = RiskEvidenceReviewer(MockLLMService(None))
        advice = AdviceOutput(
            outlook='Positive',
            summary='แนวโน้มสดใส',
            reasons=['กำไรโต'],
            risks=['ความผันผวน'],
        )
        res = reviewer.run(stale_snapshot, advice)
        self.assertIn('revise', res.status)
        self.assertTrue(any('เก่า 30 นาที' in n for n in res.notes))

        # Forbidden word flag
        bad_advice = AdviceOutput(
            outlook='Positive',
            summary='หุ้นตัวนี้ การันตี ผลตอบแทนแน่นอน',
            reasons=['กำไร 100%'],
        )
        res_bad = reviewer.run(self.snapshot, bad_advice)
        self.assertEqual(res_bad.status, 'reject')

    def test_openclaw_markdown_loading(self):
        agents = [
            NewsContextAgent(),
            FundamentalTechnicalAgent(),
            PersonalizedAdviceAgent(),
            RiskEvidenceReviewer(),
        ]
        for agent in agents:
            prompt = agent.soul()
            self.assertTrue(len(prompt) > 50, f"Prompt for {agent.name} must be loaded")
            self.assertIn("Soul:", prompt, f"SOUL.md must be loaded for {agent.name}")
            self.assertIn("Operational Protocols:", prompt, f"AGENTS.md must be loaded for {agent.name}")


if __name__ == '__main__':
    unittest.main()
