# AIAgent LineStock — Project Presentation Brief

> One-page tech-stack presentation for pitching / demo / onboarding.

---

## 🎬 Elevator Pitch (30 s)

**"A multi-channel stock research assistant that turns raw market data into evidence-based advice — powered entirely by free-tier cloud LLMs with automatic failover, running at near-zero cost on GCP scale-to-zero."**

- Users add stocks to a watchlist on **LINE / Web / Discord**
- AI agents analyze **news + balance sheets + technical indicators**
- Every recommendation cites its evidence: news, financials, and statistics separately
- No hallucinated numbers — all math is deterministic Python

---

## 🧩 The Problem

| Pain | Our answer |
|---|---|
| Single LLM API = single point of failure + quota/billing risk (e.g., Gemini 402 credits depleted) | Provider chain with **context-forwarding failover** across 8 free-tier providers |
| AI-generated stock advice is vague or hallucinated | **Evidence-based contract**: every claim maps to a numbered news source, a computed ratio, or a deterministic indicator |
| Market data APIs block cloud IPs / cost money | Provider chain for data too: Settrade → Yahoo → FMP → local relay via Cloudflare Tunnel |
| Duplicated AI calls when users press buttons repeatedly | Press-debounce locks + 15-min snapshot cache + idempotent deliveries |

---

## 🏗 Architecture Highlights

```
Channels (LINE / Web / Discord)
        │
   Chat dispatch layer (same commands, every channel)
        │
   Flask webhook ──► Job queue (RQ/Redis ↔ local fallback)
        │
   Market Snapshot Service ──► Firestore cache (15-min TTL)
        │
   4-agent workflow (parallel, audited in Firestore)
   News Context ─┬─► Personalized Advice ─► Risk & Evidence Reviewer
   Fund/Tech ────┘
        │
   Flex renderers ──► push / reply
```

### Three resilience layers
1. **LLM chain** — `groq → cerebras → mistral → cloudflare → openrouter → unorouter → router9 → ollama`; failure (429/404/timeout/no key) forwards the *same prompt + context* to the next provider; 404 self-heals by fetching live `/models`.
2. **Data chain** — Settrade Open API (official Thai) → Yahoo → FMP → home-machine relay (Cloudflare Tunnel) to dodge cloud-IP blocks.
3. **Delivery** — canonical-UUID `X-Line-Retry-Key` + Firestore idempotency keys = zero duplicate pushes.

---

## 🧠 AI Design: Evidence-Based, Not LLM Math

| Deterministic (Python/pandas) | LLM (interpretation only) |
|---|---|
| RSI-14, SMA-20/50, volatility, support/resistance (30-day swing), 52-week range | Synthesizes ranked news into one verdict |
| D/E, net margin, ROE, P/B from raw balance-sheet values | Explains *why* each number matters (Thai, with formulas) |
| News cleaning: dedupe, strip garbage, impact scoring | Buy/Hold/Sell reasoning with citation contract ([1], [2]…) |
| Charts (QuickChart sparklines) | Risk framing & items to watch |

**Safety gate**: independent `RiskEvidenceReviewer` agent rejects advice containing unsupported claims, stale data (>15 min), or guaranteed-return language.

---

## 💡 UX Engineering

- **Instant ack**: every button press replies "⏳ processing" immediately — no dead air.
- **Press debounce**: 30-s lock per user/action/symbol in Firestore; repeat presses get "already working on it" instead of duplicate AI calls.
- **Progressive disclosure**: 2-line headline flash in the summary card → full impact-ranked news card (with original-source buttons) on the News press.
- **Three-bucket reasons**: 📰 News / 🏦 Financials / 📊 Statistics — the user always knows *which kind of evidence* backs each claim.

---

## 🧰 Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11, Flask 3, gunicorn |
| Channels | line-bot-sdk (Flex), discord.py, web chat |
| LLM | google-genai + OpenAI-compatible failover chain (8 providers incl. Ollama local) |
| Data | yfinance, pandas, Google News RSS, Settrade Open API, FMP |
| Storage | Google Firestore (prod) / in-memory backend (dev & tests) |
| Queue | Redis + RQ (optional; local thread-pool fallback) |
| Validation | Pydantic v2 JSON contracts for all agent outputs |
| Deploy | Docker → GCP Cloud Run (scale-to-zero), Secret Manager, Cloud Scheduler |

---

## 💰 Cost Story (hobbyist → production)

| Component | Cost |
|---|---|
| LLMs | **$0** — free tiers across 8 providers + local Ollama for dev |
| Cloud Run | **~$0** — scale-to-zero, min-instances 0 |
| Firestore | free tier (SP-SB) covers hobby workloads |
| Secret Manager / Scheduler | free tier |
| **Total** | **effectively $0/month for a personal bot** |

---

## 🚀 What's Next

1. **BigQuery analytics** — export `analysis_runs` to `stocks_query` for historical recommendation-accuracy dashboards.
2. **LangGraph orchestration** — conditional branching (skip expensive analysis for low-impact questions) + reflection loops (fact-check against financials before delivery).
3. **Settrade production account** — live Thai-market data with real trading-grade quality.
4. **News source upgrade** — Finnhub company news / SET official news beyond Google News RSS.

---

## ✅ Demo Script (5 min)

1. Add stock "PTT" via LINE rich menu → confirmation carousel.
2. Press **News** → instant ack → impact-ranked card with source buttons.
3. Press **Why?** → support/resistance *with derivation* + three-bucket reasons.
4. Press **Financials** → ratios with formulas computed from the real balance sheet.
5. Show Cloud Run logs: provider failover in action (`groq 404 → next provider`).
6. Show `/debug/config`: secret mounting verified without exposing values.
