"""Channel-agnostic chat orchestration shared by LINE, Web UI, and Discord.

Each channel adapter converts its own message shape into a ChatRequest and
renders the ChatResponse payloads for its platform. Business logic (news
analysis, full reports, add-to-watchlist) lives only here so all channels
stay behaviorally identical.

Storage goes through the unified store layer (Firestore on GCP, in-memory
for local dev/tests) — no SQL sessions anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import store
from data.market_snapshot_service import MarketSnapshotService
from workflows import ReportWorkflow


@dataclass
class ChatRequest:
    """Normalized incoming message from any channel."""
    channel: str                      # 'line' | 'web' | 'discord'
    channel_user_id: str              # platform-specific id
    text: str
    profile: Dict[str, str] = field(default_factory=dict)
    display_name: str = ''


@dataclass
class ChatResponse:
    """Normalized outgoing reply; `kind` selects the channel renderer."""
    kind: str                         # 'text' | 'report_card' | 'market_brief' | 'add_confirm'
    text: str = ''
    payload: Dict[str, Any] = field(default_factory=dict)  # renderer-specific


# ------------------------------------------------------------------ helpers

def _user_key(channel: str, channel_user_id: str) -> str:
    """Users are keyed per channel so the same human can exist on LINE and Discord."""
    return f'{channel}:{channel_user_id}'


def _get_or_create_user(req: ChatRequest) -> Dict:
    return store.get_or_create_user(
        _user_key(req.channel, req.channel_user_id), req.display_name or ''
    )


def _profile_of(user: Dict) -> Dict[str, str]:
    return {
        'core_strategy': user.get('core_strategy') or 'AI-Auto',
        'investment_goal': user.get('investment_goal') or 'Medium',
        'risk_appetite': user.get('risk_appetite') or 'Medium',
        'report_format': user.get('report_format') or 'Short',
    }


def _resolve_symbol(raw: str) -> Optional[str]:
    """Accept PTT, ptt.bk, NVDA; validate via yfinance like the LINE flow."""
    symbol = raw.upper().strip()
    if len(symbol) < 2 or len(symbol) > 10:
        return None
    candidates = [symbol] if symbol.endswith('.BK') else [symbol, f'{symbol}.BK']
    import yfinance as yf
    for candidate in candidates:
        try:
            info = yf.Ticker(candidate).info or {}
            price = info.get('currentPrice') or info.get('regularMarketPrice')
            if price and float(price) > 0:
                return candidate
        except Exception:
            continue
    return None


# ----------------------------------------------------------------- handlers

def handle_add_stocks(req: ChatRequest) -> List[ChatResponse]:
    """Validate and add symbols; returns per-symbol confirmations."""
    user = _get_or_create_user(req)
    user_key = user['user_key']
    responses: List[ChatResponse] = []
    added, duplicates, not_found = [], [], []

    for raw in req.text.split():
        symbol = _resolve_symbol(raw)
        if not symbol:
            not_found.append(raw.upper())
            continue
        if store.add_watch_item(user_key, symbol):
            added.append(symbol)
        else:
            duplicates.append(symbol)

    if added:
        responses.append(ChatResponse(
            kind='text',
            text='✓ เพิ่มเข้า Watchlist แล้ว: ' + ', '.join(added),
        ))
    if duplicates:
        responses.append(ChatResponse(
            kind='text', text='! หุ้นเหล่านี้มีอยู่แล้ว: ' + ', '.join(duplicates),
        ))
    if not_found:
        responses.append(ChatResponse(
            kind='text', text='ไม่พบข้อมูลหุ้น: ' + ', '.join(not_found),
        ))
    if not responses:
        responses.append(ChatResponse(kind='text', text='ไม่พบข้อมูลหุ้นที่ถูกต้อง'))
    return responses


def handle_market_brief(req: ChatRequest, symbol: str) -> ChatResponse:
    """News -> AI analysis -> Thai Market Brief (uses cached snapshot)."""
    from analysis.news_analysis import analyze_news

    user = _get_or_create_user(req)
    snapshot, _ = MarketSnapshotService().get_or_collect(symbol)
    brief = analyze_news(snapshot, profile=_profile_of(user))
    return ChatResponse(kind='market_brief', payload={
        'symbol': snapshot.symbol, 'brief': brief, 'snapshot': snapshot.to_dict(),
    })


def handle_full_report(req: ChatRequest, symbols: List[str]) -> List[ChatResponse]:
    """Run the full LangGraph workflow for each symbol."""
    user = _get_or_create_user(req)
    profile = {**_profile_of(user), **req.profile}
    responses: List[ChatResponse] = []
    for symbol in symbols:
        try:
            report = ReportWorkflow().run(symbol, profile, user_key=user['user_key'])
            responses.append(ChatResponse(kind='report_card', payload=report))
        except Exception as exc:
            print(f'[ChatService] report failed for {symbol}: {exc}')
            responses.append(ChatResponse(
                kind='text', text=f'! ไม่สามารถสร้างรายงานสำหรับ {symbol} ได้ในขณะนี้',
            ))
    return responses


def handle_watchlist(req: ChatRequest) -> ChatResponse:
    user = _get_or_create_user(req)
    items = store.list_watchlist(user['user_key'])
    if not items:
        return ChatResponse(kind='text', text='Watchlist ของคุณว่างเปล่า — พิมพ์ "add PTT" เพื่อเพิ่มหุ้น')
    lines = [f"• {item['symbol']}" for item in items]
    return ChatResponse(kind='text', text='📋 Watchlist ของคุณ:\n' + '\n'.join(lines))


# ------------------------------------------------------- command dispatcher

HELP_TEXT = (
    'คำสั่งที่ใช้ได้:\n'
    '• add <หุ้น> — เพิ่มหุ้นเข้า Watchlist (เช่น add PTT NVDA)\n'
    '• news <หุ้น> — Market Brief วิเคราะห์ข่าวโดย AI\n'
    '• report <หุ้น...> — รายงานวิเคราะห์เต็ม\n'
    '• watchlist — ดูรายการหุ้น\n'
    '• help — แสดงคำสั่งทั้งหมด'
)


def dispatch(req: ChatRequest) -> List[ChatResponse]:
    """Parse the message and route to the right handler. Raises nothing."""
    try:
        text = req.text.strip()
        lowered = text.lower()

        if not text:
            return [ChatResponse(kind='text', text=HELP_TEXT)]

        parts = text.split()
        command = parts[0].lower()

        if command in ('help', 'เริ่ม', 'start', '/start'):
            return [ChatResponse(kind='text', text=HELP_TEXT)]

        if command in ('add', 'เพิ่ม'):
            if len(parts) < 2:
                return [ChatResponse(kind='text', text='พิมพ์ชื่อหุ้นที่ต้องการเพิ่ม เช่น: add PTT NVDA')]
            return handle_add_stocks(req)

        if command in ('news', 'ข่าว'):
            if len(parts) < 2:
                return [ChatResponse(kind='text', text='ระบุชื่อหุ้นด้วย เช่น: news PTT')]
            symbol = _resolve_symbol(parts[1])
            if not symbol:
                return [ChatResponse(kind='text', text=f'ไม่พบข้อมูลหุ้น: {parts[1]}')]
            return [handle_market_brief(req, symbol)]

        if command in ('report', 'รายงาน', 'analyze'):
            if len(parts) < 2:
                return [ChatResponse(kind='text', text='ระบุชื่อหุ้นด้วย เช่น: report PTT NVDA')]
            symbols = []
            for raw in parts[1:]:
                symbol = _resolve_symbol(raw)
                if symbol:
                    symbols.append(symbol)
            if not symbols:
                return [ChatResponse(kind='text', text='ไม่พบข้อมูลหุ้นที่ระบุ')]
            return handle_full_report(req, symbols)

        if command in ('watchlist', 'รายการหุ้น'):
            return [handle_watchlist(req)]

        # Bare ticker (e.g. "PTT" or "PTT.BK") -> treat as report request
        if len(parts) == 1 and _resolve_symbol(parts[0]):
            return handle_full_report(req, [parts[0].upper()])

        return [ChatResponse(kind='text', text='ไม่เข้าใจคำสั่ง\n\n' + HELP_TEXT)]
    except Exception as exc:
        print(f'[ChatService] dispatch error: {exc}')
        return [ChatResponse(kind='text', text='! เกิดข้อผิดพลาดในการประมวลผล กรุณาลองใหม่')]
