"""Balance sheet / income statement service.

Primary source: yfinance (ticker.balance_sheet / quarterly_financials) —
verified to cover Thai (.BK) symbols. Cached 24h in the financial_statement_cache
table since statements change quarterly, not daily.
Fallback: Financial Modeling Prep REST API (free tier) when Yahoo blocks
datacenter IPs (429) or returns nothing.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests

from config import Config
import store

# Row keys we expose, in display order, with Thai labels.
_BALANCE_ROWS = [
    ('Total Assets', 'สินทรัพย์รวม'),
    ('Total Liabilities Net Minority Interest', 'หนี้สินรวม'),
    ('Stockholders Equity', 'ส่วนของผู้ถือหุ้น'),
    ('Cash And Cash Equivalents', 'เงินสดและรายการเทียบเท่า'),
    ('Total Debt', 'หนี้สินระยะยาว+ระยะสั้น'),
    ('Retained Earnings', 'กำไรสะสม'),
]
_INCOME_ROWS = [
    ('Total Revenue', 'รายได้รวม'),
    ('Operating Income', 'กำไรจากการดำเนินงาน'),
    ('Net Income', 'กำไรสุทธิ'),
    ('Basic EPS', 'กำไรต่อหุ้น (EPS)'),
]


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fmt_baht(value: Any) -> str:
    try:
        v = float(value)
        if abs(v) >= 1e9:
            return f'{v / 1e9:,.2f} พันล้าน'
        if abs(v) >= 1e6:
            return f'{v / 1e6:,.2f} ล้าน'
        return f'{v:,.0f}'
    except (TypeError, ValueError):
        return '-'


class FinancialsService:
    CACHE_HOURS = 24

    # ------------------------------------------------------------- public

    def get_financials(self, symbol: str) -> Dict[str, Any]:
        """Return {'balance_sheet': [(label_th, value_str), ...],
        'income': [...], 'periods': [...], 'source': str} or raises."""
        clean = symbol.upper().strip()
        cached = store.get_financial_cache(clean, self.CACHE_HOURS)
        if cached:
            data = dict(cached['data'])
            data['source'] = cached['source']
            data['cached'] = True
            return data

        data, source = self._fetch_yahoo(clean)
        if data is None:
            data, source = self._fetch_fmp(clean)
        if data is None:
            raise ValueError(f'No financial statements available for {clean}')

        data.setdefault('cached', False)
        store.save_financial_cache(clean, data, source)
        return data

    # -------------------------------------------------------------- cache

    # ----------------------------------------------------------- providers

    def _fetch_yahoo(self, symbol: str) -> tuple[Optional[Dict[str, Any]], str]:
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)

            bs = ticker.balance_sheet
            inc = ticker.financials
            if bs is None or getattr(bs, 'empty', True):
                return None, 'yahoo'

            def extract(frame, rows):
                out = []
                latest = frame.columns[0] if len(frame.columns) else None
                if latest is None:
                    return out
                for key, label in rows:
                    if key in frame.index:
                        out.append((label, _fmt_baht(frame.loc[key, latest])))
                return out

            period = str(bs.columns[0])[:10] if len(bs.columns) else ''
            data = {
                'balance_sheet': extract(bs, _BALANCE_ROWS),
                'income': extract(inc, _INCOME_ROWS) if inc is not None and not getattr(inc, 'empty', True) else [],
                'period': period,
                'cached': False,
            }
            if not data['balance_sheet'] and not data['income']:
                return None, 'yahoo'
            return data, 'yahoo'
        except Exception as exc:
            print(f'[FinancialsService] yahoo failed for {symbol}: {exc}')
            return None, 'yahoo'

    def _fetch_fmp(self, symbol: str) -> tuple[Optional[Dict[str, Any]], str]:
        api_key = Config.FMP_API_KEY
        if not api_key:
            print('[FinancialsService] FMP_API_KEY not set; skipping fallback')
            return None, 'fmp'
        sym = symbol.replace('.BK', '')
        # FMP covers Thai listings via .BK exchange suffix when available.
        for suffix in ('.BK', ''):
            try:
                resp = requests.get(
                    f'https://financialmodelingprep.com/api/v3/balance-sheet-statement/{sym}{suffix}',
                    params={'apikey': api_key, 'limit': 1},
                    timeout=20,
                )
                if resp.status_code != 200:
                    continue
                records = resp.json()
                if not isinstance(records, list) or not records:
                    continue
                r = records[0]
                data = {
                    'balance_sheet': [
                        ('สินทรัพย์รวม', _fmt_baht(r.get('totalAssets'))),
                        ('หนี้สินรวม', _fmt_baht(r.get('totalLiabilities'))),
                        ('ส่วนของผู้ถือหุ้น', _fmt_baht(r.get('totalStockholdersEquity'))),
                        ('เงินสดและรายการเทียบเท่า', _fmt_baht(r.get('cashAndCashEquivalents'))),
                        ('หนี้สินระยะยาว+ระยะสั้น', _fmt_baht(r.get('totalDebt'))),
                        ('กำไรสะสม', _fmt_baht(r.get('retainedEarnings'))),
                    ],
                    'income': [],
                    'period': str(r.get('date') or ''),
                    'cached': False,
                }
                return data, 'fmp'
            except Exception as exc:
                print(f'[FinancialsService] FMP error ({sym}{suffix}): {exc}')
        return None, 'fmp'
