from config import Config
import logging

try:
    import google.generativeai as genai
except ImportError:
    genai = None
    print("Warning: 'google-generativeai' package not found. Please install via: pip install google-generativeai")

class LLMService:
    def __init__(self):
        self.client = None
        self.model = None
        self.model_name = Config.GEMINI_MODEL_NAME
        
        # Initialize Client (Old SDK Style)
        if Config.GEMINI_API_KEY:
             if genai:
                 try:
                     genai.configure(api_key=Config.GEMINI_API_KEY)
                     self.model = genai.GenerativeModel(self.model_name)
                     print(f"[LLM] Initialized Gemini Model: {self.model_name}")
                 except Exception as e:
                     print(f"[LLMINIT ERROR] {e}")
             else:
                 print("Warning: google-generativeai library is missing.")
        else:
            print("Warning: GEMINI_API_KEY not found in environment.")

    def _call_gemini(self, prompt):
        if not self.model:
            return "AI Service Not Configured."
        try:
            # Old SDK Call Structure with Lower Temperature for Consistency
            config = genai.types.GenerationConfig(temperature=0.1)
            response = self.model.generate_content(prompt, generation_config=config)
            if response and response.text:
                return response.text.strip()
            return "No response from AI."
        except Exception as e:
            return f"AI Connection Error: {str(e)}"

    def analyze_stock_ai(self, symbol, price, pe_ratio, div_yield, news_list, strategy="General", goal="Medium", technicals=None):
        """
        One-Shot Analysis: News Summary + Financial Analysis + Signal Generation in 1 call.
        """
        
        # Handling News List
        news_context = "No news found."
        if news_list:
            news_context = "\n- ".join(news_list[:3]) # Top 3 headlines
            
        # Robust Missing Data Handling
        pe_str = str(pe_ratio)
        dy_str = str(div_yield)
        missing_note = ""
        if pe_str in ["0", "0.0", "N/A", "None", "None.00"] or not pe_ratio:
            pe_str = "N/A (Ignore P/E)"
            missing_note += " P/E is missing."
        if dy_str in ["0", "0.0", "N/A", "None", "None.00"] or not div_yield:
            dy_str = "N/A (Ignore Yield)"
            missing_note += " Yield is missing."

        # Build Technical Context
        tech_context = ""
        if technicals:
            tech_context = (
                f"Technical Indicators:\n"
                f"- RSI (14): {technicals.get('rsi', 'N/A')}\n"
                f"- SMA (50): {technicals.get('sma50', 'N/A')}\n"
                f"- Market Cap: {technicals.get('market_cap', 'N/A')}\n"
                f"- 52W Range: {technicals.get('year_low', 'N/A')} - {technicals.get('year_high', 'N/A')}\n"
            )

        prompt = (
            f"Analyze stock {symbol} for Strategy: '{strategy}' (Goal: '{goal}').\n"
            f"Current Price: {price}, P/E: {pe_str}, Yield: {dy_str}%\n"
            f"{tech_context}\n"
            f"Recent News Headlines:\n{news_context}\n\n"
            "TASK: Perform holistic analysis and return the result in EXACTLY this format:\n"
            "SIGNAL | REASON | NEWS_SUMMARY\n\n"
            "RULES:\n"
            "1. SIGNAL: Choose from [BUY, SELL, HOLD, WAIT].\n"
            "2. REASON: Explain the analytical reasoning (Thai, 1 concise sentence).\n"
            "3. NEWS_SUMMARY: Summarize the provided news/headlines. If specific news is missing, use global context (Thai, 2-3 sentences).\n"
            f"4. Focus context on '{strategy}' strategy and '{goal}' goal.\n"
            "5. If absolutely NO news provided, set NEWS_SUMMARY to 'ไม่มีข่าวที่เกี่ยวข้อง'.\n"
            "6. Output MUST start with the SIGNAL.\n"
            "\nExample: HOLD | ราคายังทรงตัวเหนือแนวรับสำคัญ แต่ RSI เข้าใกล้เขต Overbought | ข่าวในช่วงนี้เน้นไปที่การประกาศกำไรที่ทรงตัวตามคาด แต่มีปัจจัยลบจากดอกเบี้ย"
        )
        
        return self._call_gemini(prompt)

    def summarize_news(self, news_list):
        if not news_list:
            return "ไม่มีข่าวสารสำคัญในช่วงนี้"
            
        # Limit to top 3 news for speed context window efficiency
        combined_news = "\n- ".join(news_list[:3])
        
        prompt = (
            f"Summarize these stock news headlines into a concise Thai paragraph.\n"
            f"Headlines:\n{combined_news}\n\n"
            f"Requirements:\n"
            f"1. Translate and summarize the key points into Thai language ONLY.\n"
            f"2. Strictly limit to 2-3 sentences maximum (under 250 characters).\n"
            f"3. Focus on market impact (Positive/Negative).\n"
            f"Thai Summary:"
        )
        
        return self._call_gemini(prompt)
