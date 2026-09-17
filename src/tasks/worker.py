from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from linebot import LineBotApi
from linebot.models import FlexSendMessage

from config import Config
from database import ReportDelivery, SessionLocal
from services import process_stock_list


def process_report_job(payload):
    """RQ entry point. Safe to call from an RQ worker or local development queue."""
    user_id = payload['user_id']
    line_user_id = payload['line_user_id']
    request_id = payload['request_id']
    settings = payload.get('user_settings') or {}
    items = [SimpleNamespace(**item) for item in payload.get('items', [])]
    if not items:
        return

    bubbles = process_stock_list(items, user_id=user_id, user_settings=settings)
    if not bubbles:
        return

    db = SessionLocal()
    try:
        delivery = db.query(ReportDelivery).filter_by(idempotency_key=request_id).first()
        if delivery and delivery.status == 'sent':
            return
        if not delivery:
            delivery = ReportDelivery(user_id=user_id, idempotency_key=request_id, status='sending')
            db.add(delivery)
        else:
            delivery.status = 'sending'
        db.commit()

        contents = bubbles[0] if len(bubbles) == 1 else {'type': 'carousel', 'contents': bubbles[:10]}
        message = FlexSendMessage(alt_text='รายงานหุ้นของคุณ', contents=contents)
        api = LineBotApi(Config.LINE_CHANNEL_ACCESS_TOKEN)
        try:
            api.push_message(line_user_id, message, retry_key=request_id)
        except TypeError:
            # Older installed SDKs do not expose retry_key; the delivery row still
            # prevents this worker from intentionally sending the same job twice.
            api.push_message(line_user_id, message)
        delivery.status = 'sent'
        delivery.sent_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        if 'delivery' in locals():
            delivery.status = 'failed'
            delivery.error_message = str(exc)[:1000]
            db.commit()
        raise
    finally:
        db.close()
