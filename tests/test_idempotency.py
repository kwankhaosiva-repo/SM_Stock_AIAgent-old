import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from database import Base, ReportDelivery, SessionLocal, User, engine
from tasks.worker import process_report_job


class IdempotencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        # Create test user if not exists
        user = self.db.query(User).filter_by(line_user_id='U_TEST_USER').first()
        if not user:
            user = User(line_user_id='U_TEST_USER')
            self.db.add(user)
            self.db.commit()
        self.user_id = user.id

    def tearDown(self):
        self.db.close()

    @patch('tasks.worker.LineBotApi')
    @patch('tasks.worker.process_stock_list')
    def test_idempotent_report_delivery(self, mock_process_stocks, mock_line_api):
        mock_process_stocks.return_value = [{'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical', 'contents': []}}]
        mock_api_instance = mock_line_api.return_value

        request_id = 'test_request_key_123'

        # Ensure no prior delivery
        self.db.query(ReportDelivery).filter_by(idempotency_key=request_id).delete()
        self.db.commit()

        payload = {
            'user_id': self.user_id,
            'line_user_id': 'U_TEST_USER',
            'request_id': request_id,
            'items': [{'symbol': 'PTT.BK'}],
            'user_settings': {},
        }

        # First run: should process and push message
        process_report_job(payload)
        self.assertEqual(mock_api_instance.push_message.call_count, 1)

        delivery = self.db.query(ReportDelivery).filter_by(idempotency_key=request_id).first()
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.status, 'sent')

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
