"""Financial ratio computation + Thai explanation builder.

Every ratio carries the exact numbers it was computed from so the bot can
answer "มายังไง / คำนวณจากอะไร" instead of dumping bare figures.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _fmt_short(value: float) -> str:
    """Format large values compactly: 4,291,117M -> 4.29T / 348.5B."""
    a = abs(value)
    for div, suffix in ((1e12, 'ล้านล้าน'), (1e9, 'พันล้าน'), (1e6, 'ล้าน')):
        if a >= div:
            return f"{value / div:,.2f} {suffix}"
    return f"{value:,.2f}"


def _pct(part: float, whole: float) -> Optional[float]:
    if whole is None or whole == 0:
        return None
    try:
        return (part / whole) * 100.0
    except (TypeError, ZeroDivisionError):
        return None


def _ratio(num: float, den: float) -> Optional[float]:
    if den is None or den == 0:
        return None
    try:
        return num / den
    except (TypeError, ZeroDivisionError):
        return None


def compute_ratios(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Derive ratios from raw statement numbers (all in millions if yfinance)."""
    equity = raw.get('equity')
    liabilities = raw.get('total_liabilities')
    assets = raw.get('total_assets')
    debt = raw.get('total_debt')
    cash = raw.get('cash')
    revenue = raw.get('revenue')
    op_income = raw.get('operating_income')
    net_income = raw.get('net_income')
    eps = raw.get('eps')

    derived: Dict[str, Any] = {
        'de_ratio': _ratio(liabilities, equity) if equity else None,
        'debt_to_assets': _ratio(liabilities, assets),
        'current_ratio': raw.get('current_ratio'),
        'roe': _pct(net_income, equity),
        'net_margin': _pct(net_income, revenue),
        'op_margin': _pct(op_income, revenue),
        'roa': _pct(net_income, assets),
    }
    if assets and liabilities is not None and cash is not None:
        derived['net_cash'] = cash - debt if debt is not None else cash
    if eps is not None:
        derived['eps'] = eps
    return derived


def build_financial_reasoning(
    raw: Dict[str, Any],
    ratios: Dict[str, Any],
    price: Optional[float],
) -> List[str]:
    """Bullet list: each item = ratio + how it was computed + what it implies."""
    out: List[str] = []
    equity = raw.get('equity')
    liabilities = raw.get('total_liabilities')
    revenue = raw.get('revenue')
    net_income = raw.get('net_income')
    assets = raw.get('total_assets')
    de = ratios.get('de_ratio')

    # Debt structure
    if de is not None:
        if de < 0.5:
            verdict = 'โครงสร้างหนี้แข็งแรง (น้อยกว่าครึ่งของทุน)'
            tone = 'positive'
        elif de <= 1.5:
            verdict = 'ระดับกลาง ยังจัดการได้'
            tone = 'neutral'
        else:
            verdict = 'หนี้สูงกว่าส่วนของผู้ถือหุ้น เฝ้าระวังดอกเบี้ยและรอบธุรกิจ'
            tone = 'negative'
        out.append(
            f"{'🟢' if tone == 'positive' else '🟡' if tone == 'neutral' else '🔴'} "
            f"หนี้สิน/ทุน = {de:.2f} เท่า — คิดจาก หนี้สินรวม "
            f"{_fmt_short(liabilities)} ÷ ส่วนของผู้ถือหุ้น {_fmt_short(equity)} → {verdict}"
        )
    elif assets and liabilities is not None:
        da = ratios.get('debt_to_assets')
        if da is not None:
            out.append(
                f"หนี้สินคิดเป็น {da:.0f}% ของสินทรัพย์รวม "
                f"({_fmt_short(liabilities)} ÷ {_fmt_short(assets)})"
            )

    # Profitability
    nm = ratios.get('net_margin')
    if nm is not None and revenue:
        if nm >= 15:
            verdict = 'กำไรงามเป็นเงินสดหลังหักทุกค่าใช้จ่าย'
        elif nm >= 5:
            verdict = 'กำไรในระดับปกติของธุรกิจที่รักษาเสถียรภาพได้'
        else:
            verdict = 'อยู่แค่เฉลี่ย แข่งขันสูงหรือต้นทุนกดดัน'
        out.append(
            f"{'🟢' if nm >= 15 else '🟡' if nm >= 5 else '🔴'} "
            f"อัตรากำไรสุทธิ = {nm:.1f}% — คิดจาก กำไรสุทธิ "
            f"{_fmt_short(net_income)} ÷ รายได้รวม {_fmt_short(revenue)} → {verdict}"
        )

    roe = ratios.get('roe')
    if roe is not None and equity:
        if roe >= 15:
            verdict = 'ผลตอบแทนน่าพอใจ ผู้ถือหุ้นได้เปรียบจากงบดุลนี้'
        elif roe >= 8:
            verdict = 'ระดับที่ยอมรับได้แต่ไม่โดดเด่น'
        else:
            verdict = 'ต่ำกว่าที่ควร ทุนยังสร้างกำไรได้ไม่เต็มที่'
        out.append(
            f"{'🟢' if roe >= 15 else '🟡' if roe >= 8 else '🔴'} "
            f"ROE = {roe:.1f}% — คิดจาก กำไรสุทธิ ÷ ส่วนของผู้ถือหุ้น "
            f"({_fmt_short(net_income)} ÷ {_fmt_short(equity)}) → {verdict}"
        )

    # Valuation vs book — only meaningful with market cap (need per-share book)
    mcap = raw.get('market_cap')
    if mcap and assets and liabilities is not None:
        book = assets - liabilities
        pbr = _ratio(mcap, book) if book and book > 0 else None
        if pbr is not None:
            if pbr < 1:
                verdict = 'ราคาหุ้นต่ำกว่ามูลค่าทางบัญชี (อาจถูกกว่ามูลค่าจริง หรือสะท้อนความเสี่ยง)'
            elif pbr < 3:
                verdict = 'ราคาสอดคล้องกับมูลค่าบัญชีในระดับตลาดทั่วไป'
            else:
                verdict = 'ตลาดยอมจ่ายแพงกว่ามูลค่าบัญชีหลายเท่า เพราะคาดหวังการเติบโตสูง'
            out.append(
                f"{'🟢' if pbr < 1 else '🟡' if pbr < 3 else '🔴'} "
                f"P/B ≈ {pbr:.2f} เท่า — คิดจาก มูลค่าตลาด {_fmt_short(mcap)} ÷ มูลค่าทางบัญชี "
                f"(สินทรัพย์ {_fmt_short(assets)} − หนี้สิน {_fmt_short(liabilities)}) → {verdict}"
            )

    # EPS growth signal (single period: show absolute for context)
    eps = ratios.get('eps') or raw.get('eps')
    if eps is not None and price:
        pe_implied = _ratio(price, eps)
        if pe_implied is not None:
            out.append(
                f"EPS งบล่าสุด = {eps:,.2f} บาท/หุ้น → P/E ที่ราคาปัจจุบัน ≈ {pe_implied:.1f} เท่า "
                f"(ราคา {price:,.2f} ÷ EPS)"
            )

    if not out:
        out.append('ข้อมูลงบยังไม่ครบพอสำหรับคำนวณอัตราส่วน — ลองกด Refresh เพื่อดึงงบใหม่')
    return out
