import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from reporting.line_report_renderer import LineReportRenderer
from reporting.indicator_view import GLOSSARY, build_indicator_sections


class LineReportingTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            'symbol': 'PTT.BK',
            'signal': 'Positive',
            'reason': 'แนวโน้มเชิงบวกจากผลการดำเนินงานและราคายืนเหนือ SMA50',
            'updated_at': '2026-09-18 06:45',
            'metrics': {
                'price': 34.50,
                'pe_ratio': 9.2,
                'div_yield': 5.8,
            },
            'technicals': {
                'rsi': '58.20',
                'sma50': '32.10',
                'volatility': '18.2%',
                'ema20': '33.90',
                'ema50': '33.10',
                'ema200': '31.50',
                'boll_lower': '32.80',
                'boll_upper': '35.40',
                'macd_hist': '0.120',
                'avg5': '34.20',
                'momentum5': '+2.1%',
                'consolidation': '5.2%',
                'obv_trend': 'rising',
                'support': '31.00',
                'resistance': '35.00',
                'year_high': '36.00',
                'year_low': '28.00',
            },
            'advice': {
                'outlook': 'Positive',
                'summary': 'ภาพรวมเชิงบวก',
                'reasons': [
                    'ราคาหุ้นยืนเหนือเส้นค่าเฉลี่ย 50 วัน',
                    'อัตราเงินปันผลสูงกว่า 5% ต่อปี',
                    'RSI อยู่ในโซนสมดุลที่ 58.20',
                ],
                'risks': ['ความผันผวนของราคาน้ำมันดิบในตลาดโลก'],
                'next_watch_items': ['ติดตามผลการประชุม OPEC+'],
                'confidence': 'Medium',
            },
            'history': [30.0 + i * 0.15 for i in range(30)],
        }

    def test_stock_card_has_required_elements_and_buttons(self):
        card = LineReportRenderer.render_stock_card(self.report)

        self.assertEqual(card.get('type'), 'bubble')
        body = card.get('body', {})
        self.assertIn('contents', body)

        # Serialize to text to check elements easily
        raw_json = json.dumps(card, ensure_ascii=False)

        # Price and Symbol
        self.assertIn('PTT.BK', raw_json)
        self.assertIn('34.50', raw_json)

        # Outlook badge
        self.assertIn('Positive', raw_json)

        # 3 Reasons
        self.assertIn('ราคาหุ้นยืนเหนือเส้นค่าเฉลี่ย 50 วัน', raw_json)
        self.assertIn('อัตราเงินปันผลสูงกว่า 5% ต่อปี', raw_json)
        self.assertIn('RSI อยู่ในโซนสมดุลที่ 58.20', raw_json)

        # Risk and watch items
        self.assertIn('ความเสี่ยงสำคัญ', raw_json)
        self.assertIn('สิ่งที่ควรติดตาม', raw_json)

        # Postback buttons in footer
        footer = card.get('footer', {})
        footer_json = json.dumps(footer)
        self.assertIn('action=why&symbol=PTT.BK', footer_json)
        self.assertIn('action=news&symbol=PTT.BK', footer_json)
        self.assertIn('action=financials&symbol=PTT.BK', footer_json)
        self.assertIn('action=refresh&symbol=PTT.BK', footer_json)
        self.assertIn('action=set_time', footer_json)

        # Disclaimer
        self.assertIn('ไม่ใช่คำแนะนำการลงทุนเฉพาะบุคคล', raw_json)

        # Technical indicator sections: short / mid / long with explanations
        self.assertIn('บทวิเคราะห์เชิงเทคนิค', raw_json)
        self.assertIn('ระยะสั้น', raw_json)
        self.assertIn('ระยะกลาง', raw_json)
        self.assertIn('ระยะยาว', raw_json)
        self.assertIn('Golden Cross', json.dumps(GLOSSARY, ensure_ascii=False))
        self.assertIn('action=glossary', footer_json)

        # Every indicator line must carry a beginner explanation
        sections = build_indicator_sections(self.report['technicals'], 34.50)
        self.assertGreaterEqual(len(sections), 3)
        for sec in sections:
            for line in sec['lines']:
                self.assertTrue(line['explain'])
                self.assertIn(line['tone_label'], ('Positive', 'Negative', 'Watch'))

    def test_glossary_card_and_text(self):
        card = LineReportRenderer.render_glossary_card()
        self.assertEqual(card.get('type'), 'bubble')
        raw = json.dumps(card, ensure_ascii=False)
        for term in ('RSI', 'MACD', 'EMA', 'OBV', 'Bollinger'):
            self.assertIn(term, raw)

        text = LineReportRenderer.render_glossary_text()
        self.assertIn('คำศัพท์', text)
        self.assertIn('มือใหม่', text)
        self.assertGreater(len(GLOSSARY), 8)

    def test_daily_digest_card(self):
        digest = LineReportRenderer.render_daily_digest_card(
            summary_text="ตลาดหุ้นเคลื่อนไหวในแดนบวก",
            attention_count=2,
            top_stocks=[
                {'symbol': 'PTT.BK', 'price': '34.50', 'outlook': 'Positive'},
                {'symbol': 'CPALL.BK', 'price': '62.00', 'outlook': 'Neutral'},
                {'symbol': 'DELTA.BK', 'price': '80.00', 'outlook': 'Cautious'},
            ],
        )

        self.assertEqual(digest.get('type'), 'bubble')
        raw_json = json.dumps(digest, ensure_ascii=False)
        self.assertIn('Daily Digest', raw_json)
        self.assertIn('หุ้นที่ต้องจับตาเป็นพิเศษ: 2 ตัว', raw_json)
        self.assertIn('DELTA.BK', raw_json)
        self.assertIn('CPALL.BK', raw_json)


if __name__ == '__main__':
    unittest.main()
