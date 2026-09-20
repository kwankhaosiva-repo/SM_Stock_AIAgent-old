"""HTML renderers mirroring the LINE design system for the web chat UI."""
from __future__ import annotations

import html
from typing import Any, Dict

_IMPACT = {
    'Positive': {'emoji': '🟢', 'label': 'Positive'},
    'Mixed': {'emoji': '🟡', 'label': 'Mixed'},
    'Negative': {'emoji': '🔴', 'label': 'Negative'},
}
_OUTLOOK = {
    'Positive': ('🟢 Positive', 'Positive'),
    'Neutral': ('🟡 Neutral', 'Mixed'),
    'Cautious': ('🔴 Cautious', 'Negative'),
}


def _esc(value: Any) -> str:
    return html.escape(str(value))


def render_brief_html(symbol: str, brief: Dict[str, Any]) -> str:
    impact = str(brief.get('impact', 'Mixed'))
    if impact not in _IMPACT:
        impact = 'Mixed'
    cfg = _IMPACT[impact]
    provider = str(brief.get('provider') or 'ai')
    provider_label = 'โหมดสำรอง (ตัวเลขล้วน)' if provider == 'fallback' else f'AI: {provider}'

    news_items = ''.join(f'<li>{_esc(n)}</li>' for n in (brief.get('news') or [])[:5])
    advice_items = ''.join(f'<li>{_esc(a)}</li>' for a in (brief.get('advice') or [])[:4])

    return (
        f'<h3>📰 Market Brief — {_esc(symbol)} '
        f'<span class="badge {impact}">{cfg["emoji"]} {cfg["label"]}</span></h3>'
        f'<div class="body">'
        f'<p>{_esc(brief.get("summary") or "")}</p>'
        f'<b>🗞 ข่าวย้ายตลาด</b><ul>{news_items or "<li>ไม่มีข่าว</li>"}</ul>'
        f'<b>💡 คำแนะนำ</b><ul>{advice_items or "<li>ติดตามข่าวก่อนตัดสินใจ</li>"}</ul>'
        f'</div>'
        f'<div class="disclaimer">{_esc(brief.get("disclaimer") or "")} ({_esc(provider_label)})</div>'
    )


def render_report_html(report: Dict[str, Any]) -> str:
    from analysis.chart_service import ChartService

    symbol = str(report.get('symbol', '')).upper()
    outlook = report.get('signal') or 'Neutral'
    if outlook not in _OUTLOOK:
        outlook = 'Neutral'
    label, badge_cls = _OUTLOOK[outlook]

    metrics = report.get('metrics') or {}
    technicals = report.get('technicals') or {}
    advice = report.get('advice') or {}
    price = metrics.get('price') or 0.0
    currency = '฿' if symbol.endswith('.BK') else '$'
    price_str = f'{currency} {float(price):,.2f}' if price else '-'

    chart_url = ''
    history = report.get('history') or []
    if len(history) >= 2:
        chart_url = ChartService.generate_sparkline_url(history, trend=outlook)

    reasons = ''.join(f'<li>{_esc(r)}</li>' for r in (advice.get('reasons') or [])[:3])
    risks = advice.get('risks') or []
    risk_text = _esc(risks[0]) if risks else 'ติดตามความผันผวนของตลาด'

    pe = metrics.get('pe_ratio')
    div_yield = metrics.get('div_yield')
    rsi = technicals.get('rsi')

    chart_html = f'<img class="chart" src="{_esc(chart_url)}" alt="chart">' if chart_url else ''

    return (
        f'<h3>{_esc(symbol)} <span class="badge {badge_cls}">{label}</span></h3>'
        f'<div class="body">'
        f'<div style="font-size:22px;font-weight:700">{_esc(price_str)}</div>'
        f'{chart_html}'
        f'<p>📊 P/E: {_esc(pe if pe not in (None, "N/A") else "-")} · '
        f'Dividend: {_esc(div_yield if div_yield not in (None, "N/A") else "-")}% · '
        f'RSI(14): {_esc(rsi or "-")}</p>'
        f'<b>📌 เหตุผลเชิงประจักษ์</b><ul>{reasons or "<li>-</li>"}</ul>'
        f'<b>⚠️ ความเสี่ยง:</b> {_esc(risk_text)}'
        f'</div>'
        f'<div class="disclaimer">ข้อมูลนี้เป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุนเฉพาะบุคคล</div>'
    )
