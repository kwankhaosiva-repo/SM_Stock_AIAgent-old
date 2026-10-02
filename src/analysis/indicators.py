from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


def _empty_indicators() -> Dict[str, Any]:
    """Full key set with neutral values — returned when there is no data."""
    return {
        'rsi': 'N/A',
        'sma20': 'N/A',
        'sma50': 'N/A',
        'volatility': 'N/A',
        'support': '-',
        'resistance': '-',
        'year_high': '-',
        'year_low': '-',
        'ema20': 'N/A',
        'ema50': 'N/A',
        'ema200': 'N/A',
        'boll_lower': 'N/A',
        'boll_upper': 'N/A',
        'macd': 'N/A',
        'macd_signal': 'N/A',
        'macd_hist': 'N/A',
        'avg5': 'N/A',
        'momentum5': 'N/A',
        'consolidation': 'N/A',
        'obv_trend': 'N/A',
    }


def _align_prices_volumes(
    prices: Iterable[float],
    volumes: Optional[Iterable[float]],
) -> tuple[List[float], Optional[List[float]]]:
    """Filter NaN prices; keep volumes aligned when supplied at matching length."""
    raw_prices = list(prices)
    raw_volumes = list(volumes) if volumes is not None else None
    aligned = raw_volumes is not None and len(raw_volumes) == len(raw_prices)

    price_list: List[float] = []
    volume_list: List[float] = []
    for i, p in enumerate(raw_prices):
        try:
            pf = float(p)
        except (TypeError, ValueError):
            continue
        if math.isnan(pf):
            continue
        price_list.append(pf)
        if aligned:
            try:
                volume_list.append(float(raw_volumes[i]))  # type: ignore[index]
            except (TypeError, ValueError):
                volume_list.append(0.0)
    return price_list, (volume_list if aligned else None)


def calculate_indicators(
    prices: Iterable[float],
    volumes: Optional[Iterable[float]] = None,
) -> Dict[str, Any]:
    """Calculate presentation-ready technical indicators deterministically in Python.

    Returns, in addition to the classic keys (rsi, sma20, sma50, volatility,
    support, resistance, year_high, year_low):
          - ema20 / ema50 / ema200: str  (exponential moving averages)
          - boll_lower / boll_upper: str (Bollinger Band 20 periods, +/-2 sigma)
          - macd / macd_signal / macd_hist: str (12/26/9 MACD line, signal, histogram)
          - avg5: str            (5-day average price)
          - momentum5: str       (5-day price change, "+X.X%"/"-X.X%")
          - consolidation: str   (10-day range as % of mean — how sideways it is)
          - obv_trend: str       ("rising"/"falling"/"flat", needs `volumes`)

    All values are presentation-ready strings; 'N/A'/'-' when not computable.
    """
    price_list, volume_list = _align_prices_volumes(prices, volumes)
    series = pd.Series(price_list, dtype='float64').dropna()

    if series.empty:
        return _empty_indicators()

    out = _empty_indicators()

    # SMA 20
    sma20 = 'N/A'
    if len(series) >= 20:
        sma20 = f"{series.rolling(window=20).mean().iloc[-1]:.2f}"
    elif len(series) >= 5:
        sma20 = f"{series.mean():.2f}"

    # SMA 50
    sma50 = 'N/A'
    if len(series) >= 50:
        sma50 = f"{series.rolling(window=50).mean().iloc[-1]:.2f}"

    # RSI 14
    rsi = 'N/A'
    if len(series) >= 15:
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(window=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14).mean()
        last_loss = loss.iloc[-1]
        last_gain = gain.iloc[-1]

        if pd.isna(last_gain) or pd.isna(last_loss):
            rsi = 'N/A'
        elif last_loss == 0:
            rsi = '100.00' if last_gain > 0 else '50.00'
        else:
            rs = last_gain / last_loss
            rsi_val = 100 - (100 / (1 + rs))
            rsi = f"{rsi_val:.2f}"

    # Volatility (Annualized 30-day standard deviation of log returns)
    volatility = 'N/A'
    if len(series) >= 10:
        pct_changes = series.pct_change().dropna()
        if not pct_changes.empty:
            daily_std = pct_changes.tail(30).std()
            if not pd.isna(daily_std):
                annual_vol = daily_std * math.sqrt(252) * 100
                volatility = f"{annual_vol:.1f}%"

    # Support & Resistance (recent 20-30 periods swing min/max)
    window = min(len(series), 30)
    recent = series.tail(window)
    support = f"{recent.min():.2f}"
    resistance = f"{recent.max():.2f}"

    # Year high & low
    year_high = f"{series.max():.2f}"
    year_low = f"{series.min():.2f}"

    out.update({
        'rsi': rsi,
        'sma20': sma20,
        'sma50': sma50,
        'volatility': volatility,
        'support': support,
        'resistance': resistance,
        'year_high': year_high,
        'year_low': year_low,
    })

    # --- EMA 20 / 50 / 200 (span = period; needs at least `period` bars) ---
    def _ema(n: int) -> str:
        if len(series) >= n:
            return f"{series.ewm(span=n, adjust=False).mean().iloc[-1]:.2f}"
        return 'N/A'

    out['ema20'] = _ema(20)
    out['ema50'] = _ema(50)
    out['ema200'] = _ema(200)

    # --- Bollinger Bands (20 periods, +/- 2 standard deviations) ---
    if len(series) >= 20:
        window20 = series.tail(20)
        basis = window20.mean()
        sd = window20.std(ddof=0)
        out['boll_lower'] = f"{basis - 2 * sd:.2f}"
        out['boll_upper'] = f"{basis + 2 * sd:.2f}"

    # --- MACD (12/26/9): line, signal, histogram ---
    if len(series) >= 35:
        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        out['macd'] = f"{macd_line.iloc[-1]:.3f}"
        out['macd_signal'] = f"{signal_line.iloc[-1]:.3f}"
        out['macd_hist'] = f"{(macd_line - signal_line).iloc[-1]:.3f}"

    # --- 5-day average price + 5-day momentum ---
    if len(series) >= 5:
        out['avg5'] = f"{series.tail(5).mean():.2f}"
    if len(series) >= 6:
        change5 = (series.iloc[-1] / series.iloc[-6] - 1) * 100
        out['momentum5'] = f"{change5:+.1f}%"

    # --- Consolidation: 10-day range as % of the 10-day mean (how sideways) ---
    if len(series) >= 10:
        w10 = series.tail(10)
        mean10 = w10.mean()
        if mean10:
            out['consolidation'] = f"{(w10.max() - w10.min()) / mean10 * 100:.1f}%"

    # --- OBV trend (needs aligned daily volumes) ---
    if volume_list and len(volume_list) == len(price_list) and len(price_list) >= 3:
        vol_series = pd.Series(volume_list, dtype='float64')
        direction = series.diff().fillna(0).apply(lambda d: 1.0 if d > 0 else (-1.0 if d < 0 else 0.0))
        obv = (direction * vol_series).cumsum()
        lookback = min(20, len(obv) - 1)
        delta = obv.iloc[-1] - obv.iloc[-1 - lookback]
        if delta > 0:
            out['obv_trend'] = 'rising'
        elif delta < 0:
            out['obv_trend'] = 'falling'
        else:
            out['obv_trend'] = 'flat'

    return out


def infer_trend(price: float, technicals: Dict[str, Any]) -> str:
    """Explicit, rule-based trend classification used strictly as evidence, never trade advice."""
    sma50 = technicals.get('sma50')
    sma20 = technicals.get('sma20')

    # Try SMA50 first, then SMA20
    benchmark = None
    for candidate in (sma50, sma20):
        if candidate not in (None, 'N/A', '-', ''):
            try:
                benchmark = float(candidate)
                break
            except (ValueError, TypeError):
                pass

    if benchmark is None or price <= 0:
        return 'Neutral'

    if price >= benchmark * 1.01:
        return 'Positive'
    elif price <= benchmark * 0.99:
        return 'Cautious'
    return 'Neutral'
