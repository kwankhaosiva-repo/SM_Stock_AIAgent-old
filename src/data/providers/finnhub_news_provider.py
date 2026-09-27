"""Finnhub company-news provider (official company feed, US-listed only).

Finnhub's free tier covers US equities only — Thai (.BK) symbols are skipped
via ProviderSkip so the chain falls through to Google News RSS. Skips equally
gracefully when FINNHUB_API_KEY is absent.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import requests

from config import Config
from models.analysis_models import SourceItem

from .base import NewsDataProvider, ProviderSkip

_BASE = 'https://finnhub.io/api/v1'


class FinnhubNewsProvider(NewsDataProvider):
    name: str = 'finnhub_news'

    def fetch_news(self, symbol: str) -> List[SourceItem]:
        clean = symbol.upper().strip()
        if clean.endswith('.BK'):
            raise ProviderSkip('finnhub free tier: Thai equities not covered')
        if not Config.FINNHUB_API_KEY:
            raise ProviderSkip('FINNHUB_API_KEY not set')

        end = datetime.utcnow()
        start = end - timedelta(days=7)
        try:
            resp = requests.get(
                f'{_BASE}/company-news',
                params={
                    'symbol': clean,
                    'from': start.strftime('%Y-%m-%d'),
                    'to': end.strftime('%Y-%m-%d'),
                    'token': Config.FINNHUB_API_KEY,
                },
                timeout=10,
            )
            if resp.status_code == 401 or resp.status_code == 403:
                raise ProviderSkip(f'finnhub auth rejected ({resp.status_code})')
            if resp.status_code == 429:
                raise ProviderSkip('finnhub rate limited (429)')
            resp.raise_for_status()
            items: List[Dict[str, Any]] = resp.json() or []
        except ProviderSkip:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise ProviderSkip(f'finnhub error: {exc}')

        sources: List[SourceItem] = []
        for item in items[:8]:
            headline = (item.get('headline') or '').strip()
            if not headline:
                continue
            ts = item.get('datetime')
            published = (
                datetime.utcfromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M')
                if ts else ''
            )
            sources.append(SourceItem(
                title=headline,
                url=item.get('url') or '',
                published_at=published,
                source_type='company_news',
                relevance='high',
            ))
        if not sources:
            raise ProviderSkip('finnhub: no company news this week')
        return sources
