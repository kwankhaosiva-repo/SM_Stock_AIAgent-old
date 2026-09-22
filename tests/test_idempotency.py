import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import store
from tasks.worker import process_report_job


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        # Fresh in-memory backend per test
        store.backend = store.MemoryBackend()

    def tearDown(self):
        store.backend = store.MemoryBackend()

    @patch('tasks.worker.LineBotApi')
    @patch('tasks.worker.process_stock_list')
    def test_idempotent_report_delivery(self, mock_process_stocks, mock_line_api):
        mock_process_stocks.return_value = [{'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical', 'contents': []}}]
        mock_api_instance = mock_line_api.return_value

        request_id = 'test_request_key_123'
        user_key = 'U_TEST_USER'

        payload = {
            'user_id': user_key,
            'line_user_id': 'U_TEST_USER',
            'request_id': request_id,
            'items': [{'symbol': 'PTT.BK'}],
            'user_settings': {},
        }

        # First run: should process and push message
        process_report_job(payload)
        self.assertEqual(mock_api_instance.push_message.call_count, 1)

        delivery = store.get_delivery(request_id)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery['status'], 'sent')

        # Second run with identical idempotency_key (retry or duplicate webhook):
        # Must be skipped and NOT call push_message again!
        process_report_job(payload)
        self.assertEqual(
            mock_api_instance.push_message.call_count,
            1,
            "Duplicate job execution must be idempotent and not resend message",
        )


if __name__ == '__main__':
    unittest.main()
