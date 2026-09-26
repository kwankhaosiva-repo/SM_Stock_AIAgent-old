"""Dedicated Flex card for the "News" button: every kept headline ranked by
expected price impact with publisher, one-line 'why it matters' and a
clickable URL button per item.

Input is the `news_detail` list produced by analysis.news_analysis.analyze_news.
"""
from __future__ import annotations

from typing import Any, Dict, List

_IMPACT_CFG = {
    'Positive': {'emoji': '🟢', 'color': '#16803C'},
    'Mixed': {'emoji': '🟡', 'color': '#8A6100'},
    'Negative': {'emoji': '🔴', 'color': '#B42318'},
}


def render_news_detail_card(symbol: str, brief: Dict[str, Any]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = [i for i in (brief.get('news_detail') or []) if isinstance(i, dict)]
    if not items:
        items = [
            {'no': i, 'title': str(t)[:120], 'publisher': '', 'url': '', 'impact': 'Mixed', 'why': ''}
            for i, t in enumerate((brief.get('news') or [])[:5], 1)
        ]

    provider = str(brief.get('provider') or 'ai')
    provider_label = 'โหมดสำรอง' if provider == 'fallback' else f'AI: {provider}'
    news_count = brief.get('news_count')

    contents: List[Dict[str, Any]] = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "flex": 1,
                    "contents": [
                        {"type": "text", "text": "📰 ข่าวที่กระทบราคา (เรียงตามน้ำหนัก)", "size": "xxs", "color": "#6B7280"},
                        {"type": "text", "text": str(symbol).upper(), "weight": "bold", "size": "xl", "color": "#111827"},
                    ],
                },
            ],
        },
    ]
    if news_count:
        contents.append({
            "type": "text",
            "text": f"คัดกรองจาก {news_count} ข่าวล่าสุด • เรียงจากกระทบมากไปน้อย",
            "size": "xxs",
            "color": "#6B7280",
            "margin": "sm",
            "wrap": True,
        })

    for item in items[:6]:
        impact = str(item.get('impact') or 'Mixed')
        cfg = _IMPACT_CFG.get(impact, _IMPACT_CFG['Mixed'])
        no = item.get('no', '')
        title = str(item.get('title') or '')[:120]
        publisher = str(item.get('publisher') or '')
        # Google News titles embed the publisher as "... - Name"; drop the
        # tail when we already show the publisher separately.
        if publisher and title.lower().endswith(f'- {publisher.lower()}'):
            title = title[: -len(publisher) - 2].rstrip(' -')
        why = str(item.get('why') or '')
        url = str(item.get('url') or '')

        row_children: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": f"{no}. {cfg['emoji']} {title}",
                "size": "xs",
                "weight": "bold",
                "color": "#1F2937",
                "wrap": True,
                "flex": 1,
            }
        ]
        meta_bits = []
        if publisher:
            meta_bits.append(publisher)
        if impact:
            meta_bits.append(f"{cfg['emoji']} {impact}")
        if meta_bits:
            row_children.append({
                "type": "text",
                "text": ' • '.join(meta_bits),
                "size": "xxs",
                "color": cfg['color'],
                "align": "end",
                "flex": 0,
            })
        contents.append({
            "type": "box",
            "layout": "horizontal",
            "margin": "md",
            "spacing": "xs",
            "contents": row_children,
        })
        if why:
            contents.append({
                "type": "text",
                "text": f"→ {why}",
                "size": "xxs",
                "color": "#4B5563",
                "wrap": True,
                "margin": "xs",
            })
        if url:
            contents.append({
                "type": "button",
                "style": "link",
                "height": "sm",
                "color": "#1D4ED8",
                "action": {"type": "uri", "label": "🔗 อ่านต้นฉบับ", "uri": url},
                "margin": "xs",
            })

    contents.extend([
        {"type": "separator", "margin": "md"},
        {
            "type": "text",
            "text": f"ข้อมูลเพื่อประกอบการพิจารณา ไม่ใช่คำแนะนำการลงทุน ({provider_label})",
            "size": "xxs",
            "color": "#9CA3AF",
            "wrap": True,
            "align": "center",
            "margin": "sm",
        },
    ])

    return {
        "type": "bubble",
        "size": "mega",
        "body": {"type": "box", "layout": "vertical", "contents": contents},
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "xs",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {"type": "postback", "label": "📊 Financials", "data": f"action=financials&symbol={str(symbol).upper()}"},
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {"type": "postback", "label": "🔄 Refresh", "data": f"action=refresh&symbol={str(symbol).upper()}"},
                },
            ],
        },
    }
