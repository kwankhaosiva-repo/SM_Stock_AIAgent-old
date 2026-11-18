import datetime
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import store
from tasks.dispatcher import check_jobs, process_schedule
from tasks.worker import process_report_job
from app import app


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        store.backend = store.MemoryBackend()

    def tearDown(self):
        store.backend = store.MemoryBackend()

    @patch('tasks.worker.LineBotApi')
    @patch('tasks.worker.process_stock_list')
    def test_check_jobs_executes_synchronously_and_pushes(self, mock_process_stocks, mock_line_api):
        """Verify check_jobs(sync=True) runs inline and calls push_message before returning."""
        mock_process_stocks.return_value = [
            {'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical', 'contents': []}}
        ]
        mock_api_instance = mock_line_api.return_value

        user_key = 'U_SCHED_USER_1'
        store.get_or_create_user(user_key)
        store.add_watch_item(user_key, 'AAPL')
        store.upsert_schedule(user_key, alert_time='09:00', is_active=True)

        processed = check_jobs(target_time='09:00', force=False, sync=True)

        self.assertEqual(processed, 1)
        self.assertEqual(mock_api_instance.push_message.call_count, 1)

        # Schedule last_run should be updated in UTC
        sched = store.get_schedule(user_key)
        self.assertIsNotNone(sched.get('last_run'))

    @patch('tasks.worker.LineBotApi')
    @patch('tasks.worker.process_stock_list')
    def test_timezone_last_run_prevents_duplicate_in_same_bangkok_hour(self, mock_process_stocks, mock_line_api):
        """Verify UTC last_run (02:00 UTC) correctly skips re-run at 09:00 Asia/Bangkok."""
        mock_process_stocks.return_value = [
            {'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical', 'contents': []}}
        ]
        mock_api_instance = mock_line_api.return_value

        tz = pytz.timezone('Asia/Bangkok')
        now_bkk = datetime.datetime.now(tz)
        current_hour_str = now_bkk.strftime('%H:00')

        # Record last_run as current UTC time (same Bangkok hour, different UTC hour by -7h)
        last_run_utc = now_bkk.astimezone(datetime.timezone.utc)

        user_key = 'U_TZ_USER'
        store.get_or_create_user(user_key)
        store.add_watch_item(user_key, 'GOOG')
        store.upsert_schedule(user_key, alert_time=current_hour_str, is_active=True, last_run=last_run_utc)

        # Should skip because it already ran in this Bangkok hour
        processed = check_jobs(target_time=current_hour_str, force=False, sync=True)
        self.assertEqual(processed, 0)
        self.assertEqual(mock_api_instance.push_message.call_count, 0)

        # With force=True, it must run even if last_run is in the same hour
        processed_force = check_jobs(target_time=current_hour_str, force=True, sync=True)
        self.assertEqual(processed_force, 1)
        self.assertEqual(mock_api_instance.push_message.call_count, 1)

    @patch('tasks.worker.LineBotApi')
    @patch('tasks.worker.process_stock_list')
    def test_single_bubble_flex_error_falls_back_to_text_without_unbound_local(
        self, mock_process_stocks, mock_line_api
    ):
        """Verify summary_text is defined when single-bubble Flex push fails and falls back to text."""
        def fake_process(items, callback_func=None, user_id=None, user_settings=None):
            bubble = {'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical', 'contents': []}}
            report = {'symbol': 'NVDA', 'signal': 'Positive', 'metrics': {'price': 120.0}, 'reason': 'Strong growth'}
            if callback_func:
                callback_func(bubble, report)
            return [bubble]

        mock_process_stocks.side_effect = fake_process
        mock_api_instance = mock_line_api.return_value
        # First call (Flex) fails, second call (TextSendMessage fallback) succeeds
        mock_api_instance.push_message.side_effect = [Exception('Invalid Flex payload'), None]

        payload = {
            'user_id': 'U_FALLBACK',
            'line_user_id': 'U_FALLBACK',
            'request_id': 'req-fallback-test-1',
            'items': [{'symbol': 'NVDA'}],
            'user_settings': {},
        }

        # Should NOT raise UnboundLocalError
        process_report_job(payload)

        self.assertEqual(mock_api_instance.push_message.call_count, 2)
        delivery = store.get_delivery('req-fallback-test-1')
        self.assertEqual(delivery['status'], 'sent')

    @patch('tasks.worker.LineBotApi')
    @patch('tasks.worker.process_stock_list')
    def test_cron_trigger_endpoint_runs_synchronously(self, mock_process_stocks, mock_line_api):
        """Verify /cron/trigger endpoint executes jobs synchronously and returns JSON status."""
        mock_process_stocks.return_value = [
            {'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical', 'contents': []}}
        ]
        mock_api_instance = mock_line_api.return_value

        user_key = 'U_CRON_HTTP'
        store.get_or_create_user(user_key)
        store.add_watch_item(user_key, 'MSFT')
        # Save as '9:00' without leading zero to also verify normalization
        store.upsert_schedule(user_key, alert_time='9:00', is_active=True)

        client = app.test_client()
        resp = client.get('/cron/trigger?time=09:00&force=true')

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['processed'], 1)
        self.assertEqual(mock_api_instance.push_message.call_count, 1)

    def test_firestore_list_watchlist_guarantees_symbol(self):
        """Verify FirestoreBackend.list_watchlist populates symbol from doc.id when missing."""
        mock_doc = MagicMock()
        mock_doc.id = 'TSLA'
        mock_doc.to_dict.return_value = {'strategy': 'AI-Auto'}  # missing 'symbol' field

        mock_client = MagicMock()
        mock_client.collection.return_value.document.return_value.collection.return_value.stream.return_value = [
            mock_doc
        ]

        backend = store.FirestoreBackend(mock_client)
        items = backend.list_watchlist('U_FS_USER')

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['symbol'], 'TSLA')
        self.assertEqual(items[0]['strategy'], 'AI-Auto')


if __name__ == '__main__':
    unittest.main()
