from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

from linebot import LineBotApi
from linebot.models import FlexSendMessage, TextSendMessage

from config import Config
import store
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

    user_key = str(user_id)
    try:
        # Idempotency check: do not deliver duplicate reports
        delivery = store.get_delivery(request_id)
        if delivery and delivery.get('status') == 'sent':
            print(f"[Worker] Skipping already sent report job: {request_id}")
            return
        store.upsert_delivery(request_id, user_key, 'sending')

        # Collect results
        collected_reports = []

        def on_report(bubble, report):
            if report:
                collected_reports.append(report)

        bubbles = process_stock_list(items, callback_func=on_report, user_id=user_key, user_settings=settings)
        if not bubbles:
            store.upsert_delivery(request_id, user_key, 'failed', error_message='No bubbles generated')
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
                    # One-line evidence under each stock: prefer news reason,
                    # then financials, then stats — keeps the digest explainable.
                    'reason': (
                        ((r.get('reason_categories') or {}).get('news')
                         or (r.get('reason_categories') or {}).get('financials')
                         or (r.get('reason_categories') or {}).get('stats')
                         or [''])[0]
                    ),
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
        # X-Line-Retry-Key must be a canonical UUID string (with hyphens);
        # request_id may be a bare hex — convert or generate a stable one.
        try:
            retry_key = str(uuid.UUID(request_id))
        except (ValueError, AttributeError, TypeError):
            retry_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f'line-push:{request_id}'))
        try:
            api.push_message(line_user_id, message, retry_key=retry_key)
        except TypeError:
            # Older installed SDK fallback without retry_key kwarg
            api.push_message(line_user_id, message)
        except Exception as flex_exc:
            # Last-resort fallback: an invalid Flex payload must never leave
            # the user with silence — degrade to a plain-text summary.
            print(f"[Worker] Flex push failed ({flex_exc}); falling back to text")
            fallback = LineReportRenderer.render_daily_digest_text(summary_text, collected_reports)
            api.push_message(line_user_id, TextSendMessage(text=fallback[:4900]))

        store.upsert_delivery(request_id, user_key, 'sent')
        print(f"[Worker] Report successfully delivered to {line_user_id} (key: {request_id})")
    except Exception as exc:
        print(f"[Worker] Error in report job {request_id}: {exc}")
        store.upsert_delivery(request_id, user_key, 'failed', error_message=str(exc)[:1000])
        raise
