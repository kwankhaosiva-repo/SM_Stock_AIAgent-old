from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

from linebot import LineBotApi
from linebot.models import FlexSendMessage

from config import Config
from database import ReportDelivery, SessionLocal
from reporting.line_report_renderer import LineReportRenderer
from services import process_stock_list


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def process_report_job(payload: Dict[str, Any]):
    """RQ entry point. Safe to call from an RQ worker or local development queue."""
    user_id = payload['user_id']
    line_user_id = payload['line_user_id']
    request_id = payload['request_id']
    settings = payload.get('user_settings') or {}
    items = [SimpleNamespace(**item) for item in payload.get('items', [])]
    if not items:
        return

    db = SessionLocal()
    try:
        # Idempotency check: do not deliver duplicate reports
        delivery = db.query(ReportDelivery).filter_by(idempotency_key=request_id).first()
        if delivery and delivery.status == 'sent':
            print(f"[Worker] Skipping already sent report job: {request_id}")
            return
        if not delivery:
            delivery = ReportDelivery(user_id=user_id, idempotency_key=request_id, status='sending')
            db.add(delivery)
        else:
            delivery.status = 'sending'
        db.commit()

        # Collect results
        collected_reports = []

        def on_report(bubble, report):
            if report:
                collected_reports.append(report)

        bubbles = process_stock_list(items, callback_func=on_report, user_id=user_id, user_settings=settings)
        if not bubbles:
            delivery.status = 'failed'
            delivery.error_message = 'No bubbles generated'
            db.commit()
            return

        # Rule 8: Create a daily digest card first if multiple stocks
        if len(bubbles) > 1:
            attention_count = sum(
                1 for r in collected_reports if (r.get('signal') == 'Cautious' or r.get('advice', {}).get('outlook') == 'Cautious')
            )
            top_stocks = [
                {
                    'symbol': r.get('symbol'),
                    'price': f"{r.get('metrics', {}).get('price', 0):,.2f}",
                    'outlook': r.get('signal') or r.get('advice', {}).get('outlook') or 'Neutral',
                }
                for r in collected_reports[:3]
            ]
            digest_bubble = LineReportRenderer.render_daily_digest_card(
                summary_text=f"สรุปการวิเคราะห์หุ้น {len(collected_reports)} ตัวใน Watchlist ของคุณ",
                attention_count=attention_count,
                top_stocks=top_stocks,
            )
            bubbles.insert(0, digest_bubble)

        # Build Flex message (max 10 bubbles in carousel for LINE API limits)
        contents = bubbles[0] if len(bubbles) == 1 else {'type': 'carousel', 'contents': bubbles[:10]}
        message = FlexSendMessage(alt_text='รายงานวิเคราะห์หุ้นของคุณ', contents=contents)

        api = LineBotApi(Config.LINE_CHANNEL_ACCESS_TOKEN)
        try:
            api.push_message(line_user_id, message, retry_key=request_id)
        except TypeError:
            # Older installed SDK fallback without retry_key kwarg
            api.push_message(line_user_id, message)

        delivery.status = 'sent'
        delivery.sent_at = _utcnow_naive()
        db.commit()
        print(f"[Worker] Report successfully delivered to {line_user_id} (key: {request_id})")
    except Exception as exc:
        print(f"[Worker] Error in report job {request_id}: {exc}")
        if 'delivery' in locals() and delivery:
            delivery.status = 'failed'
            delivery.error_message = str(exc)[:1000]
            db.commit()
        raise
    finally:
        db.close()
