"""Indicator presentation layer: groups technicals into short / mid / long
term sections with a traffic-light tone and a beginner explanation per line,
plus the glossary (คำอธิบายตัวแปร) used by the "📖 คำศัพท์" mode.

All interpretations are deterministic Python rules — never LLM output — so
the same numbers always produce the same tone and explanation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Traffic-light tones (same labels as reason lines: Positive / Negative / Watch).
TONES = {
    'Positive': {'emoji': '\U0001f7e2', 'label': 'Positive', 'color': '#16803C'},
    'Negative': {'emoji': '\U0001f534', 'label': 'Negative', 'color': '#B42318'},
    'Watch': {'emoji': '\U0001f7e1', 'label': 'Watch', 'color': '#8A6100'},
}


def _f(value: Any) -> Optional[float]:
    try:
        if value in (None, '', 'N/A', '-'):
            return None
        return float(str(value).replace(',', '').replace('%', ''))
    except (TypeError, ValueError):
        return None


def _tone_line(label: str, value: str, tone: str, explain: str) -> Dict[str, Any]:
    t = TONES[tone]
    return {
        'label': label,
        'value': value,
        'emoji': t['emoji'],
        'tone_label': t['label'],
        'color': t['color'],
        'explain': explain,
    }


def build_indicator_sections(technicals: Dict[str, Any], price: float = 0.0) -> List[Dict[str, Any]]:
    """Group technicals into 3 timeframe sections.

    Each section: {'title', 'lines': [{'label','value','emoji','tone_label','color','explain'}]}
    Lines with N/A data are skipped entirely (no noise for the reader).
    """
    tech = technicals or {}
    price = float(price or 0.0)

    short_lines: List[Dict[str, Any]] = []
    mid_lines: List[Dict[str, Any]] = []
    long_lines: List[Dict[str, Any]] = []

    # ---------------- Short term (days-weeks): RSI, MACD, momentum ----------------
    rsi = _f(tech.get('rsi'))
    if rsi is not None:
        if rsi >= 70:
            short_lines.append(_tone_line(
                'RSI(14)', f'{rsi:.1f}', 'Watch',
                'RSI วัดแรงซื้อ-แรงขาย 14 วันล่าสุด ถ้าเกิน 70 แปลว่าคนซื้อมากไปแล้ว มักมีการขายทำกำไรลงมาสักระยะ',
            ))
        elif rsi <= 30:
            short_lines.append(_tone_line(
                'RSI(14)', f'{rsi:.1f}', 'Watch',
                'RSI ต่ำกว่า 30 แปลว่าคนขายมากเกินไป มักเป็นช่วงที่ราคาเริ่มเด้งกลับได้',
            ))
        else:
            short_lines.append(_tone_line(
                'RSI(14)', f'{rsi:.1f}', 'Positive',
                'RSI อยู่กลางโซน (30-70) แปลว่าแรงซื้อแรงขายสมดุล ยังไม่มีสัญญาณร้อนหรือเย็นเกินไป',
            ))

    macd_hist = _f(tech.get('macd_hist'))
    if macd_hist is not None:
        if macd_hist > 0:
            short_lines.append(_tone_line(
                'MACD', f'{macd_hist:+.3f}', 'Positive',
                'MACD เทียบค่าเฉลี่ยราคา 12 กับ 26 วัน ถ้าค่าบวกแปลว่าแรงซื้อระยะสั้นยังนำอยู่ ราคาไหลขึ้นต่อได้',
            ))
        else:
            short_lines.append(_tone_line(
                'MACD', f'{macd_hist:+.3f}', 'Negative',
                'MACD ติดลบแปลว่าค่าเฉลี่ยสั้นอยู่ต่ำกว่าค่าเฉลี่ยยาว โมเมนตัมระยะสั้นเริ่มอ่อน ราคาอาจย่อลง',
            ))

    mom5 = _f(tech.get('momentum5'))
    if mom5 is not None:
        if mom5 >= 1:
            short_lines.append(_tone_line(
                'โมเมนตัม 5 วัน', f'{mom5:+.1f}%', 'Positive',
                'ราคา 5 วันล่าสุดเพิ่มขึ้นเกิน 1% — แรงซื้อสั้น ๆ ยังเหนียว แต่ตัวเลขแค่ 5 วันเปลี่ยนแปลงเร็ว อย่าเพิ่งไว้ใจคนเดียว',
            ))
        elif mom5 <= -1:
            short_lines.append(_tone_line(
                'โมเมนตัม 5 วัน', f'{mom5:+.1f}%', 'Negative',
                'ราคา 5 วันล่าสุดลดลงเกิน 1% — แรงขายสั้น ๆ กำลังกด ถ้ายังไม่มีข่าวดีมักไหลลงต่อได้',
            ))
        else:
            short_lines.append(_tone_line(
                'โมเมนตัม 5 วัน', f'{mom5:+.1f}%', 'Watch',
                'ราคา 5 วันเปลี่ยนแปลงน้อยมาก (±1%) — ยังไม่มีทิศทางชัด รอสัญญาณเพิ่ม',
            ))

    consol = _f(tech.get('consolidation'))
    if consol is not None:
        if consol < 4:
            short_lines.append(_tone_line(
                'พักฐาน (ช่วง 10 วัน)', f'{consol:.1f}%', 'Watch',
                'ราคาแกว่งแคบกว่า 4% ใน 10 วัน = กำลังพักฐาน รอเลือกทาง หุ้นจะวิ่งแรงหลังออกจากช่วงนี้',
            ))
        else:
            short_lines.append(_tone_line(
                'พักฐาน (ช่วง 10 วัน)', f'{consol:.1f}%', 'Positive',
                'ราคาแกว่งกว้างกว่า 4% ใน 10 วัน = มีการเคลื่อนไหวชัดเจน ไม่ใช่ช่วงนิ่งรอ',
            ))

    # ---------------- Mid term (weeks-months): avg5, Bollinger, EMA20/50 ----------------
    avg5 = _f(tech.get('avg5'))
    if avg5 is not None:
        if price > 0:
            diff = (price / avg5 - 1) * 100
            if diff >= 1:
                tone = 'Positive'
                why = 'ราคาล่าสุดอยู่เหนือค่าเฉลี่ย 5 วัน เท่ากับว่าคนยอมจ่ายแพงกว่าค่าเฉลี่ยใกล้ ๆ แรงซื้อยังนำ'
            elif diff <= -1:
                tone = 'Negative'
                why = 'ราคาล่าสุดอยู่ต่ำกว่าค่าเฉลี่ย 5 วัน เท่ากับว่าคนขายเร่งขายต่ำกว่าค่าเฉลี่ยใกล้ ๆ แรงขายกำลังนำ'
            else:
                tone = 'Watch'
                why = 'ราคาล่าสุดอยู่ใกล้ค่าเฉลี่ย 5 วัน ยังไม่มีฝ่ายไหนนำชัด'
            mid_lines.append(_tone_line('ราคาเฉลี่ย 5 วัน', f'{avg5:,.2f}', tone, why))
        else:
            mid_lines.append(_tone_line(
                'ราคาเฉลี่ย 5 วัน', f'{avg5:,.2f}', 'Watch',
                'ค่าเฉลี่ยราคา 5 วันล่าสุด เทียบกับราคาปัจจุบันว่าอยู่เหนือหรือต่ำกว่า เพื่อดูแรงซื้อสั้น ๆ',
            ))

    boll_l = _f(tech.get('boll_lower'))
    boll_u = _f(tech.get('boll_upper'))
    if boll_l is not None and boll_u is not None:
        if price > 0 and price < boll_l:
            tone = 'Negative'
            why = 'ราคาหลุดกรอบล่าง Bollinger = ขายแรงผิดปกติเทียบค่าเฉลี่ย 20 วัน มักลงต่อหรือเด้งแรงก็จริงต้องรอดู'
        elif price > 0 and price > boll_u:
            tone = 'Positive'
            why = 'ราคาทะลุกรอบบน Bollinger = ซื้อแรงผิดปกติเทียบค่าเฉลี่ย 20 วัน ขึ้นเร็วแต่มักย่อลงมาพักก่อน'
        else:
            tone = 'Watch'
            why = 'กรอบ Bollinger คือค่าเฉลี่ย 20 วัน บวกลบ 2 ส่วนเบี่ยงเบน ราคาอยู่ในกรอบแปลว่าปกติ ยังไม่ร้อนหรือเย็นเกินไป'
        mid_lines.append(_tone_line('Bollinger (20)', f'{boll_l:,.2f} – {boll_u:,.2f}', tone, why))

    ema20 = _f(tech.get('ema20'))
    ema50 = _f(tech.get('ema50'))
    if ema20 is not None and ema50 is not None:
        if ema20 > ema50:
            mid_lines.append(_tone_line(
                'EMA 20/50 ระยะกลาง', f'{ema20:,.2f} / {ema50:,.2f}', 'Positive',
                'EMA ถ่วงน้ำหนักราคาใหม่กว่าเก่า EMA20 อยู่เหนือ EMA50 แปลว่าแนวโน้มระยะกลางเป็นขาขึ้น',
            ))
        else:
            mid_lines.append(_tone_line(
                'EMA 20/50 ระยะกลาง', f'{ema20:,.2f} / {ema50:,.2f}', 'Negative',
                'EMA20 อยู่ต่ำกว่า EMA50 แปลว่าราคาล่าสุดอ่อนกว่าค่าเฉลี่ยกลาง แนวโน้มระยะกลางเริ่มเป็นขาลง',
            ))
    elif ema20 is not None or ema50 is not None:
        val = ema20 if ema20 is not None else ema50
        mid_lines.append(_tone_line(
            'EMA ระยะกลาง', f'{val:,.2f}', 'Watch',
            'EMA คือค่าเฉลี่ยที่ถ่วงน้ำหนักราคาล่าสุดมากกว่าเก่า ขยับตามราคาไวกว่าค่าเฉลี่ยธรรมดา (SMA)',
        ))

    support = tech.get('support')
    resistance = tech.get('resistance')
    if support not in (None, '-', 'N/A') and resistance not in (None, '-', 'N/A'):
        mid_lines.append(_tone_line(
            'แนวรับ / แนวต้าน',
            f'{support} / {resistance}',
            'Watch',
            'จุดต่ำสุด-สูงสุดราคาย้อนหลัง 30 วัน แนวรับคือแถวที่คนเคยซื้อรับ แนวต้านคือแถวที่คนเคยขายกด',
        ))

    # ---------------- Long term (months): EMA50/200, OBV, 52-week range ----------------
    ema200 = _f(tech.get('ema200'))
    ema50v = _f(tech.get('ema50'))
    if ema200 is not None and ema50v is not None:
        if ema50v > ema200:
            long_lines.append(_tone_line(
                'EMA 50/200 ระยะยาว', f'{ema50v:,.2f} / {ema200:,.2f}', 'Positive',
                'EMA50 อยู่เหนือ EMA200 (โกลเดนครอส) = แนวโน้มระยะยาวเป็นขาขึ้น สัญญาณที่นักลงทุนระยะยาวใช้ดูทิศทางหลัก',
            ))
        else:
            long_lines.append(_tone_line(
                'EMA 50/200 ระยะยาว', f'{ema50v:,.2f} / {ema200:,.2f}', 'Negative',
                'EMA50 อยู่ต่ำกว่า EMA200 (เดทครอส) = แนวโน้มระยะยาวเป็นขาลง ภาพยังอ่อน ต้องรอสัญญาณกลับตัว',
            ))
    elif ema200 is None and ema50v is not None:
        long_lines.append(_tone_line(
            'EMA 50 ระยะยาว', f'{ema50v:,.2f}', 'Watch',
            'EMA200 ยังคำนวณไม่ได้เพราะต้องใช้ราคาอย่างน้อย 200 วันทำการ — เมื่อข้อมูลครบจะเทียบ EMA50/200 ให้ทันที',
        ))

    obv = str(tech.get('obv_trend') or 'N/A')
    if obv == 'rising':
        long_lines.append(_tone_line(
            'OBV ล่าสุด', 'เพิ่มขึ้น', 'Positive',
            'OBV รวมปริมาณซื้อขายตามทิศทางราคา ถ้าขึ้นแปลว่าวันที่ราคาขึ้นมีคนซื้อเยอะกว่า วันที่ราคาลง = เงินไหลเข้าจริง',
        ))
    elif obv == 'falling':
        long_lines.append(_tone_line(
            'OBV ล่าสุด', 'ลดลง', 'Negative',
            'OBV ลดลงแปลว่าวันที่ราคามีคนขายมากกว่าซื้อ = เริ่มมีแรงขายเทออก ราคาขึ้นอาจไม่มีน้ำหนัก',
        ))
    elif obv == 'flat':
        long_lines.append(_tone_line(
            'OBV ล่าสุด', 'ทรงตัว', 'Watch',
            'OBV ไม่เปลี่ยนแปลง = แรงซื้อขายสมดุล ยังไม่มีเงินไหลเข้าหรือออกชัดเจน',
        ))

    yh = _f(tech.get('year_high'))
    yl = _f(tech.get('year_low'))
    if yh is not None and yl is not None and yh > yl and price > 0:
        pos = (price - yl) / (yh - yl) * 100
        if pos >= 80:
            tone = 'Watch'
            why = 'ราคาอยู่โซนบนของช่วง 52 สัปดาห์ ใกล้จุดสูงสุดปี — อาจเหนื่อยกับแรงขายทำกำไรที่แนวต้าน'
        elif pos <= 20:
            tone = 'Negative'
            why = 'ราคาอยู่โซนล่างของช่วง 52 สัปดาห์ ใกล้จุดต่ำสุดปี — ยังอ่อน ต้องรอดูสัญญาณกลับตัว'
        else:
            tone = 'Positive'
            why = 'ราคาอยู่กลางช่วง 52 สัปดาห์ ยังมีพื้นที่วิ่งทั้งขึ้นและลง ไม่ได้ติดบนหรือจมก้นจนเกินไป'
        long_lines.append(_tone_line(
            'ช่วง 52 สัปดาห์', f'{yl:,.2f} – {yh:,.2f} ({pos:.0f}%)', tone, why,
        ))

    vol = tech.get('volatility')
    vol_f = _f(vol)
    if vol_f is not None:
        if vol_f >= 40:
            tone = 'Negative'
            why = 'ความผันผวนต่อปีเกิน 40% = ราคาแกว่งแรงมาก ผลตอบแทนคาดยาก เหมาะกับคนรับความเสี่ยงได้สูง'
        elif vol_f >= 20:
            tone = 'Watch'
            why = 'ความผันผวน 20-40% ต่อปี = แกว่งปานกลางตามตลาดปกติ ยังพอประเมินกรอบราคาได้'
        else:
            tone = 'Positive'
            why = 'ความผันผวนต่ำกว่า 20% ต่อปี = ราคานิ่ง แกว่งน้อย เหมาะกับเน้นถือนาน แต่กำไรวิ่งช้า'
        long_lines.append(_tone_line('ความผันผวน (ต่อปี)', str(vol), tone, why))

    sections = []
    if short_lines:
        sections.append({'title': '⏱ ระยะสั้น (วัน-สัปดาห์)', 'lines': short_lines})
    if mid_lines:
        sections.append({'title': '📅 ระยะกลาง (สัปดาห์-เดือน)', 'lines': mid_lines})
    if long_lines:
        sections.append({'title': '📆 ระยะยาว (เดือนขึ้นไป)', 'lines': long_lines})
    return sections


# ---------------------------------------------------------------------------
# Glossary (โหมดคำอธิบายตัวแปร สำหรับมือใหม่)
# ---------------------------------------------------------------------------
# term -> (what it is, how to read it, why it matters)
GLOSSARY: List[Dict[str, str]] = [
    {
        'term': 'RSI (Relative Strength Index)',
        'what': 'ตัวเลข 0-100 วัดว่าช่วง 14 วันล่าสุดคนซื้อกับคนขาย ฝั่งไหนแรงกว่า',
        'how': 'เกิน 70 = ซื้อมากเกินไป (overbought), ต่ำกว่า 30 = ขายมากเกินไป (oversold), กลาง ๆ คือสมดุล',
        'why': 'บอกจังหวะที่มักจะย่อลง (ตอนร้อนเกิน) หรือเด้งกลับ (ตอนเย็นเกิน) — ใช้ประกอบไม่ใช่ตัวเดียว',
    },
    {
        'term': 'MACD',
        'what': 'เทียบค่าเฉลี่ยราคาสั้น 12 วัน กับยาว 26 วัน แล้วดูความต่าง (histogram)',
        'how': 'ค่าบวก = โมเมนตัมเป็นขาขึ้น, ค่าลบ = โมเมนตัมเป็นขาลง',
        'why': 'บอกแรงเร่งของราคา ถ้าราคาขึ้นแต่ MACD ลบ เรียกว่า divergence มักเตือนว่าขาขึ้นกำลังอ่อนแรง',
    },
    {
        'term': 'EMA (Exponential Moving Average)',
        'what': 'ค่าเฉลี่ยราคาที่ถ่วงน้ำหนักราคาล่าสุดมากกว่าราคาเก่า จึงขยับตามราคาไวกว่า SMA',
        'how': 'EMA อยู่เหนือเส้นที่ยาวกว่า = ขาขึ้น (เช่น EMA20 > EMA50), อยู่ต่ำกว่า = ขาลง',
        'why': 'จับทิศทางได้ไวกว่าค่าเฉลี่ยธรรมดา เส้นสั้นตัดเส้นยาว (cross) ใช้เป็นสัญญาณเข้า-ออกตามแนวโน้ม',
    },
    {
        'term': 'Golden Cross / Death Cross',
        'what': 'EMA50 ตัดขึ้นเหนือ EMA200 = โกลเดนครอส, ตัดลง = เดทครอส',
        'how': 'Golden = สัญญาณขาขึ้นระยะยาว, Death = สัญญาณขาลงระยะยาว',
        'why': 'EMA200 ใช้เวลา 200 วันทำการ จึงเป็นเส้นแบ่ง "แนวโน้มหลัก" ของหุ้น — นักลงทุนระยะยาวใช้ตัวนี้เยอะ',
    },
    {
        'term': 'Bollinger Band (20)',
        'what': 'กรอบราคารอบค่าเฉลี่ย 20 วัน บวกลบ 2 ส่วนเบี่ยงเบนมาตรฐาน',
        'how': 'แตะกรอบล่าง = ขายแรงผิดปกติ, แตะกรอบบน = ซื้อแรงผิดปกติ, อยู่กลางกรอบ = ปกติ',
        'why': 'กรอบจะแคบเมื่อหุ้นนิ่ง (บีบตัว) แล้วมักวิ่งแรงหลังจากนั้น — หลายคนใช้รอจังหวะราคาออกจากกรอบ',
    },
    {
        'term': 'OBV (On-Balance Volume)',
        'what': 'รวมปริมาณซื้อขายโดยบวกเมื่อราคาปิดสูง ลบเมื่อราคาปิดต่ำ',
        'how': 'OBV ขึ้น = เงินไหลเข้า, OBV ลง = เริ่มมีคนขายเท',
        'why': 'ราคายังไม่ขึ้นแต่ OBV ขึ้นก่อน มักเป็นสัญญาณว่ามีคนแอบสะสม — ปริมาณมาก่อนราคาเสมอ',
    },
    {
        'term': 'แนวรับ / แนวต้าน',
        'what': 'แนวรับ = ราคาที่คนเคยซื้อรับจนราคาไม่ลงต่อ, แนวต้าน = ราคาที่คนเคยขายกดจนราคาไม่ขึ้นต่อ',
        'how': 'ดูจากจุดสูงสุด/ต่ำสุดย้อนหลัง 30 วันทำการ',
        'why': 'ราคาใกล้แนวรับมักเด้ง ใกล้แนวต้านมักย่อ — ใช้วางแผนว่าจะดูราคาแถวไหนก่อนตัดสินใจ',
    },
    {
        'term': 'ความผันผวน (Volatility)',
        'what': 'ค่าส่วนเบี่ยงเบนของผลตอบแทนรายวันย้อนหลัง 30 วัน คูณ √252 แล้วแสดงเป็น % ต่อปี',
        'how': 'ต่ำกว่า 20% = นิ่ง, 20-40% = ปกติ, เกิน 40% = แกว่งแรง',
        'why': 'บอกความเสี่ยงของหุ้นตัวนั้น ไม่ได้บอกทิศทาง แต่บอกว่าต้องเจอกับการแกว่งรุนแรงแค่ไหน',
    },
    {
        'term': 'โมเมนตัม 5 วัน',
        'what': 'การเปลี่ยนแปลงของราคาเทียบกับ 5 วันทำการก่อนหน้า',
        'how': 'บวกเกิน 1% = แรงซื้อสั้นนำ, ลบเกิน 1% = แรงขายสั้นนำ',
        'why': 'จับอารมณ์ระยะสั้นแบบเร็วที่สุด แต่แกว่งง่าย — ควรคู่กับ EMA/MACD ที่นิ่งกว่า',
    },
    {
        'term': 'การพักฐาน (Consolidation)',
        'what': 'ช่วงที่ราคาแกว่งในกรอบแคบ ๆ โดยไม่มีทิศทางชัด (เราคำนวณจากช่วงแกว่ง 10 วัน)',
        'how': 'ช่วงแกว่งแคบกว่า 4% = กำลังพักฐาน, กว้างกว่า = มีการเคลื่อนไหวชัด',
        'why': 'หุ้นมักวิ่งแรงหลังพักฐานเสร็จ ทิศทางที่ทะลุกรอบมักเป็นทิศทางจริง — เลือกว่าจะรอหรือเข้าก่อน',
    },
    {
        'term': 'ช่วง 52 สัปดาห์',
        'what': 'ราคาสูงสุดและต่ำสุดของหุ้นในรอบ 1 ปีที่ผ่านมา',
        'how': '% บอกว่าราคาตอนนี้อยู่ตรงไหนของช่วงนั้น (0% = ต่ำสุดปี, 100% = สูงสุดปี)',
        'why': 'ช่วยประเมินว่าราคาตอนนี้ "แพง" หรือ "ถูก" เทียบกับตัวมันเองในปีที่ผ่านมา',
    },
    {
        'term': 'SMA (Simple Moving Average)',
        'what': 'ค่าเฉลี่ยราคาธรรมดาแบบถ่วงน้ำหนักเท่ากันทุกวัน (ต่างจาก EMA ที่ให้น้ำหนักวันล่าสุดมากกว่า)',
        'how': 'ราคาอยู่เหนือ SMA = แนวโน้มขึ้น, ต่ำกว่า = แนวโน้มลง (นิยมดู SMA20 กับ SMA50)',
        'why': 'เส้นนิ่งกว่า EMA ใช้ยืนยันแนวโน้มใหญ่ได้ดี แต่สัญญาณช้ากว่า',
    },
]
