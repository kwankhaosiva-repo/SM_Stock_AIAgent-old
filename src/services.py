"""Compatibility facade used by LINE handlers and scheduled jobs."""

import time

from line_templates import get_analysis_flex
from reporting.line_report_renderer import LineReportRenderer
from workflows import ReportWorkflow


def process_stock_list(stocks, callback_func=None, user_id=None, user_settings=None):
    """Generate reports through the auditable workflow while retaining old callers."""
    bubbles = []
    workflow = ReportWorkflow()
    settings = user_settings or {}

    for index, item in enumerate(stocks):
        symbol = item.symbol if hasattr(item, 'symbol') else str(item)
        profile = {
            'core_strategy': getattr(item, 'strategy', None) or settings.get('core_strategy', 'AI-Auto'),
            'investment_goal': getattr(item, 'goal', None) or settings.get('investment_goal', 'Medium'),
            'risk_appetite': getattr(item, 'risk', None) or settings.get('risk_appetite', 'Medium'),
            'report_format': getattr(item, 'report_format', None) or settings.get('report_format', 'Short'),
        }
        try:
            report = workflow.run(symbol, profile, user_id=user_id)
            # Render using the rich LineReportRenderer
            bubble = LineReportRenderer.render_stock_card(report)
            bubbles.append(bubble)
            if callback_func:
                callback_func(bubble, report)
        except Exception as exc:
            print(f'[SERVICE] Failed to process {symbol}: {exc}')
            flex = get_analysis_flex(symbol, 'CAUTIOUS', 'ไม่สามารถสร้างรายงานได้ในขณะนี้', {})
            if flex and 'contents' in flex:
                bubble = flex['contents']
                bubbles.append(bubble)
                if callback_func:
                    callback_func(bubble, None)
        if index < len(stocks) - 1:
            time.sleep(1)
    return bubbles
