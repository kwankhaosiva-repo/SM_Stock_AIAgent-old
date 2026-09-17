import os
from pathlib import Path
from dotenv import load_dotenv

# Use Pathlib for robustness (Cross-platform & Cloud Run Safe)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, ".env"))

class Config:
    # Point to Project Root
    BASE_DIR = str(BASE_DIR)
    
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL')
    
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

    # Settrade Open API (Thai Stocks)
    SETTRADE_APP_ID = os.getenv('SETTRADE_APP_ID')
    SETTRADE_APP_SECRET = os.getenv('SETTRADE_APP_SECRET')
    SETTRADE_BROKER_ID = os.getenv('SETTRADE_BROKER_ID', 'SANDBOX')
    SETTRADE_APP_CODE = os.getenv('SETTRADE_APP_CODE', 'SANDBOX')
    SETTRADE_IS_SANDBOX = os.getenv('SETTRADE_IS_SANDBOX', 'true').lower() == 'true'

    # LLM Settings
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
    GEMINI_MODEL_NAME = os.getenv('GEMINI_MODEL_NAME', 'gemini-flash-latest')

    # Report workflow and worker settings. Redis is optional for local development,
    # but required in production so report jobs survive web-server restarts.
    REDIS_URL = os.getenv('REDIS_URL', '')
    QUEUE_NAME = os.getenv('QUEUE_NAME', 'reports')
    REPORT_QUEUE_MODE = os.getenv('REPORT_QUEUE_MODE', 'auto').lower()
    MARKET_SNAPSHOT_TTL_MINUTES = int(os.getenv('MARKET_SNAPSHOT_TTL_MINUTES', '15'))

    # App Settings
    SCHEDULER_TIMEZONE = 'Asia/Bangkok'
    DEBUG = False
