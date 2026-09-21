import os
import sys

# Ensure src is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from config import Config
from api.line_webhook import line_webhook_bp
from api.web_chat import web_chat_bp

app = Flask(__name__)
app.config.from_object(Config)

# Register channel blueprints: LINE webhook + Web chat UI
app.register_blueprint(line_webhook_bp)
app.register_blueprint(web_chat_bp)

_db_initialized = False


def ensure_db_initialized():
    global _db_initialized
    if not _db_initialized:
        from database import Base, engine

        try:
            print("[INIT] Lazy initializing database...")
            Base.metadata.create_all(bind=engine)
            try:
                from init_cache_db import Base as CacheBase
            except ImportError:
                from src.init_cache_db import Base as CacheBase
            CacheBase.metadata.create_all(bind=engine)
            _db_initialized = True
            print("[INIT] Database initialization successful.")
        except Exception as e:
            print(f"[INIT] Database Init Warning: {e}")


@app.before_request
def before_request_hook():
    ensure_db_initialized()


@app.route("/health", methods=['GET'])
def health():
    return {"status": "ok", "channels": ["line", "web", "discord"]}, 200


@app.route("/debug/config", methods=['GET'])
def debug_config():
    """Report which env vars are actually visible to THIS container.
    Shows only set/empty + whether a value is a known placeholder — never the value itself.
    Use to diagnose secret mounting issues on Cloud Run."""
    def status(name: str, default: str = '') -> str:
        val = os.environ.get(name, '')
        if not val or val == default:
            return 'PLACEHOLDER/EMPTY'
        return 'SET'

    from config import Config
    return {
        'LINE_CHANNEL_SECRET': status('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET'),
        'LINE_CHANNEL_ACCESS_TOKEN': status('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_ACCESS_TOKEN'),
        'GEMINI_API_KEY': status('GEMINI_API_KEY') or status('GEMINI_API'),
        'GROQ_API_KEY': status('GROQ_API_KEY') or status('GROQ_API'),
        'MISTRAL_API_KEY': status('MISTRAL_API_KEY') or status('MISTRAL_API'),
        'OPENROUTER_API_KEY': status('OPENROUTER_API_KEY') or status('OPENROUTER_API'),
        'DATABASE_URL': 'SET' if Config.DATABASE_URL.startswith('postgres') else 'LOCAL_SQLITE',
    }, 200


@app.route("/cron/trigger", methods=['GET', 'POST'])
def cron_trigger():
    """Endpoint for Google Cloud Scheduler or HTTP cron to trigger hourly checks."""
    ensure_db_initialized()
    print("[CRON] Triggered by Cloud Scheduler")
    from tasks.dispatcher import check_jobs

    check_jobs()
    return "Cron Job Completed", 200


if __name__ == "__main__":
    ensure_db_initialized()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
