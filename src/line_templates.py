import json
import os
import urllib.parse
import copy
from config import Config

# Robust Path Detection for line_ux
# Standard Path using Config
try:
    TEMPLATE_DIR = os.path.join(Config.BASE_DIR, 'line_ux')
except:
    TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'line_ux')

if not os.path.exists(TEMPLATE_DIR):
    print(f"[TEMPLATE SYSTEM] CRITICAL: line_ux NOT FOUND at {TEMPLATE_DIR}")
else:
    print(f"[TEMPLATE SYSTEM] Found line_ux at: {TEMPLATE_DIR}")

def load_template(filename):
    if not TEMPLATE_DIR:
        print("[TEMPLATE ERROR] Template directory not initialized.")
        return None
    path = os.path.join(TEMPLATE_DIR, filename)
    if not os.path.exists(path):
        print(f"[TEMPLATE ERROR] File not found: {path} (Checked in {TEMPLATE_DIR})") 
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # print(f"[TEMPLATE SUCCESS] Loaded {filename} keys: {list(data.keys()) if isinstance(data, dict) else 'List'}")
            return data
    except json.JSONDecodeError as e:
        print(f"[TEMPLATE JSON ERROR] {filename}: {e}") 
        return None
    except Exception as e:
        print(f"[TEMPLATE LOAD ERROR] {filename}: {e}")
        return None

def _replace_recursive(obj, replacements):
    """
    Recursively replace string values. Supports matches for 'KEY' and '${KEY}'.
    """
    if isinstance(obj, dict):
        return {k: _replace_recursive(v, replacements) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_replace_recursive(i, replacements) for i in obj]
    elif isinstance(obj, str):
        # Scan for keys in replacements
        new_str = obj
        for key, val in replacements.items():
            s_val = str(val)
            # Try Direct Match
            if key in new_str:
                new_str = new_str.replace(key, s_val)
            # Try ${KEY} Match
            place_key = f"${{{key}}}"
            if place_key in new_str:
                new_str = new_str.replace(place_key, s_val)
        return new_str
    return obj

def get_add_stock_confirm_flex(symbol, company_name, price):
    price_fmt = "N/A"
    try:
        val = float(price)
        price_fmt = f"{val:,.2f}"
    except:
        price_fmt = str(price)

    template = load_template("add.json")
    if template:
        img_url = "https://cdn-icons-png.flaticon.com/512/217/217853.png" #Fallback
        replacements = {
            "Stock_Name": str(symbol),
            "company_name": str(company_name or symbol),
            "current_price": price_fmt,
            "img_url": img_url
        }
        bubble = _replace_recursive(template, replacements)
        return {"type": "flex", "altText": f"Confirm Add {symbol}", "contents": bubble}
    
    # Critical Fallback Only (Should not happen if JSON exists)
    return None

def get_watchlist_carousel(stocks):
    """
    Constructs Watchlist using watch_list.json base and Python loop for rows.
    Style: White Card, Grey Setting Button, Red Delete Button.
    """
    base_template = load_template("watch_list.json")
    if not base_template: return None

    list_items = []
    for stock in stocks:
        symbol = stock.symbol
        company = getattr(stock, 'company_name', symbol) or symbol
        
        # Row Item (Constructed in Code)
        row = {
            "type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm",
            "contents": [
                # Symbol Title
                {
                    "type": "text", "text": str(symbol), "size": "xl", "weight": "bold", "color": "#000000"
                },
                # Company Name (Small Grey)
                {
                    "type": "text", "text": str(company), "size": "xs", "color": "#aaaaaa", "margin": "none"
                },
                # Buttons
                {
                    "type": "button", "action": {"type": "postback", "label": "⚙ Specific Setting", "data": f"action=settings&symbol={symbol}"}, 
                    "style": "secondary", "height": "sm", "color": "#F0F2F5", "margin": "md"
                },
                {
                    "type": "button", "action": {"type": "postback", "label": "Delete", "data": f"action=confirm_delete&symbol={symbol}", "displayText": f"ยืนยันการลบ {symbol}"}, 
                    "style": "primary", "height": "sm", "color": "#ff4444", "margin": "sm"
                },
                {"type": "separator", "margin": "lg"}
            ]
        }
        list_items.append(row)

    # Pagination Logic
    MAX_ITEMS = 5 # Fewer items per bubble because rows are tall
    chunks = [list_items[i:i + MAX_ITEMS] for i in range(0, len(list_items), MAX_ITEMS)]
    
    bubbles = []
    for chunk in chunks:
        # Remove separator from last item in chunk
        if chunk and chunk[-1]['contents'][-1]['type'] == 'separator':
             chunk[-1]['contents'].pop()

        import copy
        bubble = copy.deepcopy(base_template)
        
        # Replace Count Header
        if "header" in bubble and "contents" in bubble["header"]:
             for item in bubble["header"]["contents"]:
                 if "text" in item and "COUNT_STOCKS" in item["text"]:
                     item["text"] = item["text"].replace("COUNT_STOCKS", str(len(stocks)))

        # Inject Rows into Body
        if "body" in bubble:
            bubble["body"]["contents"] = chunk
            
        bubbles.append(bubble)

    if not bubbles: return None
        
    if len(bubbles) == 1:
        return {"type": "flex", "altText": "My Watchlist", "contents": bubbles[0]}
    else:
        return {"type": "flex", "altText": "My Watchlist", "contents": {"type": "carousel", "contents": bubbles}}

def get_global_setting_flex():
    template = load_template("carousel_setting_global.json")
    if template:
        return {"type": "flex", "altText": "Global Settings", "contents": template}
    return None

def get_specific_setting_flex(symbol):
    template = load_template("carousel_setting_stock.json")
    if template:
        replacements = {"stock_name": str(symbol), "Stock_Name": str(symbol)}
        return {"type": "flex", "altText": f"Settings {symbol}", "contents": _replace_recursive(template, replacements)}
    return None

def get_scheduler_flex():
    template = load_template("scheduler.json")
    if template:
        return {"type": "flex", "altText": "Scheduler", "contents": template}
    return None

def get_analysis_flex(symbol, signal, recommendation, details):

    template = load_template("analysis.json")
    
    color_map = {
        "POSITIVE": "#16803c", "NEUTRAL": "#8a6100", "CAUTIOUS": "#b42318",
        "BUY": "#1DB446", "SELL": "#ff4444", "HOLD": "#ffbb33", "WAIT": "#33b5e5", "ERROR": "#000000",
    }
    signal_color = color_map.get(str(signal).upper(), "#000000")
    
    def safe_get(key, fmt="{:.2f}"):
        val = details.get(key)
        if val is None or val == "" or val == "N/A": return "-"
        try:
            if isinstance(val, (int, float)):
                return fmt.format(val)
            f_val = float(str(val).replace(',', ''))
            return fmt.format(f_val)
        except:
            return str(val)

    price = safe_get("price", "{:,.2f}")
    pe = safe_get("pe_ratio", "{:.2f}")
    
    yd_val = details.get("div_yield")
    yd = f"{yd_val:.2f}%" if yd_val is not None and isinstance(yd_val, (int, float)) else "-"
    
    rsi = details.get("technicals", {}).get("rsi") or "-"
    sma = details.get("technicals", {}).get("sma50") or "-"
    
    mkt_val = details.get("technicals", {}).get("market_cap")
    mkt = str(mkt_val) if mkt_val and mkt_val != "N/A" else "-"
    
    yh = details.get("technicals", {}).get("year_high") or "-"
    yl = details.get("technicals", {}).get("year_low") or "-"
    
    hist = details.get('history', [])
    chart_url = "" 
    if hist and len(hist) > 1:
        data_points = hist[-20:]
        chart_data = ",".join([str(round(p,1)) for p in data_points])
        
        chart_config = {
            "type": "line",
            "data": {
                "labels": [""] * len(data_points),
                "datasets": [{
                    "data": [float(x) for x in chart_data.split(',')],
                    "borderColor": "#8854d0",
                    "borderWidth": 2,
                    "fill": False,
                    "pointRadius": 0
                }]
            },
            "options": {
                "legend": {"display": False},
                "scales": {
                    "xAxes": [{"display": False}],
                    "yAxes": [{"display": False}]
                }
            }
        }
        
        try:
            import json
            chart_json = json.dumps(chart_config)
            chart_encoded = urllib.parse.quote(chart_json)
            chart_url = f"https://quickchart.io/chart?c={chart_encoded}&w=300&h=150&bkg=transparent"
        except ImportError:
            pass

    news_sum = details.get('news_summary')
    news_raw = details.get('news', [])
    
    if news_sum and news_sum != "-" and news_sum != "":
        news_text = news_sum
    elif news_raw and len(news_raw) > 0:
        news_text = news_raw[0]
    else:
        news_text = "ไม่มีข่าวสำคัญในช่วงนี้"
    
    if len(news_text) > 140: news_text = news_text[:137] + "..."

    risks = details.get('risks') or []
    risk_text = " | ".join(str(item) for item in risks[:2]) if risks else "ควรพิจารณาความเสี่ยงและข้อมูลล่าสุดก่อนตัดสินใจ"
    if len(risk_text) > 160: risk_text = risk_text[:157] + "..."
    updated_at = str(details.get('updated_at') or "ข้อมูลล่าสุด")[:19].replace('T', ' ')
    confidence = str(details.get('confidence') or "Medium")

    # Footer Link Logic
    is_thai = ".BK" in str(symbol).upper()
    link_uri = f"https://www.settrade.com/th/equities/quote/{str(symbol).replace('.BK','')}/overview" if is_thai else f"https://finance.yahoo.com/quote/{symbol}"

    replacements = {
        "STOCK_SYMBOL": str(symbol),
        "SIGNAL_TEXT": str(signal),
        "SIGNAL_COLOR": signal_color,
        "RECOMMENDATION_TEXT": str(recommendation),
        "CHART_URL": chart_url,
        "VAL_PRICE": str(price),
        "VAL_PE": str(pe),
        "VAL_YIELD": str(yd),
        "VAL_RSI": str(rsi),
        "VAL_SMA": str(sma),
        "VAL_MKT": str(mkt),
        "VAL_YH": str(yh),
        "VAL_YL": str(yl),
        "NEWS_TEXT": str(news_text), 
        "RISK_TEXT": risk_text,
        "UPDATED_AT": updated_at,
        "CONFIDENCE": confidence,
        "LINK_URI": link_uri
    }

    if template:
        payload = copy.deepcopy(template)
    else:
        return None

    # Remove Hero (Model Graph Section in Body instead)
    if "hero" in payload: del payload["hero"]

    # Add Graph Section to Body (Separator -> Header -> Image -> Separator)
    if chart_url and chart_url != "":
        graph_section = [
            {"type": "separator", "margin": "lg", "color": "#DDDDDD"},
            {"type": "text", "text": "📈 30-Day Trend", "size": "xs", "weight": "bold", "color": "#888888", "margin": "sm", "align": "center"},
            {"type": "image", "url": chart_url, "size": "full", "aspectRatio": "2:1", "aspectMode": "fit", "margin": "md"},
            {"type": "separator", "margin": "lg", "color": "#DDDDDD"},
        ]
        
        # Safe Insert: Check if body exists
        if "body" in payload and "contents" in payload["body"]:
             # Insert after the first few items (Title/Price) or at the bottom if safer
             # Let's insert BEFORE the metrics box (usually index 2 or 3)
             # Better strategy: Append to the main list but before Footer? 
             # No, let's Put it at Index 1 (After Title)
             
             # Find index of the main details box?
             # Simplest: Insert at Index 2
             target_idx = 2
             if len(payload["body"]["contents"]) < 2: target_idx = len(payload["body"]["contents"])
             
             for item in reversed(graph_section):
                 payload["body"]["contents"].insert(target_idx, item)

    # Final Recursive Replace and Return (Always execute)
    final_content = _replace_recursive(payload, replacements)
    return {"type": "flex", "altText": f"Analysis {symbol}", "contents": final_content}
