from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    PostbackEvent, FlexSendMessage
)

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from database import SessionLocal, User, Watchlist
from line_templates import (
    get_add_stock_confirm_flex, get_watchlist_carousel,
    get_global_setting_flex, get_specific_setting_flex,
    get_scheduler_flex, get_analysis_flex
)

from analyzer import AnalysisEngine
from datetime import datetime, timedelta

app = Flask(__name__)
app.config.from_object(Config)

# Verify line_ux directory
print(f"[INIT] BASE_DIR: {Config.BASE_DIR}")
ux_dir = os.path.join(Config.BASE_DIR, 'line_ux')
if os.path.exists(ux_dir):
    print(f"[INIT] Found 'line_ux'")
else:
    print(f"[INIT] CRITICAL: 'line_ux' directory NOT FOUND at {ux_dir}")

line_bot_api = LineBotApi(Config.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(Config.LINE_CHANNEL_SECRET)
analyzer = AnalysisEngine()

USER_STATES = {}
_db_initialized = False

def ensure_db_initialized():
    global _db_initialized
    if not _db_initialized:
        from database import Base, engine
        try:
            print("Lazy initializing database...")
            Base.metadata.create_all(bind=engine)
            
            try:
                from init_cache_db import Base as CacheBase
            except ImportError:
                from src.init_cache_db import Base as CacheBase
            
            CacheBase.metadata.create_all(bind=engine)
            
            _db_initialized = True
            print("Database initialization successful.")
        except Exception as e:
            print(f"Database Init Warning: {e}")

@app.route("/callback", methods=['POST'])
def callback():
    ensure_db_initialized()
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

def get_or_create_user(line_user_id):
    db = SessionLocal()
    user = db.query(User).filter(User.line_user_id == line_user_id).first()
    if not user:
        user = User(line_user_id=line_user_id)
        db.add(user)
        db.commit()
    return user, db

import yfinance as yf

def check_stock_exists(symbol):
    """
    Check stock existence using yfinance:
    Try the symbol as entered first -> Fallback to suffixing with .BK if not found
    """
    symbol = symbol.upper().strip()
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if info and ('currentPrice' in info or 'regularMarketPrice' in info):
            price = float(info.get('currentPrice') or info.get('regularMarketPrice') or 0.0)
            if price > 0:
                return symbol, price
    except Exception as e:
        print(f"[Check Stock yfinance Error] {symbol}: {e}")

    # Fallback to Thai stock check if symbol doesn't already end with .BK
    if not symbol.endswith(".BK"):
        thai_symbol = symbol + ".BK"
        print(f"[Check Stock] Trying Thai fallback for {thai_symbol}")
        try:
            ticker = yf.Ticker(thai_symbol)
            info = ticker.info
            if info and ('currentPrice' in info or 'regularMarketPrice' in info):
                price = float(info.get('currentPrice') or info.get('regularMarketPrice') or 0.0)
                if price > 0:
                    return thai_symbol, price
        except Exception as e:
            print(f"[Check Stock Thai Fallback Error] {thai_symbol}: {e}")

    return None, None


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    
    if text == "เพิ่มรายชื่อหุ้น":
        USER_STATES[user_id] = "ADD_STOCK"
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text="พิมพ์ชื่อหุ้นที่ต้องการเพิ่ม (เช่น PTT NVDA) หรือพิมพ์หลายตัวด้วยการเว้นวรรค")
        )
        return

    menu_keywords = ["ตั้งเวลา", "แสดงผล", "รายการหุ้น", "ตั้งค่า", "ผลงาน", "Setting", "Watcher"]
    if any(k in text for k in menu_keywords):
        if user_id in USER_STATES:
            del USER_STATES[user_id]
        return

    # Check State
    current_state = USER_STATES.get(user_id)

    if current_state == "ADD_STOCK":
        potential_stocks = text.split()
        confirm_flexes = []
        duplicate_list = []
        
        # Open DB once for checking
        user, db = get_or_create_user(user_id)
        
        for raw_symbol in potential_stocks:
            symbol = raw_symbol.upper()
            if len(symbol) < 2 or len(symbol) > 10:
                continue
                
            found_symbol, price = check_stock_exists(symbol)
                
            if found_symbol and price:
                # Check DB for duplicate
                exists = db.query(Watchlist).filter_by(user_id=user.id, symbol=found_symbol).first()
                if exists:
                    duplicate_list.append(found_symbol)
                else:
                    flex_content = get_add_stock_confirm_flex(found_symbol, found_symbol, price)
                    if flex_content and 'contents' in flex_content:
                        confirm_flexes.append(flex_content['contents'])
                    else:
                        print(f"[DEBUG] Flex gen failed for {found_symbol} Price: {price}")
        
        db.close()

        # Construct Reply
        msgs = []
        
        # 1. Duplicates
        if duplicate_list:
             dup_text = "! หุ้นเหล่านี้มีอยู่แล้ว: " + ", ".join(duplicate_list)
             msgs.append(TextSendMessage(text=dup_text))
        
        # 2. Carousel for new ones
        if confirm_flexes:
             if len(confirm_flexes) > 10:
                 confirm_flexes = confirm_flexes[:10]
             
             carousel = FlexSendMessage(
                 alt_text="ยืนยันการเพิ่มหุ้น",
                 contents={"type": "carousel", "contents": confirm_flexes}
             )
             msgs.append(carousel)
        
        # 3. Not found fallback
        if not confirm_flexes and not duplicate_list:
             line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"ไม่พบข้อมูลหุ้น: {text}"))
        else:
             try:
                 line_bot_api.reply_message(event.reply_token, msgs)
             except Exception as e:
                 print(f"Reply Error (Likely Timeout): {e}")

        del USER_STATES[user_id]
            
    else:
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาเลือกเมนูจากด้านล่างครับ ↓"))
        except Exception:
            pass # Suppress silent fail for expired tokens


@handler.add(PostbackEvent)
def handle_postback(event):
    # Deduplication: Ignore LINE Redeliveries
    if hasattr(event, 'delivery_context') and event.delivery_context.is_redelivery:
        print(f"[SKIP] Redelivery Postback: {event.webhook_event_id}")
        return

    data = event.postback.data
    user_id = event.source.user_id
    user, db = get_or_create_user(user_id)
    
    if user_id in USER_STATES:
        del USER_STATES[user_id]
    
    params = {}
    if data:
        for part in data.split('&'):
            if '=' in part:
                k, v = part.split('=', 1)
                params[k] = v
    
    action = params.get('action', '')
    symbol = params.get('symbol', '')

    try:
        # --- Add Stock ---
        if action == 'add_stock':
            # Check Limit (Max 10 for Carousel safety)
            count = db.query(Watchlist).filter_by(user_id=user.id).count()
            if count >= 10:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="Limit reached (Max 10 stocks). Please remove some items."))
                return

            exists = db.query(Watchlist).filter_by(user_id=user.id, symbol=symbol).first()
            if not exists:
                wl = Watchlist(user_id=user.id, symbol=symbol)
                db.add(wl)
                db.commit()
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"Confirmed: {symbol} added."))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"Info: {symbol} is already in watchlist."))
                
        elif action == 'cancel_add' or action == 'cancel':
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยกเลิกรายการแล้ว"))

        # --- Delete Stock ---
        elif (action == 'delete_stock' or action == 'delete') and symbol:
            item = db.query(Watchlist).filter_by(user_id=user.id, symbol=symbol).first()
            if item:
                db.delete(item)
                db.commit()
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"Removed: {symbol}"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ไม่พบรายการที่จะลบ"))

        # --- Settings ---
        elif (action == 'specific_setting' or action == 'settings') and symbol:
            try:
                flex = get_specific_setting_flex(symbol)
                # Fallback check for text response
                if isinstance(flex, dict) and flex.get('type') == 'text':
                     line_bot_api.reply_message(event.reply_token, TextSendMessage(text=flex['text']))
                elif flex:
                    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"Settings {symbol}", contents=flex['contents']))
            except Exception as e:
                print(f"[ERR SETTINGS Stock] {e}")
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="Error opening stock settings"))

        elif action in ['main_setting', 'global_setting', 'settings']:  # Added 'settings' for global fallback
            try:
                flex = get_global_setting_flex()
                if isinstance(flex, dict) and flex.get('type') == 'text':
                     line_bot_api.reply_message(event.reply_token, TextSendMessage(text=flex['text']))
                elif flex:
                    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="Global Settings", contents=flex['contents']))
            except Exception as e:
                print(f"[ERR SETTINGS Global] {e}")
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="Error opening global settings"))

        # --- Save Settings ---
        elif 'global' in action and 'setting' not in action:
            parts = action.split('_')
            if len(parts) >= 3:
                # Ex: global_strategy_value
                setting_group = parts[0] # global
                setting_type = parts[1] # strategy
                val_key = parts[2]      # value
                
                val_map = {
                    'dca': 'DCA', 'ai': 'AI-Auto', 'value': 'Value', 'growth': 'Growth', 
                    'dividend': 'Dividend', 'technical': 'Technical',
                    'short': 'Short', 'medium': 'Medium', 'long': 'Long',
                    'low': 'Low', 'high': 'High'
                }
                final_val = val_map.get(val_key, val_key.capitalize())
                
                if setting_type == 'strategy': user.core_strategy = final_val
                elif setting_type == 'goal': user.investment_goal = final_val
                elif setting_type == 'risk': user.risk_appetite = final_val
                
                db.commit()
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✓ Global {setting_type.capitalize()} = {final_val}"))

        elif 'stock' in action and symbol:
            parts = action.split('_')
            if len(parts) >= 3:
                # Ex: stock_strategy_value
                setting_group = parts[0] # stock
                setting_type = parts[1] # strategy
                val_key = parts[2]      # value
                
                val_map = {
                    'dca': 'DCA', 'ai': 'AI-Auto', 'value': 'Value', 'growth': 'Growth', 
                    'dividend': 'Dividend', 'technical': 'Technical',
                    'short': 'Short', 'medium': 'Medium', 'long': 'Long',
                    'low': 'Low', 'high': 'High'
                }
                final_val = val_map.get(val_key, val_key.capitalize())
                
                wl_item = db.query(Watchlist).filter_by(user_id=user.id, symbol=symbol).first()
                if wl_item:
                    if setting_type == 'strategy': wl_item.strategy = final_val
                    elif setting_type == 'goal': wl_item.goal = final_val
                    elif setting_type == 'risk': wl_item.risk = final_val
                    db.commit()
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✓ {symbol} {setting_type.capitalize()} = {final_val}"))

        elif action == 'set_time':
            flex = get_scheduler_flex()
            if flex:
                line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="Schedule", contents=flex['contents']))
                
        elif action == 'time_set':
            time_val = event.postback.params.get('time')
            if time_val:
                try:
                    dt = datetime.strptime(time_val, "%H:%M")
                    # Snap to nearest HOUR (Logic: 30-59 -> next hour, 00-29 -> this hour)
                    if dt.minute >= 30:
                        dt = dt + timedelta(hours=1)
                    
                    final_dt = dt.replace(minute=0, second=0)
                    final_time = final_dt.strftime("%H:%M")
                    
                    from database import Schedule
                    sched = db.query(Schedule).filter_by(user_id=user.id).first()
                    if not sched:
                        sched = Schedule(user_id=user.id)
                        db.add(sched)
                    
                    sched.alert_time = final_time
                    sched.is_active = True
                    db.commit()
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"ตั้งเวลาแจ้งเตือนรายวัน (ทุกชั่วโมง): {final_time}"))
                except Exception as e:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"! รูปแบบเวลาไม่ถูกต้อง"))

        elif action == 'reset_time':
             from database import Schedule
             sched = db.query(Schedule).filter_by(user_id=user.id).first()
             if sched:
                 sched.is_active = False
                 db.commit()
             line_bot_api.reply_message(event.reply_token, TextSendMessage(text="X ปิดการแจ้งเตือนแล้ว"))

        elif action == 'view_watchlist':
            items = db.query(Watchlist).filter_by(user_id=user.id).all()
            if not items:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="Watchlist ของคุณว่างเปล่า"))
            else:
                flex = get_watchlist_carousel(items)
                if flex:
                    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="Watchlist", contents=flex['contents']))

        elif action == 'get_report':
            # --- Rate Limiting Strategy ---
            current_req_time = datetime.now()
            last_req_time = USER_STATES.get(f"{user_id}_last_report")
            
            # Cooldown Period (e.g., 30 seconds to prevent double threads)
            if last_req_time and (current_req_time - last_req_time).total_seconds() < 30:
                try:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ระบบกำลังประมวลผลคำขอเก่าอยู่ กรุณารอสักครู่..."))
                except: pass
                return # Stop processing
            
            # Update Timestamp
            USER_STATES[f"{user_id}_last_report"] = current_req_time

            items = db.query(Watchlist).filter_by(user_id=user.id).all()
            if not items:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ไม่มีหุ้นในรายการ"))
            else:
                # 1. Immediate Reply (Using Token) with Time Estimation
                try:
                    # Calculate estimated time (conservative based on network latency)
                    # Global stock: ~30s (Network slow, Finnhub/TwelveData timeouts observed)
                    # Thai stock: ~15s (Login overhead)
                    # Overhead: ~20s
                    global_count = sum(1 for item in items if not item.symbol.upper().endswith('.BK'))
                    thai_count = len(items) - global_count
                    total_est_seconds = (global_count * 30) + (thai_count * 15) + 20

                    time_str = ""
                    if total_est_seconds >= 60:
                        mins = (total_est_seconds + 59) // 60 # Ceil minutes
                        time_str = f"ประมาณ {mins}-{mins+1} นาที" # Range for better expectation
                    else:
                        time_str = f"ประมาณ {total_est_seconds} วินาที"
                    
                    if global_count > 0:
                         reply_msg = f"กำลังวิเคราะห์ข้อมูล (หุ้นต่างประเทศ {global_count} ตัว อาจใช้เวลา{time_str}) กรุณารอสักครู่..."
                    else:
                         reply_msg = f"กำลังวิเคราะห์ข้อมูล (ใช้เวลา{time_str}) กรุณารอสักครู่..."

                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))
                except Exception:
                    pass 

                # 2. Fire-and-Forget Background Task
                import threading
                
                # Snapshot Data (to avoid DB DetachedInstanceError in thread)
                user_settings_snapshot = {
                    'core_strategy': user.core_strategy,
                    'investment_goal': user.investment_goal,
                    'risk_appetite': user.risk_appetite
                }
                
                safe_items = []
                for item in items:
                    safe_items.append({
                        'symbol': item.symbol, 
                        'strategy': item.strategy,
                        'goal': item.goal,
                        'risk': item.risk
                    })

                def run_analysis_safe(u_id, s_items, u_settings):
                    from services import process_stock_list
                    # Helper class for service compatibility
                    class ItemObj: pass
                    
                    final_items = []
                    for d in s_items:
                        obj = ItemObj()
                        obj.symbol = d['symbol']
                        obj.strategy = d['strategy'] or u_settings.get('core_strategy', 'Value')
                        obj.goal = d['goal'] or u_settings.get('investment_goal', 'Medium')
                        obj.risk = d['risk'] or u_settings.get('risk_appetite', 'Medium')
                        final_items.append(obj)
                    
                    def on_result(bubble):
                        try:
                            # Push immediately
                            line_bot_api.push_message(u_id, FlexSendMessage(alt_text="Analysis Result", contents=bubble))
                        except Exception as e:
                            print(f"[PUSH ERROR] {e}")

                    # Call Service
                    process_stock_list(final_items, callback_func=on_result)

                # Start Thread
                bg_thread = threading.Thread(target=run_analysis_safe, args=(user.id, safe_items, user_settings_snapshot))
                bg_thread.start()
                # Function ends here, returning 200 OK immediately to LINE

        elif action == 'our_products':
             line_bot_api.reply_message(event.reply_token, TextSendMessage(text="รอติดตามผลงานเร็วๆนี้"))

    except Exception as e:
        print(f"Postback Error: {e}")
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="! เกิดข้อผิดพลาด"))
        except Exception:
            pass # Token likely expired, ignore.
    finally:
        db.close()

@app.route("/cron/trigger", methods=['GET', 'POST'])
def cron_trigger():
    """
    Endpoint for Google Cloud Scheduler to trigger hourly checks.
    """
    ensure_db_initialized()
    print("Cron Triggered by Cloud Scheduler")
    from worker import check_jobs
    check_jobs()
    return "Cron Job Completed", 200

if __name__ == "__main__":
    import os
    from src.init_cache_db import init_db
    try:
        init_db()
    except Exception as e:
        print(f"[DB INIT ERROR] {e}")

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
