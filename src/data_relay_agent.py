"""Local Data Relay Agent — runs on a home machine (residential IP).

Cloud Run cannot reliably call Yahoo Finance (datacenter IPs get rate
limited), but a home connection is fine. This tiny Flask app exposes
/quote/<symbol> using yfinance and is exposed to the internet via a free
Cloudflare Tunnel — no open router ports, no static IP.

Run locally:
    python src/data_relay_agent.py          # listens on 127.0.0.1:8787
    cloudflared tunnel --url http://127.0.0.1:8787
    # copy the https://xxx.trycloudflare.com URL into Cloud Run's
    # DATA_RELAY_URL secret — done.

Security note: the tunnel URL is unguessable but public; keep it secret and
rotate it by restarting cloudflared. For stronger auth add a token header
check via DATA_RELAY_TOKEN.
"""
from __future__ import annotations

import os

from flask import Flask, abort, jsonify, request

from config import Config

app = Flask(__name__)

_TOKEN = os.getenv('DATA_RELAY_TOKEN', '')


def _check_token():
    if _TOKEN and request.headers.get('X-Relay-Token') != _TOKEN:
        abort(403)


@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok', 'service': 'data-relay'}


@app.route('/quote/<symbol>', methods=['GET'])
def quote(symbol: str):
    _check_token()
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or not (2 <= len(symbol) <= 12):
        abort(400)

    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)

        history_prices = []
        try:
            hist = ticker.history(period='60d')
            if not hist.empty and 'Close' in hist:
                history_prices = [float(p) for p in hist['Close'].dropna().tolist()]
        except Exception as exc:
            print(f'[Relay] history error {symbol}: {exc}')

        info = {}
        try:
            info = ticker.info or {}
        except Exception as exc:
            print(f'[Relay] info error {symbol}: {exc}')

        price = 0.0
        current = info.get('currentPrice') or info.get('regularMarketPrice')
        if current:
            price = float(current)
        elif history_prices:
            price = history_prices[-1]

        if price <= 0:
            return jsonify({'error': 'no price'}), 404

        pe = info.get('trailingPE') or info.get('forwardPE')
        yd = info.get('dividendYield')

        return jsonify({
            'symbol': symbol,
            'price': price,
            'pe_ratio': float(pe) if pe else None,
            'div_yield': (float(yd) * 100 if float(yd) < 1.0 else float(yd)) if yd else None,
            'history': history_prices,
            'technicals': {},
        })
    except Exception as exc:
        print(f'[Relay] quote error {symbol}: {exc}')
        return jsonify({'error': str(exc)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('RELAY_PORT', '8787'))
    app.run(host='127.0.0.1', port=port)
