from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from flask import Blueprint, abort, current_app, request
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
from database import Schedule, SessionLocal, User, Watchlist
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

def get_or_create_user(line_user_id: str):
    db = SessionLocal()
    user = db.query(User).filter(User.line_user_id == line_user_id).first()
    if not user:
        user = User(line_user_id=line_user_id)
        db.add(user)
        db.commit()
    return user, db


def set_chat_state(line_user_id: str, db, state: str | None) -> None:
    """Persist chat state on the user row so state survives instance restarts
    and is shared across Cloud Run instances."""
    user = db.query(User).filter(User.line_user_id == line_user_id).first()
    if user is None:
        return
    user.chat_state = state
    db.commit()


def get_chat_state(line_user_id: str, db) -> str | None:
    user = db.query(User).filter(User.line_user_id == line_user_id).first()
    return user.chat_state if user else None


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


def _process_add_stocks(line_user_id: str, user_pk, symbols: list[str]) -> None:
    confirm_flexes: list = []
    duplicate_list: list = []
    db = SessionLocal()
    try:
        for symbol in symbols:
            found_symbol, price = check_stock_exists(symbol)
            if found_symbol and price:
                exists = db.query(Watchlist).filter_by(user_id=user_pk, symbol=found_symbol).first()
                if exists:
                    duplicate_list.append(found_symbol)
                else:
                    flex_content = get_add_stock_confirm_flex(found_symbol, found_symbol, price)
                    if flex_content and 'contents' in flex_content:
                        confirm_flexes.append(flex_content['contents'])
        db.commit()
    finally:
        db.close()

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

    db = SessionLocal()
    try:
        snapshot, _ = MarketSnapshotService(db_session=db).get_or_collect(symbol)
    finally:
        db.close()
    brief = analyze_news(snapshot, profile=profile)
    brief_bubble = LineReportRenderer.render_market_brief_card(snapshot.symbol, brief)
    _push(line_user_id, FlexSendMessage(alt_text=f"Market Brief {snapshot.symbol}", contents=brief_bubble))


def _process_why(line_user_id: str, symbol: str) -> None:
    from data.market_snapshot_service import MarketSnapshotService

    db = SessionLocal()
    try:
        snapshot, _ = MarketSnapshotService(db_session=db).get_or_collect(symbol)
    finally:
        db.close()
    reasons_text = f"💡 เหตุผลเชิงลึกสำหรับ {symbol}:\n"
    for k, v in snapshot.technicals.items():
        reasons_text += f"- {k}: {v}\n"
    _push(line_user_id, TextSendMessage(text=reasons_text.strip()[:4900]))


def _process_financials(line_user_id: str, symbol: str) -> None:
    from data.financials_service import FinancialsService
    from data.market_snapshot_service import MarketSnapshotService

    fin_data = None
    db = SessionLocal()
    try:
        snapshot, _ = MarketSnapshotService(db_session=db).get_or_collect(symbol)
        try:
            fin_data = FinancialsService().get_financials(symbol, db=db)
        except Exception as exc:
            print(f'[Financials] unavailable for {symbol}: {exc}')
    finally:
        db.close()

    fin_text = (
        f"📊 ข้อมูลทางการเงิน {symbol}:\n"
        f"- ราคา: {snapshot.price:,.2f}\n"
        f"- P/E: {snapshot.pe_ratio or 'N/A'}\n"
        f"- Dividend Yield: {snapshot.div_yield or 'N/A'}%\n"
        f"- RSI(14): {snapshot.technicals.get('rsi', 'N/A')}\n"
        f"- SMA50: {snapshot.technicals.get('sma50', 'N/A')}\n"
        f"- แนวรับ/แนวต้าน: {snapshot.technicals.get('support', '-')}/{snapshot.technicals.get('resistance', '-')}\n\n"
    )
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
        fin_text += "🏦 งบการเงินยังไม่พร้อมใช้งานสำหรับหุ้นตัวนี้"
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
        user, db = get_or_create_user(user_id)
        set_chat_state(user_id, db, "ADD_STOCK")
        db.close()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="พิมพ์ชื่อหุ้นที่ต้องการเพิ่ม (เช่น PTT NVDA) หรือพิมพ์หลายตัวด้วยการเว้นวรรค"),
        )
        return

    menu_keywords = ["ตั้งเวลา", "แสดงผล", "รายการหุ้น", "ตั้งค่า", "ผลงาน", "Setting", "Watcher"]
    if any(k in text for k in menu_keywords):
        user, db = get_or_create_user(user_id)
        set_chat_state(user_id, db, None)
        db.close()
        return

    user, db = get_or_create_user(user_id)
    current_state = get_chat_state(user_id, db)
    if current_state == "ADD_STOCK":
        potential_stocks = [s.upper() for s in text.split() if 2 <= len(s.upper()) <= 10]
        db.commit()
        set_chat_state(user_id, db, None)
        db.close()
        if not potential_stocks:
            _quick_reply(event, f"ไม่พบชื่อหุ้นที่ถูกต้อง: {text}")
            return
        _quick_reply(event, f"กำลังตรวจสอบ {len(potential_stocks)} หุ้น... สักครู่ครับ")
        # Heavy: yfinance lookups — run in background, deliver via push_message
        _BACKGROUND.submit(_process_add_stocks, user_id, user.id, potential_stocks)
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
    user, db = get_or_create_user(user_id)

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
            count = db.query(Watchlist).filter_by(user_id=user.id).count()
            if count >= 10:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="เพิ่มได้สูงสุด 10 หุ้น กรุณาลบหุ้นบางตัวออกก่อนครับ"),
                )
                return
            exists = db.query(Watchlist).filter_by(user_id=user.id, symbol=symbol).first()
            if not exists:
                db.add(Watchlist(user_id=user.id, symbol=symbol))
                db.commit()
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
            item = db.query(Watchlist).filter_by(user_id=user.id, symbol=symbol).first()
            if item:
                db.delete(item)
                db.commit()
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
                    user.core_strategy = final_val
                elif setting_type == 'goal':
                    user.investment_goal = final_val
                elif setting_type == 'risk':
                    user.risk_appetite = final_val
                db.commit()
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
                wl_item = db.query(Watchlist).filter_by(user_id=user.id, symbol=symbol).first()
                if wl_item:
                    if setting_type == 'strategy':
                        wl_item.strategy = final_val
                    elif setting_type == 'goal':
                        wl_item.goal = final_val
                    elif setting_type == 'risk':
                        wl_item.risk = final_val
                    db.commit()
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

                sched = db.query(Schedule).filter_by(user_id=user.id).first()
                if not sched:
                    sched = Schedule(user_id=user.id)
                    db.add(sched)
                sched.alert_time = final_time
                sched.is_active = True
                db.commit()
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"ตั้งเวลาแจ้งเตือนรายวัน: {final_time}"))

        elif action == 'reset_time':
            sched = db.query(Schedule).filter_by(user_id=user.id).first()
            if sched:
                sched.is_active = False
                db.commit()
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ปิดการแจ้งเตือนแล้ว"))

        # --- View Watchlist ---
        elif action == 'view_watchlist':
            items = db.query(Watchlist).filter_by(user_id=user.id).all()
            if not items:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="Watchlist ของคุณว่างเปล่า"))
            else:
                flex = get_watchlist_carousel(items)
                if flex:
                    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="Watchlist", contents=flex['contents']))

        # --- Report Actions (Rule 8 postback buttons: Why?, News, Financials, Refresh, Schedule) ---
        elif action == 'why' and symbol:
            _quick_reply(event, f"กำลังวิเคราะห์ {symbol}... สักครู่ครับ")
            _BACKGROUND.submit(_process_why, user_id, symbol)

        elif action == 'news' and symbol:
            _quick_reply(event, f"กำลังวิเคราะห์ข่าว {symbol}... สักครู่ครับ 📡")
            _BACKGROUND.submit(
                _process_news, user_id, symbol,
                {
                    'core_strategy': user.core_strategy,
                    'investment_goal': user.investment_goal,
                    'risk_appetite': user.risk_appetite,
                },
            )

        elif action == 'financials' and symbol:
            _quick_reply(event, f"กำลังดึงงบการเงิน {symbol}... สักครู่ครับ")
            _BACKGROUND.submit(_process_financials, user_id, symbol)

        elif action in ('get_report', 'refresh'):
            target_symbol = symbol if action == 'refresh' else None
            items = (
                db.query(Watchlist).filter_by(user_id=user.id, symbol=target_symbol).all()
                if target_symbol
                else db.query(Watchlist).filter_by(user_id=user.id).all()
            )

            if not items:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ไม่มีหุ้นในรายการ"))
                return

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"กำลังประมวลผลข้อมูลหุ้น {len(items)} รายการ กรุณารอสักครู่..."),
            )

            user_settings_snapshot = {
                'core_strategy': user.core_strategy,
                'investment_goal': user.investment_goal,
                'risk_appetite': user.risk_appetite,
                'report_format': user.report_format,
            }
            safe_items = [
                {
                    'symbol': item.symbol,
                    'strategy': item.strategy,
                    'goal': item.goal,
                    'risk': item.risk,
                    'report_format': item.report_format,
                }
                for item in items
            ]
            enqueue_report(user.id, user_id, safe_items, user_settings_snapshot)

        elif action == 'our_products':
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="รอติดตามผลงานเร็วๆนี้"))

    except Exception as exc:
        print(f"[Webhook Postback Error]: {exc}")
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="! เกิดข้อผิดพลาดในการประมวลผล"))
        except Exception:
            pass
    finally:
        db.close()
