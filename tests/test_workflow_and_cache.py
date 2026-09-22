import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import store
from data.market_snapshot_service import MarketSnapshotService
from data.providers.base import MarketDataProvider, NewsDataProvider
from models.analysis_models import SourceItem
from workflows.report_workflow import ReportWorkflow


class MockDataProvider(MarketDataProvider):
    name = 'mock_provider'

    def __init__(self):
        self.call_count = 0

    def fetch(self, symbol: str):
        self.call_count += 1
        return {
            'price': 125.0,
            'pe_ratio': 15.0,
            'div_yield': 3.5,
            'history': [100.0 + i for i in range(40)],
            'technicals': {'sma50': '115.00'},
        }


class MockNewsProvider(NewsDataProvider):
    name = 'mock_news'

    def fetch_news(self, symbol: str):
        return [
            SourceItem(title=f"Breaking news for {symbol}", url="https://example.com/test", relevance="high")
        ]


class WorkflowAndCacheTests(unittest.TestCase):
    def setUp(self):
        # Fresh in-memory backend per test — no external services needed
        store.backend = store.MemoryBackend()

    def tearDown(self):
        store.backend = store.MemoryBackend()

    def test_snapshot_cache_reuse_across_users(self):
        mock_provider = MockDataProvider()
        service = MarketSnapshotService(
            market_provider=mock_provider,
            news_provider=MockNewsProvider(),
        )

        # 1st User request: should call provider
        snapshot_1, snap_id_1 = service.get_or_collect('MOCK_SYM')
        self.assertEqual(mock_provider.call_count, 1)
        self.assertIsNotNone(snap_id_1)
        self.assertEqual(snapshot_1.price, 125.0)

        # 2nd User request for identical stock: should reuse cached snapshot without refetching
        snapshot_2, snap_id_2 = service.get_or_collect('MOCK_SYM')
        self.assertEqual(mock_provider.call_count, 1, "Cached snapshot must be reused across users")
        self.assertEqual(snap_id_1, snap_id_2)
        self.assertEqual(snapshot_2.symbol, 'MOCK_SYM')

    def test_workflow_runs_and_persists_audit_records(self):
        mock_provider = MockDataProvider()
        service = MarketSnapshotService(
            market_provider=mock_provider,
            news_provider=MockNewsProvider(),
        )
        workflow = ReportWorkflow(snapshot_service=service)

        profile = {'core_strategy': 'Growth', 'investment_goal': 'Long'}
        result = workflow.run('MOCK_SYM', profile, user_key='test-user')

        self.assertEqual(result['symbol'], 'MOCK_SYM')
        self.assertIn(result['signal'], ('Positive', 'Neutral', 'Cautious'))
        self.assertIn('advice', result)
        self.assertIn('review_status', result)

        # Verify agent outputs were persisted as audit records
        self.assertGreater(len(store.backend.agent_outputs), 0)
        run_records = list(store.backend.analysis_runs.values())
        self.assertTrue(any(r['status'] == 'completed' and r['symbol'] == 'MOCK_SYM' for r in run_records))


if __name__ == '__main__':
    unittest.main()
