import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import Config
from data.providers import (
    ProviderSkip,
    RelayMarketDataProvider,
    SettradeOpenDataProvider,
)


class SettradeProviderTests(unittest.TestCase):
    def test_skips_non_thai_symbol(self):
        provider = SettradeOpenDataProvider()
        with self.assertRaises(ProviderSkip):
            provider.fetch('AAPL')

    def test_skips_without_keys(self):
        provider = SettradeOpenDataProvider()
        with patch.object(Config, 'SETTRADE_APP_ID', ''), \
             patch.object(Config, 'SETTRADE_APP_SECRET', ''):
            with self.assertRaises(ProviderSkip):
                provider.fetch('PTT.BK')

    def test_fetch_returns_data_when_keys_present(self):
        provider = SettradeOpenDataProvider()
        fake_ctx = MagicMock()
        fake_ctx.market_report.get_sec_info.return_value = MagicMock(
            data=[{'last_price': 32.0, 'p_e': 8.5, 'yield': 3.1}]
        )
        fake_ctx.market_report.get_candlestick.return_value = MagicMock(
            data=[{'c': 30.0 + i} for i in range(10)]
        )
        with patch.object(Config, 'SETTRADE_APP_ID', 'x'), \
             patch.object(Config, 'SETTRADE_APP_SECRET', 'y'), \
             patch.object(provider, '_context', return_value=fake_ctx):
            result = provider.fetch('PTT.BK')
        self.assertEqual(result['price'], 32.0)
        self.assertEqual(result['pe_ratio'], 8.5)
        self.assertEqual(len(result['history']), 10)


class RelayProviderTests(unittest.TestCase):
    def test_skips_without_url(self):
        provider = RelayMarketDataProvider()
        with patch.object(Config, 'DATA_RELAY_URL', ''):
            with self.assertRaises(ProviderSkip):
                provider.fetch('PTT')

    def test_fetch_parses_relay_payload(self):
        provider = RelayMarketDataProvider()
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {
            'price': 45.5, 'pe_ratio': 12.0, 'div_yield': 2.5,
            'history': [40.0, 41.0, 45.5], 'technicals': {'rsi': '55'},
        }
        with patch.object(Config, 'DATA_RELAY_URL', 'https://relay.example.com'), \
             patch('data.providers.relay_provider.requests.get', return_value=fake_resp):
            result = provider.fetch('KTB.BK')
        self.assertEqual(result['price'], 45.5)
        self.assertEqual(result['technicals']['rsi'], '55')


class SnapshotChainTests(unittest.TestCase):
    def test_thai_chain_order(self):
        from data.market_snapshot_service import MarketSnapshotService
        service = MarketSnapshotService()
        chain = service._provider_chain('PTT.BK')
        names = [p.name for p in chain]
        self.assertEqual(names[0], 'settrade_open')
        self.assertIn('yahoo_finance', names)

    def test_global_chain_order(self):
        from data.market_snapshot_service import MarketSnapshotService
        service = MarketSnapshotService()
        chain = service._provider_chain('AAPL')
        names = [p.name for p in chain]
        self.assertEqual(names, ['local_relay', 'yahoo_finance'])

    def test_fallback_skips_broken_provider(self):
        from data.market_snapshot_service import MarketSnapshotService
        service = MarketSnapshotService()

        bad = MagicMock()
        bad.name = 'broken'
        bad.fetch.side_effect = ProviderSkip('no key')
        good = MagicMock()
        good.name = 'good'
        good.fetch.return_value = {'price': 10.0}
        service._market_provider = None
        with patch.object(service, '_provider_chain', return_value=[bad, good]):
            raw, name = service._fetch_with_fallback('TEST')
        self.assertEqual(name, 'good')
        self.assertEqual(raw['price'], 10.0)


class FinancialsFallbackTests(unittest.TestCase):
    def test_fmp_skips_without_key(self):
        from data.financials_service import FinancialsService
        service = FinancialsService()
        data, source = service._fetch_fmp('PTT.BK')
        self.assertIsNone(data)

    def test_cache_roundtrip(self):
        from data.financials_service import FinancialsService
        from database import Base, SessionLocal, engine
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            db.query(FinancialsServiceCacheStub).delete()
        except Exception:
            pass
        finally:
            db.close()

        service = FinancialsService()
        payload = {'balance_sheet': [('สินทรัพย์รวม', '1.00 พันล้าน')], 'income': [], 'period': '2025'}
        with patch.object(service, '_write_cache'), \
             patch.object(service, '_read_cache', return_value={**payload, 'cached': True}):
            result = service.get_financials('TEST_SYM', db=db)
        self.assertTrue(result['cached'])
        self.assertEqual(result['balance_sheet'][0][0], 'สินทรัพย์รวม')


from database import FinancialStatementCache as FinancialsServiceCacheStub  # noqa: E402


if __name__ == '__main__':
    unittest.main()
