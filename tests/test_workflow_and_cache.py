import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from data.market_snapshot_service import MarketSnapshotService
from data.providers.base import MarketDataProvider, NewsDataProvider
from database import AnalysisRun, Base, MarketSnapshot, SessionLocal, engine
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
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        # Clean test snapshots
        self.db.query(MarketSnapshot).filter(MarketSnapshot.symbol == 'MOCK_SYM').delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_snapshot_cache_reuse_across_users(self):
        mock_provider = MockDataProvider()
        service = MarketSnapshotService(
            market_provider=mock_provider,
            news_provider=MockNewsProvider(),
            db_session=self.db,
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
            db_session=self.db,
        )
        workflow = ReportWorkflow(snapshot_service=service, db_session=self.db)

        profile = {'core_strategy': 'Growth', 'investment_goal': 'Long'}
        result = workflow.run('MOCK_SYM', profile, user_id=1)

        self.assertEqual(result['symbol'], 'MOCK_SYM')
        self.assertIn(result['signal'], ('Positive', 'Neutral', 'Cautious'))
        self.assertIn('advice', result)
        self.assertIn('review_status', result)

        # Verify AnalysisRun recorded in database
        run_record = self.db.query(AnalysisRun).filter_by(symbol='MOCK_SYM').order_by(AnalysisRun.id.desc()).first()
        self.assertIsNotNone(run_record)
        self.assertEqual(run_record.status, 'completed')


if __name__ == '__main__':
    unittest.main()
