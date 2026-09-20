from __future__ import annotations

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

USER_STATES: dict[str, Any] = {}


def get_or_create_user(line_user_id: str):
    db = SessionLocal()
    user = db.query(User).filter(User.line_user_id == line_user_id).first()
    if not user:
        user = User(line_user_id=line_user_id)
        db.add(user)
        db.commit()
    return user, db


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
        USER_STATES[user_id] = "ADD_STOCK"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="พิมพ์ชื่อหุ้นที่ต้องการเพิ่ม (เช่น PTT NVDA) หรือพิมพ์หลายตัวด้วยการเว้นวรรค"),
        )
        return

    menu_keywords = ["ตั้งเวลา", "แสดงผล", "รายการหุ้น", "ตั้งค่า", "ผลงาน", "Setting", "Watcher"]
    if any(k in text for k in menu_keywords):
        if user_id in USER_STATES:
            del USER_STATES[user_id]
        return

    current_state = USER_STATES.get(user_id)
    if current_state == "ADD_STOCK":
        potential_stocks = text.split()
        confirm_flexes = []
        duplicate_list = []

        user, db = get_or_create_user(user_id)
        for raw_symbol in potential_stocks:
            symbol = raw_symbol.upper()
            if len(symbol) < 2 or len(symbol) > 10:
                continue

            found_symbol, price = check_stock_exists(symbol)
            if found_symbol and price:
                exists = db.query(Watchlist).filter_by(user_id=user.id, symbol=found_symbol).first()
                if exists:
                    duplicate_list.append(found_symbol)
                else:
                    flex_content = get_add_stock_confirm_flex(found_symbol, found_symbol, price)
                    if flex_content and 'contents' in flex_content:
                        confirm_flexes.append(flex_content['contents'])
        db.close()

        msgs = []
        if duplicate_list:
            msgs.append(TextSendMessage(text="! หุ้นเหล่านี้มีอยู่แล้ว: " + ", ".join(duplicate_list)))
        if confirm_flexes:
            msgs.append(
                FlexSendMessage(
                    alt_text="ยืนยันการเพิ่มหุ้น",
                    contents={"type": "carousel", "contents": confirm_flexes[:10]},
                )
            )

        if not confirm_flexes and not duplicate_list:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"ไม่พบข้อมูลหุ้น: {text}"))
        else:
            try:
                line_bot_api.reply_message(event.reply_token, msgs)
            except Exception as e:
                print(f"Reply Error: {e}")
        del USER_STATES[user_id]
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

    if user_id in USER_STATES:
        del USER_STATES[user_id]

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

        # --- Delete Stock ---
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
            from data.market_snapshot_service import MarketSnapshotService
            snapshot, _ = MarketSnapshotService(db_session=db).get_or_collect(symbol)
            reasons_text = f"💡 เหตุผลเชิงลึกสำหรับ {symbol}:\n"
            for k, v in snapshot.technicals.items():
                reasons_text += f"- {k}: {v}\n"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reasons_text.strip()))

        elif action == 'news' and symbol:
            from analysis.news_analysis import analyze_news
            from data.market_snapshot_service import MarketSnapshotService
            snapshot, _ = MarketSnapshotService(db_session=db).get_or_collect(symbol)
            brief = analyze_news(snapshot, profile={
                'core_strategy': user.core_strategy,
                'investment_goal': user.investment_goal,
                'risk_appetite': user.risk_appetite,
            })
            impact_icon = {'Positive': '🟢', 'Mixed': '🟡', 'Negative': '🔴'}.get(brief['impact'], '🟡')
            news_text = (
                f"📰 Market Brief: {snapshot.symbol} {impact_icon} {brief['impact']}\n\n"
                f"{brief['summary']}\n\n"
                + "\n".join(f"• {n}" for n in brief['news'][:5])
                + "\n\n💡 คำแนะนำ:\n" + "\n".join(f"- {a}" for a in brief['advice'])
                + f"\n\n_{brief['disclaimer']}_"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=news_text[:4900]))

        elif action == 'financials' and symbol:
            from data.market_snapshot_service import MarketSnapshotService
            snapshot, _ = MarketSnapshotService(db_session=db).get_or_collect(symbol)
            fin_text = (
                f"📊 ข้อมูลทางการเงิน {symbol}:\n"
                f"- ราคา: {snapshot.price:,.2f}\n"
                f"- P/E: {snapshot.pe_ratio or 'N/A'}\n"
                f"- Dividend Yield: {snapshot.div_yield or 'N/A'}%\n"
                f"- RSI(14): {snapshot.technicals.get('rsi', 'N/A')}\n"
                f"- SMA50: {snapshot.technicals.get('sma50', 'N/A')}\n"
                f"- แนวรับ/แนวต้าน: {snapshot.technicals.get('support', '-')}/{snapshot.technicals.get('resistance', '-')}"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=fin_text))

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
