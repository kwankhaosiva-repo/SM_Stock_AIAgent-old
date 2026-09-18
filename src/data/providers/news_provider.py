from __future__ import annotations

from typing import List

from models.analysis_models import SourceItem

from .base import NewsDataProvider


class NewsProvider(NewsDataProvider):
    """Fetches company-specific and global macro news with provenance."""

    name: str = 'news_provider'

    def fetch_news(self, symbol: str) -> List[SourceItem]:
        sources: List[SourceItem] = []
        clean_symbol = symbol.upper().strip()

        try:
            from global_stock_helper import get_market_news, get_general_market_news

            # 1. Company Specific News
            specific = get_market_news(clean_symbol) or []
            for item in specific[:5]:
                headline = item.get('headline') or item.get('title') or ''
                if headline:
                    sources.append(
                        SourceItem(
                            title=headline,
                            url=item.get('url') or '',
                            published_at=str(item.get('datetime') or item.get('published_at') or ''),
                            source_type='company_news',
                            relevance='high',
                        )
                    )

            # 2. Macro Market News
            macro = get_general_market_news() or []
            for item in macro[:3]:
                headline = item.get('headline') or item.get('title') or ''
                if headline:
                    sources.append(
                        SourceItem(
                            title=f"[MACRO] {headline}",
                            url=item.get('url') or '',
                            published_at=str(item.get('datetime') or item.get('published_at') or ''),
                            source_type='macro_news',
                            relevance='medium',
                        )
                    )
        except Exception as exc:
            print(f"[NewsProvider] Error fetching news for {clean_symbol}: {exc}")

        return sources
