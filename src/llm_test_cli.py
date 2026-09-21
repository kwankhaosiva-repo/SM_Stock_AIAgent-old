"""Terminal CLI to trial LLMs locally before GCP deploy.

Primary use case: test the LOCAL Ollama model (e.g. mistral-small3.2:24b)
so you can validate prompt quality and the full news-analysis pipeline
without any cloud API keys / Secret Manager.

Usage:
    # 1. Raw LLM test (default: ollama)
    python src/llm_test_cli.py                              # interactive chat
    python src/llm_test_cli.py --prompt "สรุปข่าว PTT 1 ประโยค"

    # 2. Full pipeline: news analysis with real market data via Ollama
    python src/llm_test_cli.py --pipeline PTT
    python src/llm_test_cli.py --pipeline AAPL

    # 3. Router failover test (e.g. ollama first, cloud fallback)
    python src/llm_test_cli.py --order ollama,gemini --prompt "hello"

    # 4. Test any cloud provider you DO have a key for
    python src/llm_test_cli.py --provider gemini --prompt "hello"
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load local .env (same convention as the app) so OLLAMA_* vars work here.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
except ImportError:
    pass

from llm_providers import PROVIDERS, LLMRouter, ProviderError  # noqa: E402
from config import Config  # noqa: E402


def _check_ollama_server() -> bool:
    """Fail fast with a helpful message if the Ollama server isn't up."""
    if not Config.OLLAMA_BASE_URL:
        return False
    try:
        import requests
        r = requests.get(f"{Config.OLLAMA_BASE_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except requests.RequestException:
        return False


def cmd_prompt(args: argparse.Namespace) -> None:
    """Call one provider directly with a prompt (or start interactive chat)."""
    provider = args.provider or 'ollama'

    if provider == 'ollama':
        if not _check_ollama_server():
            print("❌ Ollama server not reachable.")
            print("   Start it:        ollama serve")
            print("   And set in .env: OLLAMA_BASE_URL=http://localhost:11434")
            print(f"   Current config:  OLLAMA_BASE_URL={Config.OLLAMA_BASE_URL!r}, "
                  f"OLLAMA_MODEL_NAME={Config.OLLAMA_MODEL_NAME!r}")
            sys.exit(1)
        print(f"🦙 ollama :: model={Config.OLLAMA_MODEL_NAME}")
    else:
        print(f"☁️  provider={provider}")

    fn = PROVIDERS.get(provider)
    if fn is None:
        print(f"❌ Unknown provider {provider!r}. Available: {', '.join(PROVIDERS)}")
        sys.exit(1)

    if args.prompt:
        _single_call(fn, args.prompt)
        return

    # Interactive chat — history is flattened into the prompt so context
    # forwarding matches how the router sends context between providers.
    print("Interactive chat (type 'exit' to quit):\n")
    history: list[str] = []
    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user.lower() in ('exit', 'quit'):
            break
        if not user:
            continue
        history.append(f"User: {user}")
        _single_call(fn, "\n".join(history), label='ai> ')
        print()


def _single_call(fn, prompt: str, label: str = 'ai> ') -> None:
    start = time.time()
    try:
        text = fn(prompt)
        elapsed = time.time() - start
        print(f"{label}{text.strip()}")
        print(f"   ⏱ {elapsed:.1f}s")
    except ProviderError as exc:
        print(f"❌ provider failed: {exc}")
        sys.exit(1)


def cmd_pipeline(args: argparse.Namespace) -> None:
    """Full news-analysis pipeline (market snapshot + LLM) via Ollama."""
    from data.market_snapshot_service import MarketSnapshotService
    from analysis.news_analysis import analyze_news

    symbol = args.pipeline.upper()
    order = (args.order or 'ollama').split(',')
    router = LLMRouter(order=[p.strip() for p in order if p.strip()])

    print(f"📡 Fetching snapshot for {symbol} ...")
    svc = MarketSnapshotService()
    snap = None
    for candidate in ([symbol, f'{symbol}.BK'] if not symbol.endswith('.BK') else [symbol]):
        try:
            snap, _ = svc.get_or_collect(candidate)
            if snap is not None:
                symbol = candidate
                break
        except (ValueError, Exception) as exc:
            print(f"   ({candidate}: {exc})") 
    if snap is None:
        print(f"❌ No snapshot for {symbol} (all market providers failed)")
        sys.exit(1)
    print(f"   price={snap.price} provider={getattr(snap, 'provider_name', '?')}")

    print(f"🧠 Analyzing via router order: {[p for p, _ in router.chain]}")
    start = time.time()
    result = analyze_news(snap, router=router)
    elapsed = time.time() - start

    print(f"\n{'=' * 60}\nMarket Impact: {result.get('impact')}  "
          f"(provider: {result.get('provider', router.last_used)})\n{'=' * 60}")
    print(f"Why it matters:\n{result.get('summary', '')}\n")
    advice = result.get('advice') or []
    if isinstance(advice, str):
        advice = [advice]
    for i, item in enumerate(advice, 1):
        print(f"  {i}. {item}")
    print(f"\n⏱ total {elapsed:.1f}s")


def cmd_router(args: argparse.Namespace) -> None:
    """Test the failover router itself with a forced order."""
    order = [p.strip() for p in (args.order or Config.LLM_PROVIDER_ORDER).split(',') if p.strip()]
    router = LLMRouter(order=order)
    print(f"🔗 chain: {[p for p, _ in router.chain]}")
    start = time.time()
    try:
        text = router.generate(args.prompt or "ตอบสั้นๆ: ทดสอบการเชื่อมต่อสำเร็จ")
        print(f"✅ OK via '{router.last_used}' ({time.time() - start:.1f}s)\n{text.strip()}")
    except ProviderError as exc:
        print(f"❌ all providers failed:\n{exc}")
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Trial LLMs in terminal (Ollama local first)")
    ap.add_argument('--prompt', help="one-shot prompt (omit for interactive chat)")
    ap.add_argument('--provider', choices=sorted(PROVIDERS),
                    help="direct provider call (default: ollama)")
    ap.add_argument('--order', help="comma-separated router order, e.g. ollama,gemini")
    ap.add_argument('--pipeline', metavar='SYMBOL',
                    help="full news-analysis pipeline for a symbol, e.g. PTT")
    args = ap.parse_args()

    if args.pipeline:
        cmd_pipeline(args)
    elif args.order:
        cmd_router(args)
    else:
        cmd_prompt(args)


if __name__ == '__main__':
    main()
