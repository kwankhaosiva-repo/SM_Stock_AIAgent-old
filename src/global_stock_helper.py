import time
import datetime
import yfinance as yf
import pandas as pd
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

try:
    from init_cache_db import GlobalStockInfo
except ImportError:
    from src.init_cache_db import GlobalStockInfo
try:
    from config import Config
except ImportError:
    from src.config import Config

# DB Setup for Cache
try:
    from database import SessionLocal
except ImportError:
    from src.database import SessionLocal

# --- PUBLIC FUNCTIONS (yfinance implementation) ---

def get_quote(symbol):
    """ Get Realtime Price from yfinance """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if not info or ('currentPrice' not in info and 'regularMarketPrice' not in info):
            # Try history fallback
            history_df = ticker.history(period="2d")
            if history_df.empty:
                return None
            price = float(history_df['Close'].iloc[-1])
            prev_close = float(history_df['Close'].iloc[-2]) if len(history_df) > 1 else price
            change = price - prev_close
            pct_change = (change / prev_close) * 100 if prev_close else 0.0
            
            return {
                "c": price,
                "d": change,
                "dp": pct_change,
                "h": float(history_df['High'].max()),
                "l": float(history_df['Low'].min()),
                "o": float(history_df['Open'].iloc[-1]),
                "pc": prev_close,
                "name": symbol
            }
            
        price = float(info.get('currentPrice') or info.get('regularMarketPrice') or 0.0)
        prev_close = float(info.get('previousClose') or price)
        change = price - prev_close
        pct_change = (change / prev_close) * 100 if prev_close else 0.0
        
        return {
            "c": price,
            "d": change,
            "dp": pct_change,
            "h": float(info.get('dayHigh') or price),
            "l": float(info.get('dayLow') or price),
            "o": float(info.get('open') or price),
            "pc": prev_close,
            "name": info.get('shortName') or info.get('longName') or symbol
        }
    except Exception as e:
        print(f"[YFINANCE GLOBAL QUOTE ERROR] {symbol}: {e}")
        return None

def get_company_profile(symbol):
    """ Get Profile from Cache first, then yfinance. """
    session = SessionLocal()
    cached = None
    try:
        # 1. Check Cache
        cached = session.query(GlobalStockInfo).filter_by(symbol=symbol).first()
        if cached:
            now = datetime.datetime.utcnow()
            age = (now - cached.updated_at).days
            
            # Return cache if fresh and valid
            if age < 1 and (str(cached.pe_ratio) != '0.0' and cached.pe_ratio != 0):
                print(f"[CACHE HIT] Profile for {symbol} (Age: {age} days)")
                return {
                    "pe": cached.pe_ratio,
                    "marketCapitalization": float(cached.market_cap) if cached.market_cap and cached.market_cap != 'N/A' else 0,
                    "dividendYield": cached.dividend_yield,
                    "name": cached.company_name
                }
            
            if age < 1:
                print(f"[CACHE HIT-BUT-INVALID] Profile for {symbol} (Age: {age} days) has P/E=0. Refetching...")

        # 2. Fetch yfinance
        print(f"[CACHE MISS] Fetching Profile for {symbol} from yfinance...")
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        if info:
            pe = float(info.get('trailingPE') or info.get('forwardPE') or 0.0)
            cap = float(info.get('marketCap') or 0.0) / 1000000.0
            yd = float(info.get('dividendYield') or 0.0)
            name = info.get('shortName') or info.get('longName') or symbol
            
            # 3. Save to Cache
            if cached:
                cached.pe_ratio = pe
                cached.market_cap = str(cap)
                cached.dividend_yield = yd
                cached.company_name = name
                cached.updated_at = datetime.datetime.utcnow()
            else:
                new_entry = GlobalStockInfo(
                    symbol=symbol,
                    company_name=name,
                    pe_ratio=pe,
                    market_cap=str(cap),
                    dividend_yield=yd
                )
                session.add(new_entry)
            
            session.commit()
            
            return {
                "pe": pe,
                "marketCapitalization": cap,
                "dividendYield": yd,
                "name": name
            }
        else:
            # Fallback to cache if yfinance fails
            if cached:
                print(f"[CACHE FALLBACK] Using old data for {symbol}")
                return {
                    "pe": cached.pe_ratio,
                    "marketCapitalization": float(cached.market_cap) if cached.market_cap and cached.market_cap != 'N/A' else 0,
                    "dividendYield": cached.dividend_yield,
                    "name": cached.company_name
                }
            return {}

    except Exception as e:
        print(f"[CACHE ERROR] {e}")
        # Fallback to cache on error
        if cached:
            return {
                "pe": cached.pe_ratio,
                "marketCapitalization": float(cached.market_cap) if cached.market_cap and cached.market_cap != 'N/A' else 0,
                "dividendYield": cached.dividend_yield,
                "name": cached.company_name
            }
        return {}
    finally:
        session.close()

def get_market_news(symbol):
    """ Get News from Google News RSS in Thai """
    try:
        # Resolve Thai stock suffix if it has .BK
        display_symbol = symbol.replace('.BK', '')
        query = urllib.parse.quote(f"{display_symbol} หุ้น")
        url = f"https://news.google.com/rss/search?q={query}&hl=th&gl=TH&ceid=TH:th"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=10)
        xml_data = response.read()
        root = ET.fromstring(xml_data)
        
        news_items = []
        for item in root.findall('.//item')[:3]:  # Top 3 news items
            title = item.find('title')
            link = item.find('link')
            pub_date = item.find('pubDate')
            
            if title is not None:
                news_items.append({
                    "headline": title.text,
                    "summary": f"เผยแพร่เมื่อ: {pub_date.text}" if pub_date is not None else "",
                    "url": link.text if link is not None else ""
                })
        return news_items
    except Exception as e:
        print(f"[GOOGLE NEWS RSS ERROR] {symbol}: {e}")
        return []

def get_candles_and_indicators(symbol):
    """ Get Candles from yfinance and calculate indicators manually """
    try:
        ticker = yf.Ticker(symbol)
        history_df = ticker.history(period="60d")
        if history_df.empty:
            return None

        closes = history_df['Close'].tolist()
        highs = history_df['High'].tolist()
        lows = history_df['Low'].tolist()

        # Calculate Indicators
        series = pd.Series(closes)

        # SMA 50
        sma50 = "N/A"
        if len(series) >= 50:
            val = series.rolling(window=50).mean().iloc[-1]
            sma50 = f"{val:.2f}"
            
        # RSI 14
        rsi = "N/A"
        if len(series) >= 14:
            delta = series.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi_val = 100 - (100 / (1 + rs))
            rsi = f"{rsi_val.iloc[-1]:.2f}"

        return {
            "history": closes, 
            "technicals": {
                "rsi": rsi,
                "sma50": sma50,
                "year_high": f"{max(highs):.2f}" if highs else "-",
                "year_low": f"{min(lows):.2f}" if lows else "-",
                "market_cap": "N/A"
            }
        }
    except Exception as e:
        print(f"[INDICATOR ERROR] {symbol}: {e}")
        return None

def get_general_market_news():
    """ Get General Market News from Google News RSS """
    try:
        query = urllib.parse.quote("ตลาดหุ้นไทย")
        url = f"https://news.google.com/rss/search?q={query}&hl=th&gl=TH&ceid=TH:th"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=10)
        xml_data = response.read()
        root = ET.fromstring(xml_data)
        
        news_items = []
        for item in root.findall('.//item')[:3]:
            title = item.find('title')
            link = item.find('link')
            pub_date = item.find('pubDate')
            
            if title is not None:
                news_items.append({
                    "headline": title.text,
                    "summary": f"เผยแพร่เมื่อ: {pub_date.text}" if pub_date is not None else "",
                    "url": link.text if link is not None else ""
                })
        return news_items
    except Exception as e:
        print(f"[GOOGLE NEWS RSS ERROR] General Market: {e}")
        return []
