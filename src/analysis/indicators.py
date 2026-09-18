from __future__ import annotations

import math
from typing import Any, Dict, Iterable

import pandas as pd


def calculate_indicators(prices: Iterable[float]) -> Dict[str, Any]:
    """Calculate presentation-ready technical indicators deterministically in Python.

    Returns:
        Dict with keys:
          - rsi: str ("XX.XX" or "N/A")
          - sma20: str
          - sma50: str
          - volatility: str ("X.X%" or "N/A")
          - support: str
          - resistance: str
          - year_high: str
          - year_low: str
    """
    price_list = [float(p) for p in prices if p is not None and not math.isnan(p)]
    series = pd.Series(price_list, dtype='float64').dropna()

    if series.empty:
        return {
            'rsi': 'N/A',
            'sma20': 'N/A',
            'sma50': 'N/A',
            'volatility': 'N/A',
            'support': '-',
            'resistance': '-',
            'year_high': '-',
            'year_low': '-',
        }

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

    return {
        'rsi': rsi,
        'sma20': sma20,
        'sma50': sma50,
        'volatility': volatility,
        'support': support,
        'resistance': resistance,
        'year_high': year_high,
        'year_low': year_low,
    }


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
