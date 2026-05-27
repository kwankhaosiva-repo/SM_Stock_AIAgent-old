import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from global_stock_helper import get_market_news, get_general_market_news
from analyzer import AnalysisEngine

def test_news():
    print("Testing PTT News...")
    ptt_news = get_market_news("PTT.BK")
    for idx, n in enumerate(ptt_news):
        print(f"{idx+1}. {n['headline']} ({n['summary']})")
        
    print("\nTesting General Market News...")
    gen_news = get_general_market_news()
    for idx, n in enumerate(gen_news):
        print(f"{idx+1}. {n['headline']} ({n['summary']})")

def test_analysis():
    print("\nTesting AnalysisEngine...")
    engine = AnalysisEngine()
    result = engine.analyze("PTT.BK", "Value", "Medium", "Medium")
    print("\n--- ANALYSIS RESULT ---")
    print(f"Signal: {result.get('signal')}")
    print(f"Reason: {result.get('reason')}")
    print(f"News Summary: {result.get('news_summary')}")

if __name__ == "__main__":
    test_news()
    # Assuming valid API key is in .env, otherwise analysis might return mock or error
    test_analysis()
