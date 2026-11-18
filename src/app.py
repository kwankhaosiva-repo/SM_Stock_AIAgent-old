import os
import sys

# Ensure src is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, send_file, jsonify, request
from config import Config
from api.line_webhook import line_webhook_bp
from api.web_chat import web_chat_bp

app = Flask(__name__)
app.config.from_object(Config)

# Register channel blueprints: LINE webhook + Web chat UI
app.register_blueprint(line_webhook_bp)
app.register_blueprint(web_chat_bp)

# Path to docs/presentation.html (project root / docs / presentation.html)
_PRESENTATION_HTML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs",
    "presentation.html",
)


def _render_presentation():
    if os.path.exists(_PRESENTATION_HTML):
        response = send_file(_PRESENTATION_HTML, mimetype="text/html; charset=utf-8")
        response.headers["Cache-Control"] = "no-cache"
        return response
    return jsonify({"ok": False, "error": "docs/presentation.html not found"}), 404


@app.route("/presentation", methods=['GET'])
def presentation():
    """Serves the project presentation HTML page (same as docs/presentation.html)"""
    return _render_presentation()


@app.route("/brief", methods=['GET'])
def brief():
    """Short alias for /presentation"""
    return _render_presentation()


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

    import store
    from config import Config
    return {
        'LINE_CHANNEL_SECRET': status('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET'),
        'LINE_CHANNEL_ACCESS_TOKEN': status('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_ACCESS_TOKEN'),
        'GEMINI_API_KEY': status('GEMINI_API_KEY') or status('GEMINI_API'),
        'GROQ_API_KEY': status('GROQ_API_KEY') or status('GROQ_API'),
        'MISTRAL_API_KEY': status('MISTRAL_API_KEY') or status('MISTRAL_API'),
        'OPENROUTER_API_KEY': status('OPENROUTER_API_KEY') or status('OPENROUTER_API'),
        'DATA_BACKEND': store.backend_name(),
        'FIRESTORE_DATABASE': os.environ.get('FIRESTORE_DATABASE', 'agent-stocks'),
    }, 200


@app.route("/cron/trigger", methods=['GET', 'POST'])
def cron_trigger():
    """Endpoint for Google Cloud Scheduler or HTTP cron to trigger hourly checks.
    Executes synchronously to prevent Cloud Run scale-to-zero / CPU freeze from dropping jobs.
    Optional query parameters:
      - time: HH:00 (e.g. 09:00) to check a specific hour
      - force: true/1 to bypass last_run check for testing
      - user_id: specific user key to test
    """
    target_time = request.args.get('time')
    force = request.args.get('force', '').lower() in ('true', '1')
    user_key = request.args.get('user_id') or request.args.get('user_key')

    print(f"[CRON] Triggered (time={target_time}, force={force}, user_key={user_key})")
    from tasks.dispatcher import check_jobs, process_schedule
    import store

    if user_key:
        sched = store.get_schedule(user_key) or {'user_key': user_key}
        process_schedule(sched, sync=True)
        processed = 1
    else:
        processed = check_jobs(target_time=target_time, force=force, sync=True)

    return jsonify({
        "status": "ok",
        "message": "Cron Job Completed",
        "processed": processed,
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
