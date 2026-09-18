from __future__ import annotations

import json
import urllib.parse
from typing import List, Optional


class ChartService:
    """Deterministic chart generator producing URLs compatible with LINE Flex messages."""

    QUICKCHART_BASE_URL = "https://quickchart.io/chart"

    @classmethod
    def generate_sparkline_url(
        cls,
        prices: List[float],
        trend: str = 'Neutral',
        width: int = 300,
        height: int = 140,
        days: int = 30,
    ) -> str:
        """Generate a QuickChart image URL for the most recent historical daily closes."""
        if not prices or len(prices) < 2:
            return ""

        data_points = [round(float(p), 2) for p in prices[-days:] if p is not None]
        if len(data_points) < 2:
            return ""

        color_map = {
            'Positive': '#16803c',
            'Neutral': '#8854d0',
            'Cautious': '#b42318',
        }
        line_color = color_map.get(trend, '#8854d0')

        chart_config = {
            "type": "line",
            "data": {
                "labels": [""] * len(data_points),
                "datasets": [
                    {
                        "data": data_points,
                        "borderColor": line_color,
                        "borderWidth": 2.5,
                        "fill": True,
                        "backgroundColor": "rgba(136, 84, 208, 0.08)"
                        if trend == 'Neutral'
                        else ("rgba(22, 128, 60, 0.08)" if trend == 'Positive' else "rgba(180, 35, 24, 0.08)"),
                        "pointRadius": 0,
                        "tension": 0.2,
                    }
                ],
            },
            "options": {
                "legend": {"display": False},
                "layout": {
                    "padding": {"top": 8, "bottom": 8, "left": 6, "right": 6}
                },
                "scales": {
                    "xAxes": [{"display": False, "gridLines": {"display": False}}],
                    "yAxes": [{"display": False, "gridLines": {"display": False}}],
                },
            },
        }

        try:
            chart_json = json.dumps(chart_config)
            encoded = urllib.parse.quote(chart_json)
            return f"{cls.QUICKCHART_BASE_URL}?c={encoded}&w={width}&h={height}&bkg=transparent"
        except Exception as exc:
            print(f"[ChartService] Error encoding chart config: {exc}")
            return ""
