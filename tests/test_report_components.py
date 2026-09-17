import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from agents import FundamentalTechnicalAgent, NewsContextAgent, PersonalizedAdviceAgent, RiskEvidenceReviewer
from analysis.indicators import calculate_indicators
from line_templates import get_analysis_flex
from models.analysis_models import MarketSnapshotData, SourceItem


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

    def test_flex_template_is_not_mutated_between_reports(self):
        details = {'price': 120, 'history': [100 + i for i in range(30)], 'technicals': self.snapshot.technicals}
        first = get_analysis_flex('TEST', 'Positive', 'Summary', details)
        second = get_analysis_flex('TEST', 'Positive', 'Summary', details)
        self.assertEqual(first['contents'], second['contents'])


if __name__ == '__main__':
    unittest.main()
