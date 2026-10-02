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

    def test_extended_indicators_long_series(self):
        # Accelerating uptrend so EMA12 pulls clearly above EMA26 (MACD > 0)
        prices = [100.0 * (1.004 ** i) + i * 0.02 for i in range(250)]
        volumes = [1_000_000 + i * 1000 for i in range(250)]
        indicators = calculate_indicators(prices, volumes)

        # Long-window indicators all computable with 250 bars
        for key in ('ema20', 'ema50', 'ema200', 'boll_lower', 'boll_upper',
                    'macd', 'macd_signal', 'macd_hist', 'avg5', 'momentum5',
                    'consolidation', 'obv_trend'):
            self.assertIn(key, indicators)
            self.assertNotEqual(indicators[key], 'N/A', f'{key} should compute on 250 bars')

        # Uptrend: EMA20 > EMA50, MACD histogram positive, OBV rising
        self.assertGreater(float(indicators['ema20']), float(indicators['ema50']))
        self.assertGreater(float(indicators['macd_hist']), 0.0)
        self.assertEqual(indicators['obv_trend'], 'rising')
        # Bollinger band is ordered
        self.assertLess(float(indicators['boll_lower']), float(indicators['boll_upper']))

    def test_extended_indicators_degrade_gracefully(self):
        # No volumes -> OBV unavailable, everything else fine
        indicators = calculate_indicators([100.0 + i for i in range(60)])
        self.assertEqual(indicators['obv_trend'], 'N/A')
        self.assertEqual(indicators['ema200'], 'N/A')  # needs 200 bars
        self.assertNotEqual(indicators['ema20'], 'N/A')

        # Short series -> new keys exist with neutral values
        short = calculate_indicators([50.0, 52.0, 51.0])
        for key in ('ema20', 'ema50', 'ema200', 'boll_lower', 'macd_hist',
                    'avg5', 'momentum5', 'consolidation', 'obv_trend'):
            self.assertIn(key, short)

        # Empty series -> full neutral key set
        empty = calculate_indicators([])
        for key in ('ema200', 'macd_hist', 'boll_upper', 'momentum5'):
            self.assertEqual(empty[key], 'N/A')

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
