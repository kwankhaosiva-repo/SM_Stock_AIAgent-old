import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from analysis.indicators import calculate_indicators, infer_trend


class IndicatorTests(unittest.TestCase):
    def test_indicators_basic_series(self):
        prices = [100.0 + i for i in range(60)]
        indicators = calculate_indicators(prices)

        self.assertIn('rsi', indicators)
        self.assertIn('sma20', indicators)
        self.assertIn('sma50', indicators)
        self.assertIn('volatility', indicators)
        self.assertIn('support', indicators)
        self.assertIn('resistance', indicators)

        # SMA50 for 100..159 is average of 110..159 = 134.50
        self.assertEqual(indicators['sma50'], '134.50')
        # In an upward series, RSI is near 100
        self.assertNotEqual(indicators['rsi'], 'N/A')
        self.assertGreaterEqual(float(indicators['rsi']), 50.0)

    def test_indicators_empty_or_small_series(self):
        empty = calculate_indicators([])
        self.assertEqual(empty['rsi'], 'N/A')
        self.assertEqual(empty['sma50'], 'N/A')

        short = calculate_indicators([50.0, 52.0])
        self.assertEqual(short['sma50'], 'N/A')
        self.assertEqual(short['rsi'], 'N/A')

    def test_infer_trend_rules(self):
        technicals = {'sma50': '100.00'}

        # Above SMA50 by > 1%
        self.assertEqual(infer_trend(105.0, technicals), 'Positive')

        # Below SMA50 by > 1%
        self.assertEqual(infer_trend(95.0, technicals), 'Cautious')

        # Near SMA50
        self.assertEqual(infer_trend(100.2, technicals), 'Neutral')

        # Missing technicals
        self.assertEqual(infer_trend(100.0, {}), 'Neutral')


if __name__ == '__main__':
    unittest.main()
