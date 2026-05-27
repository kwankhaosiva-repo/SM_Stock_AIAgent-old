import yfinance as yf
import pandas as pd
import logging

class SettradeHelper:
    def __init__(self):
        pass

    def get_quote(self, symbol):
        """ Get Realtime Quote from yfinance """
        try:
            # Clean Symbol
            symbol = symbol.upper().replace(".BK", "").strip() + ".BK"
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            if not info or ('currentPrice' not in info and 'regularMarketPrice' not in info):
                # Try history fallback in case info fails
                history_df = ticker.history(period="2d")
                if history_df.empty:
                    return None
                price = float(history_df['Close'].iloc[-1])
                prev_close = float(history_df['Close'].iloc[-2]) if len(history_df) > 1 else price
                high = float(history_df['High'].max())
                low = float(history_df['Low'].min())
                vol = float(history_df['Volume'].iloc[-1])
                pe = 0.0
                pbv = 0.0
                yd = 0.0
            else:
                price = float(info.get('currentPrice') or info.get('regularMarketPrice') or 0.0)
                prev_close = float(info.get('previousClose') or price)
                high = float(info.get('dayHigh') or price)
                low = float(info.get('dayLow') or price)
                vol = float(info.get('volume') or 0.0)
                pe = float(info.get('trailingPE') or 0.0)
                pbv = float(info.get('priceToBook') or 0.0)
                yd = float(info.get('dividendYield') or 0.0)
            
            change = price - prev_close
            percent_change = (change / prev_close) * 100 if prev_close else 0.0
            
            return {
                "price": price,
                "change": change,
                "percent_change": percent_change,
                "high": high,
                "low": low,
                "vol": vol,
                "val": vol * price,
                "pe": pe,
                "pbv": pbv,
                "yield": yd
            }
        except Exception as e:
            print(f"[YFINANCE THAI QUOTE ERROR] {symbol}: {e}")
            return None

    def get_candles(self, symbol, interval='1d', limit=60):
        """ Get Historical Candles """
        try:
            symbol = symbol.upper().replace(".BK", "").strip() + ".BK"
            ticker = yf.Ticker(symbol)
            
            # Map intervals
            y_interval = "1d"
            if interval == '1m': y_interval = '1m'
            elif interval == '5m': y_interval = '5m'
            elif interval == '15m': y_interval = '15m'
            elif interval == '30m': y_interval = '30m'
            elif interval == '1h': y_interval = '1h'
            elif interval == '1d': y_interval = '1d'
            elif interval == '1wk': y_interval = '1wk'
            elif interval == '1mo': y_interval = '1mo'
            
            history_df = ticker.history(period=f"{limit * 2}d", interval=y_interval)
            if history_df.empty:
                return None
                
            history_df = history_df.tail(limit)
            
            # Format time index to match string format
            time_list = [t.strftime('%Y-%m-%d %H:%M:%S') for t in history_df.index]
            
            return {
                "time": time_list,
                "close": [float(x) for x in history_df['Close'].tolist()],
                "high": [float(x) for x in history_df['High'].tolist()],
                "low": [float(x) for x in history_df['Low'].tolist()]
            }
        except Exception as e:
            print(f"[YFINANCE THAI CANDLES ERROR] {symbol}: {e}")
            return None

def get_thai_stock_data(symbol):
    helper = SettradeHelper()
    
    # 1. Get Quote (Realtime)
    quote = helper.get_quote(symbol)
    if not quote: return None
    
    # 2. Get History (Candles)
    history = []
    candles = helper.get_candles(symbol, interval='1d', limit=60)
    if candles and candles['close']:
        history = candles['close']
        
    # Merge History into result
    quote['history'] = history
    
    return quote
