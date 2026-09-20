import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from chat_service import ChatRequest, dispatch, HELP_TEXT
from reporting.web_chat_renderer import render_brief_html, render_report_html


class OfflineOnlyTests(unittest.TestCase):
    """Tests that don't hit network (no yfinance resolution)."""

    def test_help_command(self):
        req = ChatRequest(channel='web', channel_user_id='u1', text='help')
        responses = dispatch(req)
        self.assertEqual(responses[0].kind, 'text')
        self.assertIn('add', responses[0].text)

    def test_unknown_command_returns_help(self):
        req = ChatRequest(channel='web', channel_user_id='u1', text='blah blah')
        responses = dispatch(req)
        self.assertEqual(responses[0].kind, 'text')
        self.assertIn('ไม่เข้าใจ', responses[0].text)

    def test_empty_message_returns_help(self):
        req = ChatRequest(channel='web', channel_user_id='u1', text='   ')
        responses = dispatch(req)
        self.assertEqual(responses[0].text, HELP_TEXT)

    def test_watchlist_empty_for_new_user(self):
        req = ChatRequest(channel='web', channel_user_id='wl-test-user', text='watchlist')
        responses = dispatch(req)
        self.assertEqual(responses[0].kind, 'text')
        self.assertIn('ว่างเปล่า', responses[0].text)

    def test_brief_html_contains_impact_badge(self):
        brief = {
            'summary': 'สรุปตลาด <script>alert(1)</script>',
            'news': ['ข่าว 1', 'ข่าว 2'],
            'impact': 'Negative',
            'advice': ['ระวังความเสี่ยง'],
            'disclaimer': 'ไม่ใช่คำแนะนำ',
            'provider': 'gemini',
        }
        out = render_brief_html('PTT.BK', brief)
        self.assertIn('badge Negative', out)
        self.assertIn('🔴', out)
        # XSS must be escaped
        self.assertNotIn('<script>', out)
        self.assertIn('&lt;script&gt;', out)

    def test_brief_html_fallback_label(self):
        brief = {'summary': 's', 'news': [], 'impact': 'Mixed', 'advice': [],
                 'disclaimer': 'd', 'provider': 'fallback'}
        out = render_brief_html('TEST', brief)
        self.assertIn('โหมดสำรอง', out)

    def test_report_html_renders_symbol_and_price(self):
        report = {
            'symbol': 'ptt.bk', 'signal': 'Positive', 'reason': 'สรุปเหตุผล',
            'metrics': {'price': 32.5, 'pe_ratio': 8.1, 'div_yield': 4.2},
            'technicals': {'rsi': '55.5'},
            'advice': {'reasons': ['a', 'b'], 'risks': ['r1'], 'next_watch_items': ['w']},
            'history': [30.0 + i * 0.1 for i in range(40)],
            'updated_at': '2026-09-19 10:00',
        }
        out = render_report_html(report)
        self.assertIn('PTT.BK', out)
        self.assertIn('฿ 32.50', out)
        self.assertIn('badge Positive', out)


if __name__ == '__main__':
    unittest.main()
