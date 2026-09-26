from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from flask import Blueprint, abort, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    FlexSendMessage,
    MessageEvent,
    PostbackEvent,
    TextMessage,
    TextSendMessage,
)

from config import Config
import store
from line_templates import (
    get_add_stock_confirm_flex,
    get_global_setting_flex,
    get_scheduler_flex,
    get_specific_setting_flex,
    get_watchlist_carousel,
)
from tasks.queue import enqueue_report

line_webhook_bp = Blueprint('line_webhook', __name__)
line_bot_api = LineBotApi(Config.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(Config.LINE_CHANNEL_SECRET)


# --- Background processing: the webhook must return 200 within seconds ---
# (LINE aborts with "timeout occurred" otherwise). Heavy work (yfinance,
# LLM calls) runs here and results are delivered via push_message.
_BACKGROUND = ThreadPoolExecutor(max_workers=4, thread_name_prefix='line-bg')


def _quick_reply(event, text: str) -> None:
    """Reply immediately so LINE never sees a webhook timeout."""
    try:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
    except Exception as exc:
        print(f"[Quick Reply Error] {exc}")


def _push(line_user_id: str, messages) -> None:
    """Deliver results after the webhook already returned 200."""
    try:
        line_bot_api.push_message(line_user_id, messages)
    except Exception as exc:
        print(f"[Push Error] {exc}")


def _process_add_stocks(line_user_id: str, symbols: list[str]) -> None:
    confirm_flexes: list = []
    duplicate_list: list = []
    for symbol in symbols:
        found_symbol, price = check_stock_exists(symbol)
        if not (found_symbol and price):
            continue
        if store.get_watch_item(line_user_id, found_symbol):
            duplicate_list.append(found_symbol)
        else:
            flex_content = get_add_stock_confirm_flex(found_symbol, found_symbol, price)
            if flex_content and 'contents' in flex_content:
                confirm_flexes.append(flex_content['contents'])

    msgs = []
    if duplicate_list:
        msgs.append(TextSendMessage(text="! หุ้นเหล่านี้มีอยู่แล้ว: " + ", ".join(duplicate_list)))
    if confirm_flexes:
        msgs.append(FlexSendMessage(
            alt_text="ยืนยันการเพิ่มหุ้น",
            contents={"type": "carousel", "contents": confirm_flexes[:10]},
        ))
    if not msgs:
        msgs.append(TextSendMessage(text="ไม่พบข้อมูลหุ้นที่ค้นหา ลองตรวจสอบชื่อย่ออีกครั้ง"))
    _push(line_user_id, msgs)


def _process_news(line_user_id: str, symbol: str, profile: dict) -> None:
    from analysis.news_analysis import analyze_news
    from data.market_snapshot_service import MarketSnapshotService
    from reporting.line_report_renderer import LineReportRenderer
    from reporting.news_detail_renderer import render_news_detail_card

    snapshot, _ = MarketSnapshotService().get_or_collect(symbol)
    brief = analyze_news(snapshot, profile=profile)
    # Deep-view: ranked headlines with clickable sources; flash/summary text
    # stays URL-free because clean_headline already stripped links upstream.
    detail_bubble = render_news_detail_card(snapshot.symbol, brief)
    _push(line_user_id, FlexSendMessage(alt_text=f"ข่าว {snapshot.symbol} เรียงตามน้ำหนักกระทบ", contents=detail_bubble))
    # Follow with the synthesized brief card (flash summary + reasons).
    brief_bubble = LineReportRenderer.render_market_brief_card(snapshot.symbol, brief)
    _push(line_user_id, FlexSendMessage(alt_text=f"Market Brief {snapshot.symbol}", contents=brief_bubble))


def _process_why(line_user_id: str, symbol: str) -> None:
    """Deep-dive: WHY this signal — evidence with derivation, not raw dumps."""
    from data.financials_service import FinancialsService
    from data.market_snapshot_service import MarketSnapshotService
    from analysis.financial_ratios import compute_ratios, build_financial_reasoning
    from analysis.indicators import infer_trend

    snapshot, _ = MarketSnapshotService().get_or_collect(symbol)
    tech = snapshot.technicals
    trend = infer_trend(snapshot.price, tech)
    support = tech.get('support')
    resistance = tech.get('resistance')
    rsi = tech.get('rsi')
    sma20 = tech.get('sma20')
    sma50 = tech.get('sma50')

    evidence: list[str] = []
    if support not in (None, '-', 'N/A') and resistance not in (None, '-', 'N/A'):
        evidence.append(
            f"📐 แนวรับ {support} / แนวต้าน {resistance} — มาจาก จุดต่ำสุด-สูงสุดของราคาย้อนหลัง 30 วันทำการ "
            f"(swing low/high) ไม่ใช่การเดา หากราคาทะลุแนวต้านด้วย volume สูง มักต่อยอด หากหลุดแนวรับมักลงลึก"
        )
    if rsi not in (None, '-', 'N/A'):
        try:
            r = float(rsi)
            stance = (
                'เข้าเขต overbought (>65) ราคาอาจร้อนเกินไป ระวังย่อตัว'
                if r >= 65 else
                'เข้าเขต oversold (<35) อาจถูกขายล้นตลาด จังหวะเด้งมีโอกาส'
                if r <= 35 else
                'อยู่โซนกลาง (35-65) โมเมนตัมยังไม่บ่งชี้ทิศทางชัด'
            )
            evidence.append(f"📊 RSI(14) = {rsi} — {stance}")
        except (TypeError, ValueError):
            pass
    try:
        p = float(snapshot.price)
        s20 = float(sma20) if sma20 not in (None, '-', 'N/A') else None
        s50 = float(sma50) if sma50 not in (None, '-', 'N/A') else None
        if s20 and s50:
            if p > s20 > s50:
                evidence.append(f"📈 ราคา {p:,.2f} > SMA20 {sma20} > SMA50 {sma50} — MA เรียงตัวขึ้น แนวโน้มระยะสั้นและกลางเป็นบวก")
            elif p < s20 < s50:
                evidence.append(f"📉 ราคา {p:,.2f} < SMA20 {sma20} < SMA50 {sma50} — MA เรียงตัวลง แนวโน้มยังอ่อน")
            else:
                evidence.append(f"➡️ ราคา {p:,.2f} กับ MA ({sma20}/{sma50}) ยังสลับกัน — อยู่ในช่วง sideway รอทิศทางชัด")
    except (TypeError, ValueError):
        pass

    # Balance-sheet based reasons (works even without AI)
    try:
        fin = FinancialsService().get_financials(symbol)
        raw = (fin or {}).get('raw') or {}
        ratios = compute_ratios(raw)
        evidence.extend(build_financial_reasoning(raw, ratios, snapshot.price))
    except Exception as exc:
        print(f'[Why] financials unavailable for {symbol}: {exc}')

    verdict = {
        'Positive': 'สถานะรวม: โทนบวก — ราคาอยู่เหนือเกณฑ์เทคนิคสำคัญ',
        'Cautious': 'สถานะรวม: โทนระมัดระวัง — ราคาอ่อนแอกว่าเกณฑ์เทคนิค',
    }.get(trend, 'สถานะรวม: เป็นกลาง — สัญญาณยังไม่ชี้ทิศทางชัด')

    text = (
        f"💡 เพราะอะไร? วิเคราะห์ {symbol} @ {snapshot.price:,.2f}\n\n"
        + verdict + '\n\n'
        + '\n\n'.join(evidence[:6])
        + '\n\n⚠️ เป็นการวิเคราะห์จากข้อมูลเชิงประจักษ์ ไม่ใช่คำแนะนำลงทุน'
    )
    _push(line_user_id, TextSendMessage(text=text[:4900]))


def _process_financials(line_user_id: str, symbol: str) -> None:
    """Financial statements WITH interpretation — ratios, formulas, implications."""
    from data.financials_service import FinancialsService
    from data.market_snapshot_service import MarketSnapshotService
    from analysis.financial_ratios import compute_ratios, build_financial_reasoning

    snapshot, _ = MarketSnapshotService().get_or_collect(symbol)
    try:
        fin_data = FinancialsService().get_financials(symbol)
    except Exception as exc:
        print(f'[Financials] unavailable for {symbol}: {exc}')
        fin_data = None

    fin_text = (
        f"📊 ข้อมูลทางการเงิน {symbol}:\n"
        f"- ราคา: {snapshot.price:,.2f}\n"
        f"- P/E: {snapshot.pe_ratio or 'N/A'} (ราคา ÷ กำไรต่อหุ้น = จ่ายกี่เท่าของกำไรต่อปี)\n"
        f"- Dividend Yield: {snapshot.div_yield or 'N/A'}% (เงินปันผล ÷ ราคาหุ้น)\n\n"
    )
    raw = (fin_data or {}).get('raw') or {}
    if raw:
        ratios = compute_ratios(raw)
        fin_text += "🧮 วิเคราะห์อัตราส่วน (จากงบล่าสุด):\n"
        for line in build_financial_reasoning(raw, ratios, snapshot.price):
            fin_text += f"• {line}\n"
        fin_text += "\n"
    if fin_data and fin_data.get('balance_sheet'):
        fin_text += f"🏦 งบดุล (งวด {fin_data.get('period') or 'ล่าสุด'}):\n"
        for label, value in fin_data['balance_sheet'][:6]:
            fin_text += f"- {label}: {value}\n"
    if fin_data and fin_data.get('income'):
        fin_text += "\n💰 งบกำไรขาดทุน:\n"
        for label, value in fin_data['income'][:4]:
            fin_text += f"- {label}: {value}\n"
    if fin_data:
        fin_text += f"\n(แหล่งข้อมูล: {fin_data.get('source')})"
    else:
        fin_text += "🏦 งบการเงินยังไม่พร้อมใช้งานสำหรับหุ้นตัวนี้ — แสดงเฉพาะข้อมูลเทคนิคชั่วคราว"
    _push(line_user_id, TextSendMessage(text=fin_text[:4900]))


def check_stock_exists(symbol: str):
    """Check stock existence using yfinance."""
    import yfinance as yf

    symbol = symbol.upper().strip()
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if info and ('currentPrice' in info or 'regularMarketPrice' in info):
            price = float(info.get('currentPrice') or info.get('regularMarketPrice') or 0.0)
            if price > 0:
                return symbol, price
    except Exception as exc:
        print(f"[Check Stock Error] {symbol}: {exc}")

    if not symbol.endswith(".BK"):
        thai_symbol = symbol + ".BK"
        try:
            ticker = yf.Ticker(thai_symbol)
            info = ticker.info
            if info and ('currentPrice' in info or 'regularMarketPrice' in info):
                price = float(info.get('currentPrice') or info.get('regularMarketPrice') or 0.0)
                if price > 0:
                    return thai_symbol, price
        except Exception as exc:
            print(f"[Check Stock Thai Error] {thai_symbol}: {exc}")

    return None, None


@line_webhook_bp.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id

    if text == "เพิ่มรายชื่อหุ้น":
        store.get_or_create_user(user_id)
        store.set_chat_state(user_id, "ADD_STOCK")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="พิมพ์ชื่อหุ้นที่ต้องการเพิ่ม (เช่น PTT NVDA) หรือพิมพ์หลายตัวด้วยการเว้นวรรค"),
        )
        return

    menu_keywords = ["ตั้งเวลา", "แสดงผล", "รายการหุ้น", "ตั้งค่า", "ผลงาน", "Setting", "Watcher"]
    if any(k in text for k in menu_keywords):
        store.get_or_create_user(user_id)
        store.set_chat_state(user_id, None)
        return

    store.get_or_create_user(user_id)
    current_state = store.get_chat_state(user_id)
    if current_state == "ADD_STOCK":
        potential_stocks = [s.upper() for s in text.split() if 2 <= len(s.upper()) <= 10]
        store.set_chat_state(user_id, None)
        if not potential_stocks:
            _quick_reply(event, f"ไม่พบชื่อหุ้นที่ถูกต้อง: {text}")
            return
        _quick_reply(event, f"กำลังตรวจสอบ {len(potential_stocks)} หุ้น... สักครู่ครับ")
        # Heavy: yfinance lookups — run in background, deliver via push_message
        _BACKGROUND.submit(_process_add_stocks, user_id, potential_stocks)
        return
    else:
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาเลือกเมนูจากด้านล่างครับ ↓"))
        except Exception:
            pass


@handler.add(PostbackEvent)
def handle_postback(event):
    if hasattr(event, 'delivery_context') and event.delivery_context.is_redelivery:
        print(f"[SKIP] Redelivery Postback: {getattr(event, 'webhook_event_id', '')}")
        return

    data = event.postback.data or ""
    user_id = event.source.user_id
    user = store.get_or_create_user(user_id)

    params = {}
    for part in data.split('&'):
        if '=' in part:
            k, v = part.split('=', 1)
            params[k] = v

    action = params.get('action', '')
    symbol = params.get('symbol', '').upper()

    try:
        # --- Add Stock ---
        if action == 'add_stock' and symbol:
            if store.count_watchlist(user_id) >= 10:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="เพิ่มได้สูงสุด 10 หุ้น กรุณาลบหุ้นบางตัวออกก่อนครับ"),
                )
                return
            if store.add_watch_item(user_id, symbol):
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"ยืนยันเพิ่ม {symbol} เข้า Watchlist แล้ว"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{symbol} อยู่ใน Watchlist แล้ว"))

        elif action in ('cancel_add', 'cancel'):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยกเลิกรายการแล้ว"))

        # --- Delete Stock (two-step confirm) ---
        elif action == 'confirm_delete' and symbol:
            confirm_bubble = {
                "type": "bubble",
                "size": "mega",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "🗑 ยืนยันการลบ", "size": "lg", "weight": "bold", "color": "#B42318"},
                        {"type": "text", "text": f"ต้องการลบ {symbol} ออกจาก Watchlist ใช่หรือไม่?", "size": "sm", "color": "#374151", "wrap": True, "margin": "md"},
                        {"type": "text", "text": "การลบไม่สามารถย้อนกลับได้", "size": "xxs", "color": "#9CA3AF", "margin": "sm"},
                    ],
                },
                "footer": {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "color": "#ff4444",
                            "height": "sm",
                            "action": {"type": "postback", "label": "ลบเลย", "data": f"action=delete&symbol={symbol}"},
                        },
                        {
                            "type": "button",
                            "style": "secondary",
                            "height": "sm",
                            "action": {"type": "postback", "label": "ยกเลิก", "data": "action=cancel"},
                        },
                    ],
                },
            }
            line_bot_api.reply_message(
                event.reply_token,
                FlexSendMessage(alt_text=f"ยืนยันลบ {symbol}", contents=confirm_bubble),
            )

        elif action in ('delete_stock', 'delete') and symbol:
            if store.delete_watch_item(user_id, symbol):
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"ลบ {symbol} ออกจาก Watchlist แล้ว"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ไม่พบรายการที่จะลบ"))

        # --- Settings ---
        elif action in ('specific_setting', 'settings') and symbol:
            flex = get_specific_setting_flex(symbol)
            if flex:
                line_bot_api.reply_message(
                    event.reply_token,
                    FlexSendMessage(alt_text=f"Settings {symbol}", contents=flex['contents']),
                )

        elif action in ('main_setting', 'global_setting', 'settings'):
            flex = get_global_setting_flex()
            if flex:
                line_bot_api.reply_message(
                    event.reply_token,
                    FlexSendMessage(alt_text="Global Settings", contents=flex['contents']),
                )

        # --- Save Settings ---
        elif 'global' in action and 'setting' not in action:
            parts = action.split('_')
            if len(parts) >= 3:
                setting_type, val_key = parts[1], parts[2]
                val_map = {
                    'dca': 'DCA', 'ai': 'AI-Auto', 'value': 'Value', 'growth': 'Growth',
                    'dividend': 'Dividend', 'technical': 'Technical',
                    'short': 'Short', 'medium': 'Medium', 'long': 'Long',
                    'low': 'Low', 'high': 'High',
                }
                final_val = val_map.get(val_key, val_key.capitalize())
                if setting_type == 'strategy':
                    store.update_user(user_id, {'core_strategy': final_val})
                elif setting_type == 'goal':
                    store.update_user(user_id, {'investment_goal': final_val})
                elif setting_type == 'risk':
                    store.update_user(user_id, {'risk_appetite': final_val})
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✓ บันทึกการตั้งค่า {setting_type.capitalize()} = {final_val}"))

        elif 'stock' in action and symbol:
            parts = action.split('_')
            if len(parts) >= 3:
                setting_type, val_key = parts[1], parts[2]
                val_map = {
                    'dca': 'DCA', 'ai': 'AI-Auto', 'value': 'Value', 'growth': 'Growth',
                    'dividend': 'Dividend', 'technical': 'Technical',
                    'short': 'Short', 'medium': 'Medium', 'long': 'Long',
                    'low': 'Low', 'high': 'High',
                }
                final_val = val_map.get(val_key, val_key.capitalize())
                wl_item = store.get_watch_item(user_id, symbol)
                if wl_item:
                    updates = {}
                    if setting_type == 'strategy':
                        updates['strategy'] = final_val
                    elif setting_type == 'goal':
                        updates['goal'] = final_val
                    elif setting_type == 'risk':
                        updates['risk'] = final_val
                    store.update_watch_item(user_id, symbol, **updates)
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✓ บันทึก {symbol} {setting_type.capitalize()} = {final_val}"))

        # --- Schedule ---
        elif action == 'set_time':
            flex = get_scheduler_flex()
            if flex:
                line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="Schedule", contents=flex['contents']))

        elif action == 'time_set':
            time_val = event.postback.params.get('time') if hasattr(event.postback, 'params') else None
            if time_val:
                dt = datetime.strptime(time_val, "%H:%M")
                if dt.minute >= 30:
                    dt = dt + timedelta(hours=1)
                final_time = dt.replace(minute=0, second=0).strftime("%H:%M")

                store.upsert_schedule(user_id, alert_time=final_time, is_active=True)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"ตั้งเวลาแจ้งเตือนรายวัน: {final_time}"))

        elif action == 'reset_time':
            store.upsert_schedule(user_id, is_active=False)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ปิดการแจ้งเตือนแล้ว"))

        # --- View Watchlist ---
        elif action == 'view_watchlist':
            items = store.list_watchlist(user_id)
            if not items:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="Watchlist ของคุณว่างเปล่า"))
            else:
                flex = get_watchlist_carousel(items)
                if flex:
                    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="Watchlist", contents=flex['contents']))

        # --- Report Actions (Rule 8 postback buttons: Why?, News, Financials, Refresh, Schedule) ---
        elif action in ('why', 'news', 'financials') and symbol:
            # Debounce: rapid repeated presses within 30s are ignored so the
            # same analysis never runs twice and users never get duplicates.
            if not store.try_acquire_action_lock(user_id, action, symbol, ttl_seconds=30):
                _quick_reply(event, f"⏳ กำลังประมวลผล {symbol} อยู่แล้ว รอผลลัพธ์สักครู่ครับ")
                return
            labels = {
                'why': f"กำลังวิเคราะห์ {symbol}... สักครู่ครับ",
                'news': f"📡 กำลังคัดกรองและจัดอันดับข่าว {symbol}... สักครู่ครับ",
                'financials': f"กำลังดึงงบการเงิน {symbol}... สักครู่ครับ",
            }
            _quick_reply(event, labels[action])
            handlers = {'why': _process_why, 'news': _process_news, 'financials': _process_financials}
            if action == 'news':
                _BACKGROUND.submit(
                    _process_news, user_id, symbol,
                    {
                        'core_strategy': user.get('core_strategy'),
                        'investment_goal': user.get('investment_goal'),
                        'risk_appetite': user.get('risk_appetite'),
                    },
                )
            else:
                _BACKGROUND.submit(handlers[action], user_id, symbol)

        elif action in ('get_report', 'refresh'):
            # Debounce per symbol (refresh) or per user (full watchlist pull).
            if not store.try_acquire_action_lock(user_id, action, symbol, ttl_seconds=30):
                _quick_reply(event, "⏳ มีรายการที่กำลังประมวลผลอยู่แล้ว รอสักครู่ครับ")
                return

        elif action in ('get_report', 'refresh'):
            target_symbol = symbol if action == 'refresh' else None
            if target_symbol:
                item = store.get_watch_item(user_id, target_symbol)
                items = [item] if item else []
            else:
                items = store.list_watchlist(user_id)

            if not items:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ไม่มีหุ้นในรายการ"))
                return

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"กำลังประมวลผลข้อมูลหุ้น {len(items)} รายการ กรุณารอสักครู่..."),
            )

            user_settings_snapshot = {
                'core_strategy': user.get('core_strategy'),
                'investment_goal': user.get('investment_goal'),
                'risk_appetite': user.get('risk_appetite'),
                'report_format': user.get('report_format'),
            }
            safe_items = [
                {
                    'symbol': item['symbol'],
                    'strategy': item.get('strategy'),
                    'goal': item.get('goal'),
                    'risk': item.get('risk'),
                    'report_format': item.get('report_format'),
                }
                for item in items
            ]
            enqueue_report(user_id, user_id, safe_items, user_settings_snapshot)

        elif action == 'our_products':
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="รอติดตามผลงานเร็วๆนี้"))

    except Exception as exc:
        print(f"[Webhook Postback Error]: {exc}")
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="! เกิดข้อผิดพลาดในการประมวลผล"))
        except Exception:
            pass
