"""News cleaning, dedup and impact-ranking helpers.

The upstream source is Google News RSS titles which are messy: long redirect
URLs, "$undefined$" template artifacts, duplicated stories across publishers
and mixed company/macro items. This module turns them into a clean ranked list
so the AI receives a small high-signal digest instead of raw noise.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

_URL_RE = re.compile(r'https?://\S+')
_UNDEFINED_RE = re.compile(r'\$[^$]{0,40}undefined[^$]{0,40}\$', re.IGNORECASE)
_STRAY_DOLLAR_RE = re.compile(r'\$undefined\$|\$(?=\s)|(?<=\s)\$')
# Publisher tail: Google News titles end with " - Publisher"
_PUBLISHER_TAIL_RE = re.compile(r'\s+-\s+([A-Za-z0-9ก-๙.\' ]{2,40})$')

# Thai/English keyword weights — higher = likely bigger price mover.
_IMPACT_KEYWORDS: List[tuple[str, int]] = [
    ('งบ', 5), ('กำไร', 5), ('ผลประกอบการ', 5), ('earnings', 5), ('guidance', 5),
    ('ซื้อกิจการ', 5), ('เข้าซื้อ', 5), ('ควบรวม', 5), ('merger', 5), ('acquisition', 5),
    ('ปันผล', 4), ('dividend', 4), ('buyback', 4), ('แตกตัว', 3), ('split', 3),
    ('ลดทุน', 5), ('เพิ่มทุน', 4), ('คดี', 4), ('ฟ้อง', 4), ('lawsuit', 4), ('probe', 4),
    ('FDA', 4), ('ภาษี', 3), ('tariff', 4), ('แบน', 4), ('ห้าม', 3),
    ('ราคาน้ำมัน', 3), ('ดอกเบี้ย', 4), ('เฟด', 4), ('Fed', 4), ('เงินบาท', 3),
    ('GDP', 3), ('เงินเฟ้อ', 4), ('inflation', 4), ('CPI', 4),
    ('จ่ายตลาด', 2), ('กระทบ', 3), ('ทยอยซื้อ', 2), ('ทยอยขาย', 2),
    ('ค้างสร้าง', 1), ('โรงงาน', 2), ('ส่งออก', 3), ('สัญญา', 2),
]

_MACRO_HINTS = ('[macro]', 'ดัชนี', 'ตลาดหุ้น', 'set ', 'dow ', 'nasdaq', 's&p',
                'เฟด', 'fed ', 'ธปท', 'แบงก์ชาติ', 'oil', 'น้ำมัน', 'ทองคำ', 'ผู้ลงทุนรายใหญ่')


def clean_headline(title: str) -> str:
    """Remove URLs, $undefined$ artifacts and collapse whitespace."""
    text = str(title or '')
    text = _UNDEFINED_RE.sub('', text)
    text = _URL_RE.sub('', text)
    text = text.replace('$undefined$', '')
    text = _STRAY_DOLLAR_RE.sub('', text)
    text = re.sub(r'\s+', ' ', text).strip()
    # Trim dangling separators left after URL/artifact removal
    text = re.sub(r'[\s\-–—:,(]+$', '', text).strip()
    return text


def publisher_of(title: str) -> str:
    """Extract the trailing publisher name from a Google News title."""
    match = _PUBLISHER_TAIL_RE.search(str(title or ''))
    return match.group(1).strip() if match else ''


def headline_fingerprint(title: str) -> str:
    """Normalize a headline for dedup comparison (drop publisher & digits)."""
    text = clean_headline(title).lower()
    text = _PUBLISHER_TAIL_RE.sub('', text)
    text = re.sub(r'[\d.,%]+', '#', text)
    text = re.sub(r'[^a-z0-9ก-๙#]+', '', text)
    return text


def impact_score(title: str) -> int:
    """Keyword-driven impact estimate; company-specific beats generic macro."""
    text = str(title or '').lower()
    score = sum(w for kw, w in _IMPACT_KEYWORDS if kw in text)
    if any(h in text for h in _MACRO_HINTS):
        score = max(1, score - 1)  # generic macro slightly de-prioritized
    return score


def clean_and_rank(
    items: Iterable[Dict[str, Any]],
    max_items: int = 8,
) -> List[Dict[str, Any]]:
    """Deduplicate + rank news dicts ({title,url,published_at,source_type}).

    Ranking: impact keywords first, then company news before macro, newest
    first as tiebreaker. Output items carry clean_title/publisher/impact_score.
    """
    seen: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    for item in items:
        title = str(item.get('title') or item.get('headline') or '').strip()
        if not title:
            continue
        clean = clean_headline(title)
        if not clean or len(clean) < 8:
            continue
        fp = headline_fingerprint(clean)
        if fp and fp in seen:
            continue
        seen.add(fp)
        cleaned.append({
            'title': clean,
            'url': str(item.get('url') or ''),
            'published_at': str(item.get('published_at') or ''),
            'source_type': str(item.get('source_type') or 'news'),
            'publisher': publisher_of(title),
            'impact_score': impact_score(clean),
        })
    cleaned.sort(
        key=lambda x: (x['impact_score'], 0 if x['source_type'] == 'company_news' else 1),
        reverse=True,
    )
    return cleaned[:max_items]


def short_line(item: Dict[str, Any], max_len: int = 90) -> str:
    """Compact single-line view for the brief card: title (+ publisher)."""
    publisher = item.get('publisher') or ''
    title = str(item.get('title') or '')
    line = f"{title} — {publisher}" if publisher and publisher not in title else title
    if len(line) > max_len:
        line = line[: max_len - 1].rstrip() + '…'
    return line
