from __future__ import annotations

from typing import Any, Dict, List, Optional
from analysis.chart_service import ChartService


class LineReportRenderer:
    """Renders evidence-based LINE Flex message components conforming to architectural guidelines."""

    OUTLOOK_CONFIG = {
        'Positive': {'color': '#16803C', 'bg': '#E8F5E9', 'text': 'Positive (เชิงบวก)'},
        'Neutral': {'color': '#8A6100', 'bg': '#FFF8E1', 'text': 'Neutral (เป็นกลาง)'},
        'Cautious': {'color': '#B42318', 'bg': '#FFEBEE', 'text': 'Cautious (ระมัดระวัง)'},
    }

    @classmethod
    def render_stock_card(cls, report: Dict[str, Any], chart_url: Optional[str] = None) -> Dict[str, Any]:
        """Create a stock report card with 30-day chart, 3 reasons, risks, watch items, and postback buttons."""
        symbol = str(report.get('symbol', 'UNKNOWN')).upper()
        outlook = report.get('signal') or report.get('advice', {}).get('outlook') or 'Neutral'
        if outlook not in cls.OUTLOOK_CONFIG:
            outlook = 'Neutral'

        cfg = cls.OUTLOOK_CONFIG[outlook]
        metrics = report.get('metrics', {})
        technicals = report.get('technicals', {})
        advice = report.get('advice', {})

        price = metrics.get('price') or report.get('price') or 0.0
        currency = "฿" if symbol.endswith('.BK') else "$"
        price_str = f"{currency} {float(price):,.2f}" if price else "-"

        updated_at = report.get('updated_at') or "ล่าสุด"

        # Chart URL
        if not chart_url:
            history = report.get('history') or []
            if len(history) >= 2:
                chart_url = ChartService.generate_sparkline_url(history, trend=outlook)

        # 3 Evidence-based reasons
        reasons = advice.get('reasons') or [report.get('reason') or "ไม่มีข้อมูลเชิงลึก"]
        reason_boxes = []
        for idx, r in enumerate(reasons[:3], 1):
            reason_boxes.append({
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": f"{idx}.", "size": "xs", "color": "#16803C", "flex": 0, "weight": "bold"},
                    {"type": "text", "text": str(r), "size": "xs", "color": "#333333", "wrap": True, "flex": 1},
                ],
            })

        # Key risk
        risks = advice.get('risks') or ["ควรติดตามข่าวสารและข้อมูลพื้นฐานประกอบการลงทุน"]
        risk_text = str(risks[0]) if risks else "ติดตามความผันผวนของตลาด"

        # Next watch items
        watch_items = advice.get('next_watch_items') or ["ติดตามผลประกอบการไตรมาสถัดไป"]
        watch_text = str(watch_items[0]) if watch_items else "ระดับราคาสำคัญ"

        # Key metrics row
        pe = metrics.get('pe_ratio')
        pe_str = f"{float(pe):.1f}x" if pe not in (None, 'N/A', '-', 0) else "-"
        div_yield = metrics.get('div_yield')
        yield_str = f"{float(div_yield):.1f}%" if div_yield not in (None, 'N/A', '-', 0) else "-"
        rsi_str = str(technicals.get('rsi') or "-")
        vol_str = str(technicals.get('volatility') or "-")

        # Construct Flex bubble
        body_contents = [
            # Header block: Symbol & Outlook badge
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": symbol, "weight": "bold", "size": "xl", "color": "#111827"},
                            {"type": "text", "text": f"อัปเดต: {updated_at}", "size": "xxs", "color": "#6B7280"},
                        ],
                        "flex": 1,
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "text",
                                "text": cfg['text'],
                                "size": "xxs",
                                "weight": "bold",
                                "color": cfg['color'],
                                "align": "center",
                            }
                        ],
                        "backgroundColor": cfg['bg'],
                        "cornerRadius": "md",
                        "paddingAll": "6px",
                        "flex": 0,
                    },
                ],
            },
            # Price block
            {
                "type": "box",
                "layout": "horizontal",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": price_str, "size": "xxl", "weight": "bold", "color": "#111827"},
                ],
            },
            {"type": "separator", "margin": "md"},
        ]

        # Add chart if available
        if chart_url:
            body_contents.extend([
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "sm",
                    "contents": [
                        {"type": "text", "text": "📈 กราฟแนวโน้มราคา 30 วัน", "size": "xxs", "color": "#6B7280", "align": "center"},
                        {
                            "type": "image",
                            "url": chart_url,
                            "size": "full",
                            "aspectRatio": "2:1",
                            "aspectMode": "fit",
                            "margin": "xs",
                        },
                    ],
                },
                {"type": "separator", "margin": "sm"},
            ])

        # Add metrics grid
        body_contents.append({
            "type": "box",
            "layout": "horizontal",
            "margin": "md",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "P/E", "size": "xxs", "color": "#9CA3AF"},
                        {"type": "text", "text": pe_str, "size": "xs", "weight": "bold", "color": "#1F2937"},
                    ],
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "Dividend", "size": "xxs", "color": "#9CA3AF"},
                        {"type": "text", "text": yield_str, "size": "xs", "weight": "bold", "color": "#1F2937"},
                    ],
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "RSI(14)", "size": "xxs", "color": "#9CA3AF"},
                        {"type": "text", "text": rsi_str, "size": "xs", "weight": "bold", "color": "#1F2937"},
                    ],
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "Volatility", "size": "xxs", "color": "#9CA3AF"},
                        {"type": "text", "text": vol_str, "size": "xs", "weight": "bold", "color": "#1F2937"},
                    ],
                },
            ],
        })

        # Reasons section
        body_contents.extend([
            {"type": "separator", "margin": "md"},
            {"type": "text", "text": "📌 เหตุผลเชิงประจักษ์ 3 ข้อ:", "size": "xs", "weight": "bold", "color": "#374151", "margin": "md"},
            {
                "type": "box",
                "layout": "vertical",
                "margin": "sm",
                "spacing": "xs",
                "contents": reason_boxes,
            },
            # Key Risk section
            {"type": "separator", "margin": "md"},
            {
                "type": "box",
                "layout": "vertical",
                "margin": "sm",
                "contents": [
                    {"type": "text", "text": "⚠️ ความเสี่ยงสำคัญ:", "size": "xs", "weight": "bold", "color": "#B42318"},
                    {"type": "text", "text": risk_text, "size": "xs", "color": "#4B5563", "wrap": True, "margin": "xs"},
                ],
            },
            # Next to watch
            {
                "type": "box",
                "layout": "vertical",
                "margin": "sm",
                "contents": [
                    {"type": "text", "text": "👀 สิ่งที่ควรติดตามต่อไป:", "size": "xs", "weight": "bold", "color": "#4B5563"},
                    {"type": "text", "text": watch_text, "size": "xs", "color": "#4B5563", "wrap": True, "margin": "xs"},
                ],
            },
            # Disclaimer
            {"type": "separator", "margin": "md"},
            {
                "type": "text",
                "text": "ข้อมูลนี้เป็นข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุนเฉพาะบุคคล",
                "size": "xxs",
                "color": "#9CA3AF",
                "wrap": True,
                "margin": "sm",
                "align": "center",
            },
        ])

        # Footer: Postback buttons: "Why?", "News", "Financials", "Refresh", "Schedule"
        footer_contents = {
            "type": "box",
            "layout": "vertical",
            "spacing": "xs",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "xs",
                    "contents": [
                        {
                            "type": "button",
                            "style": "secondary",
                            "height": "sm",
                            "action": {"type": "postback", "label": "💡 Why?", "data": f"action=why&symbol={symbol}"},
                        },
                        {
                            "type": "button",
                            "style": "secondary",
                            "height": "sm",
                            "action": {"type": "postback", "label": "📰 News", "data": f"action=news&symbol={symbol}"},
                        },
                    ],
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "xs",
                    "contents": [
                        {
                            "type": "button",
                            "style": "secondary",
                            "height": "sm",
                            "action": {"type": "postback", "label": "📊 Financials", "data": f"action=financials&symbol={symbol}"},
                        },
                        {
                            "type": "button",
                            "style": "secondary",
                            "height": "sm",
                            "action": {"type": "postback", "label": "🔄 Refresh", "data": f"action=refresh&symbol={symbol}"},
                        },
                    ],
                },
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {"type": "postback", "label": "⏰ Schedule รายงาน", "data": f"action=set_time"},
                },
            ],
        }

        return {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": body_contents,
            },
            "footer": footer_contents,
        }

    @classmethod
    def render_daily_digest_card(
        cls,
        summary_text: str,
        attention_count: int,
        top_stocks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create a daily digest card with market summary, stocks needing attention, and top 3 stocks."""
        stock_rows = []
        for item in top_stocks[:3]:
            sym = str(item.get('symbol', '')).upper()
            price = item.get('price', '-')
            outlook = item.get('outlook', 'Neutral')
            cfg = cls.OUTLOOK_CONFIG.get(outlook, cls.OUTLOOK_CONFIG['Neutral'])

            stock_rows.append({
                "type": "box",
                "layout": "horizontal",
                "margin": "sm",
                "contents": [
                    {"type": "text", "text": sym, "size": "sm", "weight": "bold", "color": "#1F2937", "flex": 2},
                    {"type": "text", "text": f"{price}", "size": "sm", "color": "#4B5563", "flex": 2},
                    {
                        "type": "text",
                        "text": outlook,
                        "size": "xxs",
                        "weight": "bold",
                        "color": cfg['color'],
                        "align": "end",
                        "flex": 2,
                    },
                ],
            })

        if not stock_rows:
            stock_rows = [{"type": "text", "text": "ไม่มีหุ้นใน Watchlist ของคุณ", "size": "xs", "color": "#9CA3AF"}]

        return {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "🌅 สรุปภาวะตลาดรายวัน (Daily Digest)",
                        "weight": "bold",
                        "size": "lg",
                        "color": "#111827",
                    },
                    {"type": "separator", "margin": "md"},
                    {
                        "type": "text",
                        "text": summary_text or "ภาพรวมตลาดและข้อมูลหุ้นในพอร์ตโฟลิโอของคุณประจำวัน",
                        "size": "xs",
                        "color": "#4B5563",
                        "wrap": True,
                        "margin": "md",
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "md",
                        "backgroundColor": "#FFF8E1" if attention_count > 0 else "#E8F5E9",
                        "cornerRadius": "md",
                        "paddingAll": "8px",
                        "contents": [
                            {
                                "type": "text",
                                "text": f"⚠️ หุ้นที่ต้องจับตาเป็นพิเศษ: {attention_count} ตัว",
                                "size": "xs",
                                "weight": "bold",
                                "color": "#8A6100" if attention_count > 0 else "#16803C",
                            }
                        ],
                    },
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": "⭐ หุ้นเด่นประจำวัน:", "size": "xs", "weight": "bold", "color": "#374151", "margin": "md"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "sm",
                        "contents": stock_rows,
                    },
                    {"type": "separator", "margin": "md"},
                    {
                        "type": "text",
                        "text": "ข้อมูลเพื่อการศึกษาและประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน",
                        "size": "xxs",
                        "color": "#9CA3AF",
                        "align": "center",
                        "margin": "sm",
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#16803C",
                        "height": "sm",
                        "action": {"type": "postback", "label": "ดูรายงานทั้งหมด", "data": "action=get_report"},
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "height": "sm",
                        "action": {"type": "postback", "label": "รายการหุ้น", "data": "action=view_watchlist"},
                    },
                ],
            },
        }
