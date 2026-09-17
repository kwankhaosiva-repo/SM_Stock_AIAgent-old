from __future__ import annotations

from typing import Dict, Iterable, List

import pandas as pd


def calculate_indicators(prices: Iterable[float]) -> Dict[str, str]:
    """Calculate presentation-ready indicators without asking an LLM to do math."""
    series = pd.Series(list(prices), dtype='float64').dropna()
    if series.empty:
        return {'rsi': 'N/A', 'sma50': 'N/A', 'year_high': '-', 'year_low': '-'}

    sma50 = 'N/A'
    if len(series) >= 50:
        sma50 = f"{series.rolling(window=50).mean().iloc[-1]:.2f}"

    rsi = 'N/A'
    if len(series) >= 15:
        delta = series.diff()
        gains = delta.clip(lower=0).rolling(window=14).mean()
        losses = -delta.clip(upper=0).rolling(window=14).mean()
        if losses.iloc[-1] == 0:
            rsi = '100.00' if gains.iloc[-1] > 0 else '50.00'
        else:
            rsi = f"{(100 - (100 / (1 + gains.iloc[-1] / losses.iloc[-1]))):.2f}"

    return {
        'rsi': rsi,
        'sma50': sma50,
        'year_high': f"{series.max():.2f}",
        'year_low': f"{series.min():.2f}",
    }


def infer_trend(price: float, technicals: Dict[str, str]) -> str:
    """A small, explicit rule set used as evidence, never as a trade instruction."""
    sma50 = technicals.get('sma50', 'N/A')
    try:
        return 'Positive' if price >= float(sma50) else 'Cautious'
    except (TypeError, ValueError):
        return 'Neutral'
