import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from agents import FundamentalTechnicalAgent, NewsContextAgent, PersonalizedAdviceAgent, RiskEvidenceReviewer
from analysis.indicators import calculate_indicators
from models.analysis_models import MarketSnapshotData, SourceItem
from reporting.line_report_renderer import LineReportRenderer


class OfflineLLM:
    def generate_json(self, *_args, **_kwargs):
        return None


class ReportComponentTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = MarketSnapshotData(
            symbol='TEST', price=120, pe_ratio=12, div_yield=2.0,
            history=[100 + i for i in range(60)],
            technicals=calculate_indicators([100 + i for i in range(60)]),
            sources=[SourceItem(title='Company earnings improve', url='https://example.com')],
        )

    def test_indicator_calculation_is_deterministic(self):
        indicators = calculate_indicators([100 + i for i in range(60)])
        self.assertEqual(indicators['sma50'], '134.50')
        self.assertNotEqual(indicators['rsi'], 'N/A')

    def test_agents_produce_safe_offline_report(self):
        news = NewsContextAgent(OfflineLLM()).run(self.snapshot)
        analysis = FundamentalTechnicalAgent(OfflineLLM()).run(self.snapshot)
        advice = PersonalizedAdviceAgent(OfflineLLM()).run(self.snapshot, news, analysis, {'risk_appetite': 'Medium'})
        review = RiskEvidenceReviewer(OfflineLLM()).run(self.snapshot, advice)
        self.assertTrue(advice.summary)
        self.assertIn(analysis.outlook, ('Positive', 'Neutral', 'Cautious'))
        self.assertIn(review.status, ('approve', 'revise'))

    def test_renderer_is_not_mutated_between_reports(self):
        report = {
            'symbol': 'TEST', 'signal': 'Positive', 'reason': 'สรุป',
            'metrics': {'price': 120}, 'technicals': self.snapshot.technicals,
            'advice': {'reasons': ['a'], 'risks': ['b'], 'next_watch_items': ['c']},
            'updated_at': '2026-09-19 10:00',
        }
        first = LineReportRenderer.render_stock_card(report)
        second = LineReportRenderer.render_stock_card(report)
        self.assertEqual(first, second)

    def test_market_brief_card_renders_all_impacts(self):
        for impact in ('Positive', 'Mixed', 'Negative', 'garbage'):
            brief = {'summary': 'สรุป', 'news': ['ข่าว 1'], 'impact': impact,
                     'advice': ['คำแนะนำ'], 'disclaimer': 'd', 'provider': 'gemini'}
            bubble = LineReportRenderer.render_market_brief_card('PTT.BK', brief)
            self.assertEqual(bubble['type'], 'bubble')
            texts = str(bubble)
            self.assertIn('PTT.BK', texts)

    def test_market_brief_card_fallback_provider_label(self):
        brief = {'summary': 'สรุป', 'news': [], 'impact': 'Mixed',
                 'advice': [], 'disclaimer': 'd', 'provider': 'fallback'}
        bubble = LineReportRenderer.render_market_brief_card('TEST', brief)
        self.assertIn('โหมดสำรอง', str(bubble))


if __name__ == '__main__':
    unittest.main()
