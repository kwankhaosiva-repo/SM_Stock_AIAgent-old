"""News -> AI analysis -> Thai advice summary (Market Brief style).

Pipeline: raw RSS headlines -> cleaned/deduped/impact-ranked digest -> LLM
synthesis with a strict JSON contract -> two-level output:

- Card summary (`news_flash`): 2 telegram-style one-liners.
- "News" button detail (`news_detail`): every kept item ranked by market
  impact with publisher, clickable URL and one-line "why it matters".

Reasons are grouped into three buckets so the user can tell WHERE each
conclusion comes from: news / financial statements / accounting-statistics.
Uses the LLMRouter (free-tier failover); falls back to a deterministic
numbers-only summary when no provider answers.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from analysis.indicators import infer_trend
from analysis.news_cleaning import clean_and_rank, short_line
from llm_providers import LLMRouter, ProviderError
from models.analysis_models import MarketSnapshotData

_SYSTEM = (
    "คุณเป็นนักวิเคราะห์การเงินชาวไทย เขียนสรุปข่าวหุ้นภาษาไทยแบบ 'โทรเลขย่อ' "
    "สั้น กระชับ ตรงประเด็น ไม่ใช้คำฟุ่มเฟือย ไม่เรียงข่าวทีละข่าวแต่สังเคราะห์รวม "
    "อิงเฉพาะข้อมูลที่ให้ ห้ามการันตีผลกำไร ห้ามเดาข่าวที่ไม่มีในรายการ"
)

_ALLOWED_IMPACT = ('Positive', 'Mixed', 'Negative')


def _extract_cited(text: str) -> List[int]:
    """Which [n] news numbers the analysis actually referenced."""
    import re

    return sorted(set(int(n) for n in re.findall(r"\[(\d+)\]", text or "")))


def _news_digest(
    snapshot: MarketSnapshotData, extra_news: Optional[List[str]]
) -> List[Dict[str, Any]]:
    """Cleaned, deduped, impact-ranked news with URLs kept for the News view."""
    raw: List[Dict[str, Any]] = [
        {
            'title': s.title,
            'url': s.url,
            'published_at': s.published_at,
            'source_type': s.source_type,
        }
        for s in snapshot.sources
    ]
    for item in extra_news or []:
        raw.append({'title': item, 'url': '', 'published_at': '', 'source_type': 'news'})
    return clean_and_rank(raw, max_items=8)


def _technical_context(snapshot: MarketSnapshotData) -> str:
    """Human-readable technical state incl. HOW support/resistance were derived."""
    tech = snapshot.technicals
    parts: List[str] = []
    support = tech.get('support')
    resistance = tech.get('resistance')
    if support not in (None, '-', 'N/A') and resistance not in (None, '-', 'N/A'):
        parts.append(
            f"แนวรับ {support} = จุดต่ำสุดย้อนหลัง 30 วันทำการ, แนวต้าน {resistance} = จุดสูงสุดย้อนหลัง 30 วันทำการ"
        )
    rsi = tech.get('rsi')
    if rsi not in (None, '-', 'N/A'):
        stance = 'ใกล้ overbought (ระวังย่อ)' if float(rsi) >= 65 else 'ใกล้ oversold (อาจพ้นตัว)' if float(rsi) <= 35 else 'โซนกลาง'
        parts.append(f"RSI(14) {rsi} ({stance})")
    sma20 = tech.get('sma20')
    sma50 = tech.get('sma50')
    try:
        p = float(snapshot.price)
        s20 = float(sma20) if sma20 not in (None, '-', 'N/A') else None
        s50 = float(sma50) if sma50 not in (None, '-', 'N/A') else None
        if s20 and s50:
            if p > s20 > s50:
                parts.append('ราคายืนเหนือ SMA20 และ SMA50 = แนวโน้มขึ้นทั้งระยะสั้น/กลาง')
            elif p < s20 < s50:
                parts.append('ราคาจมใต้ SMA20 และ SMA50 = แนวโน้มลงชัดเจน')
            else:
                parts.append('เส้น MA ยังไม่เรียงตัว แนวโน้มไม่ชัด')
        yh = tech.get('year_high')
        yl = tech.get('year_low')
        if yh not in (None, '-', 'N/A') and yl not in (None, '-', 'N/A'):
            yhf, ylf = float(yh), float(yl)
            if yhf > ylf:
                pos = ((p - ylf) / (yhf - ylf)) * 100
                parts.append(f"ราคาอยู่ {pos:.0f}% ของช่วง 52 สัปดาห์ ({ylf:,.2f}–{yhf:,.2f})")
    except (TypeError, ValueError):
        pass
    return '; '.join(parts)


def _stat_reasons(snapshot: MarketSnapshotData) -> List[str]:
    """Deterministic reasons derived from accounting/statistical numbers."""
    reasons: List[str] = []
    tech = snapshot.technicals
    support = tech.get('support')
    resistance = tech.get('resistance')
    if support not in (None, '-', 'N/A') and resistance not in (None, '-', 'N/A'):
        reasons.append(
            f"แนวรับ/แนวต้าน {support}/{resistance} คำนวณจาก จุดต่ำสุด-สูงสุดราคาย้อนหลัง 30 วันทำการ (swing low/high)"
        )
    rsi = tech.get('rsi')
    if rsi not in (None, '-', 'N/A'):
        try:
            r = float(rsi)
            stance = (
                'เขต overbought ระวังย่อ' if r >= 65
                else 'เขต oversold จังหวะเด้งมีโอกาส' if r <= 35
                else 'โซนกลาง โมเมนตัมไม่บ่งชี้ทิศทาง'
            )
            reasons.append(f"RSI(14) = {rsi} ({stance})")
        except (TypeError, ValueError):
            pass
    pe = snapshot.pe_ratio
    if pe not in (None, '-', 'N/A', 0):
        try:
            reasons.append(f"P/E = {float(pe):.1f} เท่า — นั่นคือราคาที่ผู้ลงทุนยอมจ่ายต่อกำไร 1 บาทต่อปี")
        except (TypeError, ValueError):
            pass
    return reasons


def _fallback_brief(
    snapshot: MarketSnapshotData, digest: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Deterministic brief when every AI provider failed."""
    outlook = infer_trend(snapshot.price, snapshot.technicals)
    flash = [short_line(item) for item in digest[:2]]
    detail = [
        {
            'no': idx,
            'title': item['title'][:120],
            'publisher': item.get('publisher') or '',
            'url': item.get('url') or '',
            'impact': 'Mixed',
            'why': 'โหมดสำรอง: ยังไม่มีการวิเคราะห์จาก AI — อ่านหัวข้อข่าวพร้อมลิงก์ด้านล่างประกอบการตัดสินใจ',
        }
        for idx, item in enumerate(digest[:5], 1)
    ]
    stat_reasons = _stat_reasons(snapshot)
    advice: List[str] = [
        "ติดตามข่าวที่อ้างอิงด้านบนก่อนตัดสินใจ (AI วิเคราะห์ไม่ได้ในรอบนี้)"
    ]
    if stat_reasons:
        advice.append(stat_reasons[0])
    return {
        "summary": (
            f"{snapshot.symbol} ราคา {snapshot.price:,.2f} มุมมองเชิงเทคนิค {outlook} "
            "(โหมดสำรอง: AI ไม่พร้อมใช้ สรุปจากตัวเลขล้วน)"
        ),
        "impact": "Mixed",
        "news_flash": flash,
        "news_detail": detail,
        "reasons": {"news": [], "financials": [], "stats": stat_reasons[:2]},
        "advice": advice,
        "disclaimer": "ข้อมูลเพื่อประกอบการพิจารณา ไม่ใช่คำแนะนำการลงทุน",
        # Legacy keys for older renderers (web chat / discord)
        "news": flash,
    }


def _validate_detail(data: Any, digest: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sanitize AI news_detail anchored to digest numbers.

    The AI returns `no` referencing the numbered digest; title/publisher/url
    always come from the canonical digest entry (so paraphrased or typo'd AI
    titles can never create duplicates or fabricated URLs). Impact/why are
    taken from the AI. Digest items the AI skipped are appended at the end.
    """
    from analysis.news_cleaning import headline_fingerprint

    by_no = {idx: item for idx, item in enumerate(digest, 1)}
    fp_to_no = {headline_fingerprint(item['title']): idx for idx, item in by_no.items()}
    details: List[Dict[str, Any]] = []
    used_nos: set[int] = set()

    def _entry(no: int, impact: str, why: str) -> Dict[str, Any]:
        src = by_no[no]
        return {
            'no': no,
            'title': src['title'][:140],
            'publisher': src.get('publisher') or '',
            'url': src.get('url') or '',
            'impact': impact if impact in _ALLOWED_IMPACT else 'Mixed',
            'why': str(why or '')[:220],
        }

    for raw in list(data or [])[:8]:
        if not isinstance(raw, dict) or len(details) >= 6:
            continue
        impact = str(raw.get('impact') or 'Mixed')
        why = str(raw.get('why') or '')
        try:
            no = int(raw.get('no'))
        except (TypeError, ValueError):
            no = 0
        if no in by_no and no not in used_nos:
            used_nos.add(no)
            details.append(_entry(no, impact, why))
            continue
        # Missing/bad number — match by title fingerprint against the digest.
        fp = headline_fingerprint(str(raw.get('title') or ''))
        matched = fp_to_no.get(fp)
        if matched and matched not in used_nos:
            used_nos.add(matched)
            details.append(_entry(matched, impact, why))

    # Fill digest items the AI skipped (keeps the News view complete)
    for no in by_no:
        if len(details) >= 6:
            break
        if no not in used_nos:
            used_nos.add(no)
            details.append(_entry(no, 'Mixed', ''))

    details = [d for d in details if d['title']]
    details.sort(key=lambda d: d['no'])  # keep digest impact ranking order
    for i, d in enumerate(details, 1):
        d['no'] = i
    return details


def _reasons_block(reasons: Dict[str, Any]) -> str:
    """Flatten categorized reasons for the AI prompt/legacy consumers."""
    lines: List[str] = []
    for bucket, emoji in (('news', '📰'), ('financials', '🏦'), ('stats', '📊')):
        for item in (reasons.get(bucket) or [])[:2]:
            if item:
                lines.append(f"{emoji} {item}")
    return '\n'.join(lines)


def analyze_news(
    snapshot: MarketSnapshotData,
    profile: Optional[Dict[str, str]] = None,
    extra_news: Optional[List[str]] = None,
    router: Optional[LLMRouter] = None,
) -> Dict[str, Any]:
    """Caller supplies a cached snapshot (and optional raw headlines);
    the AI turn is delegated to the provider router."""
    router = router or LLMRouter()
    trend = infer_trend(snapshot.price, snapshot.technicals)
    digest = _news_digest(snapshot, extra_news)
    news_count = len(digest)
    tech_ctx = _technical_context(snapshot)
    stat_reasons = _stat_reasons(snapshot)

    # Numbered digest for the prompt — impact score guides the AI's ranking.
    news_block = '\n'.join(
        f"[{idx}] {item['title']}"
        + (f" (แหล่ง: {item['publisher']})" if item.get('publisher') else '')
        + (f" | url: {item['url']}" if item.get('url') else '')
        + f" | impact_score: {item['impact_score']}"
        for idx, item in enumerate(digest, 1)
    ) or '(ไม่มีข่าวในระบบ)'

    prompt = (
        f"{_SYSTEM}\n\n"
        f"หุ้น: {snapshot.symbol} | ราคาปัจจุบัน {snapshot.price:,.2f} | "
        f"P/E {snapshot.pe_ratio or 'N/A'} | Dividend {snapshot.div_yield or 'N/A'}%\n"
        f"ข่าวที่คัดกรองแล้วทั้งหมด {news_count} ข่าว (เรียงตามน้ำหนักคร่าวๆ ให้ตรวจสอบซ้ำ):\n"
        f"{news_block}\n\n"
        + (f"บริบทเทคนิค: {tech_ctx}\n\n" if tech_ctx else '')
        + "งานของคุณ:\n"
        "1. สังเคราะห์ข่าวทั้งหมดเป็นประเด็นหลัก 2-3 ประโยค (ไม่ใช่เล่าทีละข่าว) เชื่อมโยงข่าวรายตัว + ข่าวมหภาค + เทคนิค\n"
        "2. จัดอันดับข่าวตามผลกระทบต่อราคาหุ้นตัวนี้ (ราคาย่อยหนักที่สุดมาก่อน) และระบุเพราะอะไรทีละข่าว\n"
        "3. แยกเหตุผลเป็น 3 หมวด: จากข่าว / จากงบการเงิน / จากตัวเลขสถิติ (P/E, RSI, แนวรับ-ต้าน, ช่วง 52 สัปดาห์)\n\n"
        'ตอบเป็น JSON เท่านั้น (ห้ามมีข้อความอื่น ห้าม Markdown fence):\n'
        '{"summary": "สรุปสังเคราะห์ 2-3 ประโยค อ้างเลขข่าว [1][2] ที่ใช้จริง", '
        '"impact": "Positive|Mixed|Negative", '
        '"news_flash": ["ข่าวเด่นสุดๆ บรรทัดละข่าว ไม่เกิน 90 ตัวอักษร เอาแค่ 2 ข่าวที่กระทบสุด"], '
        '"news_detail": [{"no": 1, "title": "หัวข้อข่าว", "publisher": "ชื่อสำนัก", '
        '"url": "ใช้เฉพาะ url จากรายการด้านบนเท่านั้น ห้ามแต่ง", '
        '"impact": "Positive|Mixed|Negative", "why": "กระทบราคาอย่างไรเพราะอะไร 1 ประโยค"}'
        f' (เรียงตามน้ำหนักกระทบสุด ห้ามซ้ำหมายเลข ใช้ครบทุกข่าวที่เกี่ยว)], '
        '"reasons": {"news": ["เหตุผลจากข่าว ไม่เกิน 2 ข้อ"], '
        '"financials": ["เหตุผลจากงบ/P/E/ปันผล ไม่เกิน 2 ข้อ ถ้าไม่มีข้อมูลงบให้บอกว่าไม่มีข้อมูล"], '
        '"stats": ["เหตุผลจาก RSI/แนวรับต้าน/MA/52 สัปดาห์ ไม่เกิน 2 ข้อ"]}, '
        '"advice": ["คำแนะนำปฏิบัติสั้นสุด 1 ข้อ"], '
        '"disclaimer": "ข้อมูลเพื่อประกอบการพิจารณา ไม่ใช่คำแนะนำการลงทุน"}'
    )

    try:
        raw = router.generate(prompt)
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Local models often wrap JSON in prose — grab first {...} block.
            start, end = text.find('{'), text.rfind('}')
            if start == -1 or end <= start:
                raise
            data = json.loads(text[start:end + 1])

        impact = data.get("impact", "Mixed")
        if impact not in _ALLOWED_IMPACT:
            impact = "Mixed"
        reasons = data.get("reasons") or {}
        if not isinstance(reasons, dict):
            reasons = {}
        advice = [str(a) for a in (data.get("advice") or [])][:2]
        detail = _validate_detail(data.get("news_detail"), digest)
        cited = _extract_cited(str(data.get("summary", "")))
        if not cited and detail:
            cited = [d.get('no') for d in detail[:3] if isinstance(d.get('no'), int)]
        flash = [str(f)[:90] for f in (data.get("news_flash") or [])][:2]
        if not flash:
            flash = [short_line(item) for item in digest[:2]]

        return {
            "summary": str(data.get("summary", ""))[:1200],
            "impact": impact,
            "news_flash": flash,
            "news_detail": detail,
            "reasons": {
                "news": [str(r)[:200] for r in (reasons.get("news") or [])][:2],
                "financials": [str(r)[:200] for r in (reasons.get("financials") or [])][:2],
                "stats": [str(r)[:200] for r in (reasons.get("stats") or [])][:2],
            },
            "advice": advice,
            "disclaimer": data.get(
                "disclaimer", "ข้อมูลเพื่อประกอบการพิจารณา ไม่ใช่คำแนะนำการลงทุน"
            ),
            "provider": router.last_used,
            "news_count": news_count,
            "news_cited": cited,
            # Legacy keys for older renderers (web chat / discord)
            "news": flash,
        }
    except (ProviderError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        print(f"[NewsAnalysis] AI unavailable ({exc}); using deterministic fallback.")
        fallback = _fallback_brief(snapshot, digest)
        fallback["provider"] = "fallback"
        fallback["news_count"] = news_count
        fallback["news_cited"] = []
        fallback["legacy_stats"] = stat_reasons[:2]
        return fallback
