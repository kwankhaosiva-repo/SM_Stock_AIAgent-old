from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from analysis.chart_service import ChartService
from analysis.news_cleaning import clean_headline

# Reason strings that carry no information for the reader.
_PLACEHOLDER_RE = re.compile(r'ไม่มีข้อมูล|ไม่พบข้อมูล|ไม่สามารถ|ประเมินไม่ได้|^\s*[-–—]?\s*$')
# Citation markers like [6] / [1][3] — meaningful only inside the detail card.
_CITATION_RE = re.compile(r'\s*\[\d+\]\s*')
# Source-bucket tags the AI sometimes embeds — normalized (not stripped) so
# every reason line carries ONE readable provenance tag: [จากข่าว] ฯลฯ
_BUCKET_TAG_RE = re.compile(r'\s*\[(?:จากข่าว|จากงบ(?:การเงิน)?|จากสถิติ|จากตัวเลข(?:สถิติ)?|จากข้อมูลสถิติ|news|financials?|stats?|macro)\]\s*', re.IGNORECASE)

# Advice-tone classifier: each recommendation line gets a traffic-light tag
# (English keywords — visually scannable, as chosen by product decision).
_ADVICE_TONES = {
    'Positive': {'emoji': '🟢', 'label': 'Positive', 'color': '#16803C'},
    'Negative': {'emoji': '🔴', 'label': 'Negative', 'color': '#B42318'},
    'Watch': {'emoji': '🟡', 'label': 'Watch', 'color': '#8A6100'},
}
_ADVICE_NEG_KW = ('ควรขาย', 'ทยอยขาย', 'ลดสัดส่วน', 'หลีกเลี่ยง', 'เสี่ยงขาดทุน', 'กดดัน', 'ลดลง', 'ร่วง', 'ดิ่ง', 'โดนขาย', 'ฟ้อง', 'คดี', 'ปรับลด', 'ต่ำกว่าคาด', 'ขาดทุน', 'sell', 'avoid', 'downside', 'negative', 'threat', 'risk')
_ADVICE_WATCH_KW = ('จับตา', 'ติดตาม', 'รอดู', 'ระวัง', 'รอให้', 'เฝ้าดู', 'ช่วงระวัง', 'โซนกลาง', 'แนวรับ', 'แนวต้าน', 'ผันผวน', 'watch', 'hold', 'monitor', 'wait')
_ADVICE_POS_KW = ('ซื้อ', 'สะสม', 'โอกาส', 'น่าสนใจ', 'แข็งแรง', 'จุดเข้า', 'เป้าหมาย', 'เพิ่มขึ้น', 'เติบโต', 'ขยาย', 'เพิ่มถือ', 'เพิ่มสัดส่วน', 'ซื้อกิจการ', 'ทะลุ', 'ผ่านแนวต้าน', 'ต่ำกว่ามูลค่า', 'ถูกกว่ามูลค่า', 'ขาขึ้น', 'buy', 'accumulate', 'positive', 'upside', 'growth', 'expand')

# Provenance tag shown before EVERY reason line so the reader always knows
# which evidence bucket backs it: news / financial statements / statistics.
_BUCKET_TAGS = {'news': '[จากข่าว]', 'financials': '[จากงบ]', 'stats': '[จากสถิติ]'}


def _advice_tone(text: str) -> Optional[Dict[str, str]]:
    """Traffic-light tag for one advice line; None = neutral (no tag)."""
    t = str(text or '').lower()
    if any(k in t for k in _ADVICE_NEG_KW):
        return _ADVICE_TONES['Negative']
    if any(k in t for k in _ADVICE_WATCH_KW):
        return _ADVICE_TONES['Watch']
    if any(k in t for k in _ADVICE_POS_KW):
        return _ADVICE_TONES['Positive']
    return None


def _reason_tone(text: str) -> Dict[str, str]:
    """Tone for a reason line — NEVER None: lines without a detectable
    signal default to 🟡 Watch so every reason line carries a traffic light."""
    return _advice_tone(text) or _ADVICE_TONES['Watch']
# Stats reasons that merely restate numbers already shown in the metrics grid.
_REDUNDANT_STATS_RE = re.compile(r'^(ราคาล่าสุด|RSI\(|ความผันผวน|Volatility|Dividend|P/E)', re.IGNORECASE)


def _clean_reason(text: Any, max_len: int = 110) -> str:
    """Normalize an AI/source reason line: strip URLs/citations, keep one
    provenance tag like [จากข่าว] (tags get re-added per bucket by callers)."""
    cleaned = clean_headline(str(text or ''))
    cleaned = _CITATION_RE.sub(' ', cleaned)
    cleaned = _BUCKET_TAG_RE.sub(' ', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + '…'
    return cleaned


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

        # Reasons section — split into 3 evidence buckets so the user knows
        # WHERE each reason comes from: news / financial statements / stats.
        cats = report.get('reason_categories') or {}
        if not cats:
            # Legacy reports without categories — tag heuristically.
            from workflows.report_workflow import ReportWorkflow
            legacy_advice = advice if isinstance(advice, dict) else advice.to_dict()
            cats = ReportWorkflow._categorized_reasons_from_list(
                legacy_advice.get('reasons') or [report.get('reason') or "ไม่มีข้อมูลเชิงลึก"]
            )
        section_defs = [
            ('news', '📰 จากข่าว', cats.get('news') or [], '#16803C', False),
            ('financials', '🏦 จากงบการเงิน', cats.get('financials') or [], '#1D4ED8', False),
            ('stats', '📊 จากตัวเลขสถิติ', cats.get('stats') or [], '#B45309', True),
        ]
        reason_sections = []
        for bucket, title, items, color, drop_redundant in section_defs:
            tag = _BUCKET_TAGS[bucket]
            items = [
                t for t in (_clean_reason(i) for i in items)
                if t and not _PLACEHOLDER_RE.search(t)
                and not (drop_redundant and _REDUNDANT_STATS_RE.match(t))
            ][:2]
            if not items:
                continue
            rows = []
            for item in items:
                tone = _reason_tone(item)
                prefix = f"{tag} "
                display = f"{prefix}{tone['emoji']} {tone['label']} — {item}" if tone else f"{prefix}{item}"
                rows.append({
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": "•", "size": "xs", "color": color, "flex": 0},
                        {"type": "text", "text": display, "size": "xs", "color": "#333333", "wrap": True, "flex": 1},
                    ],
                })
            reason_sections.extend([
                {"type": "text", "text": title, "size": "xs", "weight": "bold", "color": color, "margin": "md"},
                {"type": "box", "layout": "vertical", "margin": "xs", "spacing": "xs", "contents": rows},
            ])
        if not reason_sections:
            reason_sections = [{"type": "text", "text": "ยังไม่มีเหตุผลเชิงประจักษ์ในรอบนี้", "size": "xs", "color": "#9CA3AF"}]

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
            {"type": "text", "text": "📌 เหตุผลเชิงประจักษ์ (แยกตามแหล่งข้อมูล):", "size": "xs", "weight": "bold", "color": "#374151", "margin": "md"},
            {
                "type": "box",
                "layout": "vertical",
                "margin": "sm",
                "spacing": "xs",
                "contents": reason_sections,
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
                    {"type": "text", "text": f"{(_advice_tone(watch_text) or _ADVICE_TONES['Watch'])['emoji']} {watch_text}", "size": "xs", "color": "#4B5563", "wrap": True, "margin": "xs"},
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
    def render_market_brief_card(cls, symbol: str, brief: Dict[str, Any]) -> Dict[str, Any]:
        """Render the AI news-analysis Market Brief as a Flex bubble.

        `brief` is the dict produced by analysis.news_analysis.analyze_news:
        summary, news[], impact (Positive|Mixed|Negative), advice[], disclaimer,
        provider.
        """
        impact = str(brief.get('impact', 'Mixed'))
        if impact not in ('Positive', 'Mixed', 'Negative'):
            impact = 'Mixed'
        impact_cfg = {
            'Positive': {'color': '#16803C', 'bg': '#E8F5E9', 'emoji': '🟢'},
            'Mixed': {'color': '#8A6100', 'bg': '#FFF8E1', 'emoji': '🟡'},
            'Negative': {'color': '#B42318', 'bg': '#FFEBEE', 'emoji': '🔴'},
        }[impact]
        cfg = impact_cfg

        sym = str(symbol).upper()
        provider = str(brief.get('provider') or 'ai')
        provider_label = 'โหมดสำรอง (ตัวเลขล้วน)' if provider == 'fallback' else f'AI: {provider}'

        # Telegram-style flash (2 one-liners) — the deep ranked list with
        # clickable links lives behind the News button, not on this card.
        # Summary — strip citation markers ([6]) that only make sense in the
        # ranked detail view, then trim to a readable length.
        summary_text = _CITATION_RE.sub(' ', str(brief.get('summary') or ''))
        summary_text = re.sub(r'\s{2,}', ' ', summary_text).strip()
        if len(summary_text) > 260:
            summary_text = summary_text[:259].rstrip() + '…'

        flash = [str(f) for f in (brief.get('news_flash') or [])][:2]
        if not flash:
            flash = [str(n) for n in (brief.get('news') or [])][:2]
        news_count = brief.get('news_count')
        raw_count = brief.get('raw_count')
        news_header = '🗞 ข่าวเด่น'
        if news_count:
            if raw_count and raw_count > news_count:
                news_header += f' (คัด {news_count} จากที่ดึงมา {raw_count} ข่าว)'
            else:
                news_header += f' (คัดจาก {news_count} ข่าวล่าสุด)'
        flash_rows = [
            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "xs",
                "contents": [
                    {"type": "text", "text": "•", "size": "xs", "color": cfg['color'], "flex": 0},
                    {"type": "text", "text": f[:90], "size": "xs", "color": "#333333", "wrap": True, "flex": 1},
                ],
            }
            for f in flash
        ]
        if not flash_rows:
            flash_rows = [{"type": "text", "text": "ไม่มีข่าวสารล่าสุดในระบบ", "size": "xs", "color": "#9CA3AF"}]

        # Categorized reasons: news / financials / stats
        cats = brief.get('reasons') or {}
        cat_defs = [
            ('news', '📰', cats.get('news') or [], '#16803C'),
            ('financials', '🏦', cats.get('financials') or [], '#1D4ED8'),
            ('stats', '📊', cats.get('stats') or [], '#B45309'),
        ]
        reason_rows = []
        for bucket, emoji, items, color in cat_defs:
            tag = _BUCKET_TAGS[bucket]
            cleaned_items = [
                t for t in (_clean_reason(i) for i in (items or []))
                if t and not _PLACEHOLDER_RE.search(t)
            ][:2]
            for item in cleaned_items:
                tone = _reason_tone(item)
                prefix = f"{tag} "
                if tone:
                    prefix += f"{tone['emoji']} {tone['label']} — "
                reason_rows.append({
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": emoji, "size": "xs", "flex": 0},
                        {"type": "text", "text": f"{prefix}{item}", "size": "xs", "color": "#333333", "wrap": True, "flex": 1},
                    ],
                })

        advice_rows = []
        for idx, a in enumerate((brief.get('advice') or [])[:4], 1):
            advice_text = _clean_reason(a, max_len=140)
            tone = _reason_tone(advice_text)
            number_color = tone['color'] if tone else '#6B7280'
            prefix = f"{tone['emoji']} {tone['label']} — " if tone else ''
            advice_rows.append({
                "type": "box",
                "layout": "horizontal",
                "spacing": "xs",
                "contents": [
                    {"type": "text", "text": f"{idx}.", "size": "xs", "color": number_color, "flex": 0, "weight": "bold"},
                    {"type": "text", "text": f"{prefix}{advice_text}", "size": "xs", "color": "#333333", "wrap": True, "flex": 1},
                ],
            })
        if not advice_rows:
            advice_rows = [{"type": "text", "text": "ติดตามข่าวสารก่อนตัดสินใจ", "size": "xs", "color": "#4B5563"}]

        body_contents = [
            # Header: symbol + impact badge
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": f"📰 Market Brief", "size": "xxs", "color": "#6B7280"},
                            {"type": "text", "text": sym, "weight": "bold", "size": "xl", "color": "#111827"},
                        ],
                        "flex": 1,
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "text",
                                "text": f"{cfg['emoji']} {impact}",
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
            # Summary
            {
                "type": "text",
                "text": summary_text,
                "size": "xs",
                "color": "#1F2937",
                "wrap": True,
                "margin": "md",
            },
            {"type": "separator", "margin": "md"},
            # Top news flash (2 one-liners; full ranked detail behind News button)
            {"type": "text", "text": news_header, "size": "xs", "weight": "bold", "color": "#374151", "margin": "md", "wrap": True},
            {
                "type": "box",
                "layout": "vertical",
                "margin": "sm",
                "spacing": "xs",
                "contents": flash_rows,
            },
            # Advice — tagged by source bucket (news/financials/stats)
            {"type": "separator", "margin": "md"},
            {"type": "text", "text": "💡 คำแนะนำ:", "size": "xs", "weight": "bold", "color": "#374151", "margin": "md"},
            {
                "type": "box",
                "layout": "vertical",
                "margin": "sm",
                "spacing": "xs",
                "contents": (advice_rows if not reason_rows else advice_rows + [
                    {"type": "separator", "margin": "sm"},
                    {"type": "text", "text": "🧭 เหตุผลแยกตามแหล่งข้อมูล:", "size": "xxs", "weight": "bold", "color": "#374151"},
                    {"type": "box", "layout": "vertical", "margin": "xs", "spacing": "xs", "contents": reason_rows},
                ]),
            },
            # Disclaimer + provider
            {"type": "separator", "margin": "md"},
            {
                "type": "text",
                "text": f"{brief.get('disclaimer', 'ข้อมูลเพื่อประกอบการพิจารณา ไม่ใช่คำแนะนำการลงทุน')} ({provider_label})",
                "size": "xxs",
                "color": "#9CA3AF",
                "wrap": True,
                "align": "center",
                "margin": "sm",
            },
        ]

        return {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": body_contents,
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "xs",
                "contents": [
                    {
                        "type": "button",
                        "style": "secondary",
                        "height": "sm",
                        "action": {"type": "postback", "label": "📊 Financials", "data": f"action=financials&symbol={sym}"},
                    },
                    {
                        "type": "button",
                        "style": "secondary",
                        "height": "sm",
                        "action": {"type": "postback", "label": "🔄 Refresh", "data": f"action=refresh&symbol={sym}"},
                    },
                ],
            },
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
                "layout": "vertical",
                "margin": "sm",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
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
                    },
                ],
            })
            # One-line evidence under each stock (news -> financials -> stats)
            reason = _clean_reason(item.get('reason'))
            if reason and not _PLACEHOLDER_RE.search(reason) and not _REDUNDANT_STATS_RE.match(reason):
                digest_tag = _BUCKET_TAGS.get(str(item.get('reason_bucket') or ''), '')
                digest_line = f"{digest_tag} {reason}" if digest_tag else reason
                stock_rows.append(                    {
                        "type": "text",
                        "text": f"↳ {digest_line[:110]}{'…' if len(digest_line) > 110 else ''}",
                        "size": "xxs",
                        "color": "#6B7280",
                        "wrap": True,
                        "margin": "xs",
                        "offsetStart": "12px",
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

    @staticmethod
    def render_daily_digest_text(summary_text: str, collected_reports: List[Dict[str, Any]]) -> str:
        """Plain-text digest used as the last-resort fallback when the Flex
        payload is rejected by the LINE API — the user must never get silence."""
        lines = [f"📊 {summary_text}", ""]
        for r in collected_reports[:3]:
            sym = str(r.get('symbol', '')).upper()
            price = r.get('metrics', {}).get('price', '-')
            outlook = r.get('signal') or r.get('advice', {}).get('outlook') or 'Neutral'
            lines.append(f"• {sym} @ {price} — {outlook}")
            rcats = r.get('reason_categories') or {}
            bucket = next((b for b in ('news', 'financials', 'stats') if rcats.get(b)), None)
            reason = (rcats.get(bucket) or [''])[0] if bucket else ''
            if reason:
                tag = _BUCKET_TAGS.get(bucket, '')
                lines.append(f"  ↳ {tag + ' ' if tag else ''}{reason}")
        lines.append("")
        lines.append("(แสดงแบบข้อความธรรมดา — การ์ดเต็มใช้ไม่ได้ชั่วคราว)")
        return "\n".join(lines)
