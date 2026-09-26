import os
from pathlib import Path
from dotenv import load_dotenv

# Use Pathlib for robustness (Cross-platform & Cloud Run Safe)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, ".env"))

# --- ENV_FILE from Secret Manager -------------------------------------------
# If the whole .env file was uploaded to Secret Manager (e.g. secret name
# 'env_stocks') and mapped to a container env var, parse it here so every
# key inside becomes a normal environment variable.
for _env_file_var in ('ENV_FILE', 'ENV_STOCKS', 'env_stocks'):
    _env_file_content = os.environ.get(_env_file_var, '')
    if _env_file_content and '=' in _env_file_content:
        for _line in _env_file_content.splitlines():
            _line = _line.strip()
            if not _line or _line.startswith('#') or '=' not in _line:
                continue
            _key, _, _val = _line.partition('=')
            _key = _key.strip()
            _val = _val.strip().strip('"').strip("'")
            if _key:
                os.environ.setdefault(_key, _val)
        break

class Config:
    # Point to Project Root
    BASE_DIR = str(BASE_DIR)
    
    # Database — DATABASE_URL หรือ POSTGRES_URL (ชื่อใน .env ของ user)
    DATABASE_URL = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
    
    # Cloud Run (Postgres) vs Local (SQLite) Logic
    if DATABASE_URL and 'postgres' in DATABASE_URL:
        # Fix for SQLAlchemy requiring 'postgresql://' instead of 'postgres://'
        if DATABASE_URL.startswith("postgres://"):
            DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+pg8000://", 1)
        elif not DATABASE_URL.startswith("postgresql+pg8000://"):
             # Ensure driver is present if not specified
             DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+pg8000://", 1)
    else:
        # Fallback to Local SQLite
        db_path = os.path.join(BASE_DIR, 'app.db')
        DATABASE_URL = f"sqlite:///{db_path}"
        print(f"[CONFIG] Warning: DATABASE_URL not found. Using Local SQLite: {DATABASE_URL}")

    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    print(f"[CONFIG] DB Configured: {SQLALCHEMY_DATABASE_URI.split('@')[-1]}")

    # Line API
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_ACCESS_TOKEN')
    LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')

    # Finnhub API
    FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
    TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

    # Settrade Open API (Thai Stocks, official feed)
    SETTRADE_APP_ID = os.getenv('SETTRADE_APP_ID', '')
    SETTRADE_APP_SECRET = os.getenv('SETTRADE_APP_SECRET', '')
    SETTRADE_BROKER_ID = os.getenv('SETTRADE_BROKER_ID', '098')
    SETTRADE_APP_CODE = os.getenv('SETTRADE_APP_CODE', 'SANDBOX')
    SETTRADE_IS_SANDBOX = os.getenv('SETTRADE_IS_SANDBOX', 'true').lower() == 'true'

    # Financial Modeling Prep (balance-sheet fallback when Yahoo blocks)
    FMP_API_KEY = os.getenv('FMP_API_KEY', '')

    # Optional local data relay (Cloudflare Tunnel URL of the home agent)
    DATA_RELAY_URL = os.getenv('DATA_RELAY_URL', '')

    # LLM Settings (single primary provider)
    # รองรับชื่อย่อจาก .env ของ user (GEMINI_API) และชื่อเต็ม (GEMINI_API_KEY)
    # Gemini direct API (AI Studio) — ปิดไว้ก่อนเนื่องจากต้องผูกบัตร/billing (402)
    # จะเปิดใช้ค่อย uncomment บรรทัดด้านล่าง (model Gemini ผ่าน UnoRouter ยังใช้ได้ปกติ)
    # GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') or os.getenv('GEMINI_API', '')
    GEMINI_API_KEY = ''  # disabled
    GEMINI_MODEL_NAME = os.getenv('GEMINI_MODEL_NAME', 'gemini-flash-latest')

    # Multi-provider free-tier failover chain. Providers without keys are
    # skipped; on failure the SAME prompt + context goes to the next one.
    GROQ_API_KEY = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_API', '')
    # llama-3.3-70b-versatile ถูก Groq ปลดออกแล้ว — ใช้ llama-3.1-8b-instant (เสถียร)
    # ถ้าโมเดลที่ตั้งไม่มีแล้ว provider จะดึง /models มาเลือกอัตโนมัติ (ดู llm_providers)
    GROQ_MODEL_NAME = os.getenv('GROQ_MODEL_NAME', 'llama-3.1-8b-instant')
    CEREBRAS_API_KEY = os.getenv('CEREBRAS_API_KEY', '')
    CEREBRAS_MODEL_NAME = os.getenv('CEREBRAS_MODEL_NAME', 'llama-3.3-70b')
    MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY') or os.getenv('MISTRAL_API', '')
    MISTRAL_MODEL_NAME = os.getenv('MISTRAL_MODEL_NAME', 'mistral-small-latest')
    CLOUDFLARE_API_KEY = os.getenv('CLOUDFLARE_API_KEY') or os.getenv('CLOUDFLARE_API', '')
    CLOUDFLARE_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
    CLOUDFLARE_MODEL_NAME = os.getenv('CLOUDFLARE_MODEL_NAME', 'meta/llama-3.1-8b-instruct')
    # OpenRouter — free models available via ":free" suffix
    OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY') or os.getenv('OPENROUTER_API', '')
    OPENROUTER_MODEL_NAME = os.getenv(
        # Llama 3.3 ถูกดึงออกจาก free tier ของ OpenRouter แล้ว — ใช้ DeepSeek free
        'OPENROUTER_MODEL_NAME', 'deepseek/deepseek-chat-v3.1:free'
    )
    # UnoRouter — hosted OpenAI-compatible gateway (unorouter.com)
    UNOROUTER_API_KEY = os.getenv('UNOROUTER_API_KEY') or os.getenv('UNOROUTER_API', '')
    UNOROUTER_BASE_URL = os.getenv('UNOROUTER_BASE_URL', 'https://api.unorouter.com/v1')
    # UnoRouter ใช้ slug สไตล์ OpenRouter (เช่น google/gemini-3-flash:free)
    UNOROUTER_MODEL_NAME = os.getenv('UNOROUTER_MODEL_NAME', 'google/gemini-3-flash:free')
    # 9Router — local proxy (http://localhost:20128/v1), auto-fallback 40+ providers
    ROUTER9_BASE_URL = os.getenv('ROUTER9_BASE_URL', '')
    ROUTER9_API_KEY = os.getenv('ROUTER9_API_KEY', '')
    ROUTER9_MODEL_NAME = os.getenv('ROUTER9_MODEL_NAME', 'auto')
    OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
    OLLAMA_MODEL_NAME = os.getenv('OLLAMA_MODEL_NAME', 'mistral-small3.2:24b')
    LLM_PROVIDER_ORDER = os.getenv(
        'LLM_PROVIDER_ORDER',
        # gemini (direct API) ถูกตัดออกชั่วคราว — Gemini model ยังเข้าถึงได้ผ่าน unorouter
        'groq,cerebras,mistral,cloudflare,openrouter,unorouter,router9,ollama'
    )

    # Report workflow and worker settings. Redis is optional for local development,
    # but required in production so report jobs survive web-server restarts.
    REDIS_URL = os.getenv('REDIS_URL', '')
    QUEUE_NAME = os.getenv('QUEUE_NAME', 'reports')
    REPORT_QUEUE_MODE = os.getenv('REPORT_QUEUE_MODE', 'auto').lower()
    MARKET_SNAPSHOT_TTL_MINUTES = int(os.getenv('MARKET_SNAPSHOT_TTL_MINUTES', '15'))

    # App Settings
    SCHEDULER_TIMEZONE = 'Asia/Bangkok'
    DEBUG = False

    # Discord — DISCORD_KET_STOCKS คือชื่อที่ user ใช้ใน .env (typo แต่รองรับไว้)
    DISCORD_BOT_TOKEN = (
        os.getenv('DISCORD_BOT_TOKEN')
        or os.getenv('DISCORD_KET_STOCKS')
        or os.getenv('DISCORD_ID_STOCKS', '')
    )
