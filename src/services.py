import time
from analyzer import AnalysisEngine
from line_templates import get_analysis_flex

# Shared Analyzer Instance (Singleton-ish)
_analyzer = AnalysisEngine()

def process_stock_list(stocks, callback_func=None):
    """
    Centralized logic to process a list of stocks.
    Handles:
    - Iteration
    - Analysis
    - Rate Limiting (Sleep)
    - Formatting (Flex Bubble)
    
    Args:
        stocks: List of stock objects (must have .symbol attribute) or strings.
        callback_func: Optional function to call with the generated Flex Bubble immediately.
                       Useful for app.py needing immediate feedback.
                       
    Returns:
        List of generated Flex Bubbles (for batch sending like in worker.py).
    """
    flex_bubbles = []
    total_items = len(stocks)
    
    for index, item in enumerate(stocks):
        # Handle both object (Watchlist) and string input
        symbol = item.symbol if hasattr(item, 'symbol') else str(item)
        
        # Strategy/Goal extraction (if available on item)
        strategy = getattr(item, 'strategy', 'Value')
        goal = getattr(item, 'goal', 'Medium')
        risk = getattr(item, 'risk', 'Medium')

        print(f"[SERVICE] Processing {symbol} ({index+1}/{total_items})...")
        
        try:
            # 1. Analyze
            analysis_result = _analyzer.analyze(symbol, strategy=strategy, goal=goal, risk=risk)
            
            if analysis_result:
                # 2. Data Prep for Template
                details = analysis_result.get('metrics', {}).copy()
                details['history'] = analysis_result.get('history', [])
                details['news'] = analysis_result.get('news', [])
                details['technicals'] = analysis_result.get('technicals', {})
                details['news_summary'] = analysis_result.get('news_summary', '-')

                # 3. Generate Flex
                flex = get_analysis_flex(
                    symbol=analysis_result['symbol'],
                    signal=analysis_result['signal'],
                    recommendation=analysis_result['reason'],
                    details=details
                )
                
                if flex and 'contents' in flex:
                    bubble = flex['contents']
                    flex_bubbles.append(bubble)
                    
                    # Immediate Callback (used by app.py)
                    if callback_func:
                        callback_func(bubble)

        except Exception as e:
            print(f"[SERVICE ERROR] Failed to process {symbol}: {e}")
            # Generate Error Flex Bubble so user knows something went wrong
            try:
                err_flex = get_analysis_flex(symbol, "ERROR", f"เกิดข้อผิดพลาด: {str(e)[:50]}", {})
                if err_flex and 'contents' in err_flex:
                    bubble = err_flex['contents']
                    flex_bubbles.append(bubble)
                    
                    if callback_func:
                        callback_func(bubble)
            except: pass

        # 4. Rate Limit Logic (The crucial shared part)
        if index < total_items - 1:
            time.sleep(1) # Sleep 1s to be polite to Yahoo Finance
                
    return flex_bubbles
