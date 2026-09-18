# AIAgent LineStock - Evidence-Based Stock Research Assistant

A production-ready, multi-agent LINE stock research assistant powered by **Google Gemini** (`google-genai` / structured JSON) and deterministic Python financial services. It provides personalized, evidence-grounded decision support with interactive LINE Flex Message reports.

---

## 📌 Table of Contents
1. [Overview & Architecture](#-overview--architecture)
2. [Multi-Agent System & Reasoning Souls](#-multi-agent-system--reasoning-souls)
3. [Source Structure](#-source-structure)
4. [Tech Stack & Dependencies](#-tech-stack--dependencies)
5. [Database Schema & Migrations](#-database-schema--migrations)
6. [Queue, Dispatcher & Workers](#-queue-dispatcher--workers)
7. [Environment Variables](#-environment-variables)
8. [Local Development & Testing](#-local-development--testing)
9. [Deployment Guide](#-deployment-guide)

---

## 🎯 Overview & Architecture

Users register stocks to a personal watchlist, configure their investment style, and receive structured reports based on fresh price data, precomputed technical indicators, company fundamentals, relevant news, and global market context.

The system emphasizes **decision support**, never giving raw `BUY`/`SELL` orders or guaranteed return promises.

```mermaid
flowchart LR
  A[LINE / User Request] --> B[Webhook API: line_webhook.py]
  B --> C[Job Queue: RQ / Redis]
  D[Schedule Dispatcher: dispatcher.py] --> C
  C --> E[Market Snapshot Service]
  E --> F[(Market Snapshot DB Cache)]
  F --> G[News Context Agent]
  F --> H[Fundamental + Technical Agent]
  G --> I[Personalized Advice Agent]
  H --> I
  I --> J[Risk & Evidence Reviewer Gate]
  J --> K[LINE Report Renderer]
  K --> L[LINE Push Message]
```

### Deterministic Foundation
- **No LLM Math**: Technical indicators (RSI-14, SMA-20, SMA-50, 30-day volatility, support/resistance, 52-week high/low) are computed deterministically in Python using `pandas`.
- **Chart Service**: 30-day price trend charts are generated deterministically via QuickChart.
- **Snapshot Caching**: Market snapshots are cached in the database (`market_snapshots`) with a 15-minute TTL, making them reusable across multiple users following the same stock without redundant external API calls.

---

## 🤖 Multi-Agent System & Reasoning Souls

The workflow orchestrates four specialist agents with version-controlled Markdown system instructions (`src/agents/souls/`):

1. **`NewsContextAgent`** (`news_context.md`):
   - Extracts and filters company and macro news.
   - Retains provenance (title, URL, published time, relevance).
2. **`FundamentalTechnicalAgent`** (`fundamental_technical.md`):
   - Interprets precomputed price, P/E, dividend yield, and technical indicators.
   - Never hallucinates prices or recalculates indicators.
3. **`PersonalizedAdviceAgent`** (`personalized_advice.md`):
   - Synthesizes findings with user strategy, goal, and risk appetite.
   - Produces 3 evidence-based reasons, tangible risks, and next items to watch with a measured outlook (`Positive`, `Neutral`, `Cautious`).
4. **`RiskEvidenceReviewer`** (`risk_evidence_reviewer.md`):
   - Independent compliance gatekeeper.
   - Scrutinizes advice for unsupported claims, stale data (>15 min), or forbidden words (e.g. "การันตี", "กำไรแน่นอน"). Returns `approve`, `revise`, or `reject`.

---

## 📂 Source Structure

```text
src/
  api/
    line_webhook.py              # Webhook endpoint & event routing blueprint
  data/
    providers/
      base.py                    # MarketDataProvider & NewsDataProvider interfaces
      yahoo_provider.py          # Yahoo Finance provider for quotes, history, metrics
      thai_market_provider.py    # SET equities (.BK) provider with Settrade / Yahoo fallback
      news_provider.py           # Company & macro news scraper with provenance
      legacy_provider.py         # Adapter for backwards compatibility
    market_snapshot_service.py   # Snapshot collection, cache reuse, and source tracking
  analysis/
    indicators.py                # Precomputed RSI, SMA, volatility, support/resistance
    chart_service.py             # Deterministic QuickChart sparkline generator
  agents/
    contracts.py                 # Pydantic schema exports
    runner.py                    # Base agent runner with JSON validation & fallbacks
    news_context_agent.py
    fundamental_technical_agent.py
    personalized_advice_agent.py
    risk_evidence_reviewer.py
    souls/                       # Markdown system prompts
      news_context.md
      fundamental_technical.md
      personalized_advice.md
      risk_evidence_reviewer.md
  workflows/
    report_workflow.py           # Parallel agent orchestration & DB audit logging
  tasks/
    dispatcher.py                # Cron scheduler & schedule claim dispatcher
    queue.py                     # RQ / Redis queue with local development executor
    worker.py                    # RQ report job processor & idempotent push delivery
  reporting/
    line_report_renderer.py      # Stock Report Card & Daily Digest Flex builders
  models/
    analysis_models.py           # Pydantic v2 data models
  app.py                         # Flask application server
  config.py                      # Multi-environment configuration
  database.py                    # SQLAlchemy models & session factory
  worker.py                      # CLI entrypoint for background worker or scheduler
```

---

## 🗄 Database Schema & Migrations

The relational database supports both **SQLite** (local development) and **PostgreSQL** (production).

### Tables:
- `users`: Profile settings (investment goal, strategy, risk appetite).
- `watchlist`: Stocks tracked by users.
- `schedules`: Scheduled alert delivery times.
- `market_snapshots`: Immutable cached market data snapshots.
- `source_documents`: Provenance articles/news associated with snapshots.
- `analysis_runs`: Audit trail of every workflow run and status.
- `agent_outputs`: Structured JSON outputs from each agent stage.
- `report_deliveries`: Idempotent delivery records preventing duplicate push notifications.

### Alembic Migrations:
```bash
# Check current migration revision
alembic current

# Run pending migrations
alembic upgrade head
```

---

## 🔄 Queue, Dispatcher & Workers

### 1. Webhook (Immediate Response)
When a user requests a report or sets a schedule, the webhook confirms immediately and enqueues a background job.

### 2. Job Queue (RQ / Redis)
- Production uses Redis (`REDIS_URL`) and RQ worker processes.
- Local development automatically falls back to an internal thread pool if Redis is not configured.

### 3. Idempotency & LINE Retry Key
- Every report delivery stores an `idempotency_key` in `report_deliveries`.
- Duplicate webhook deliveries or retried jobs are recognized and will not send duplicate push messages.
- LINE push messages pass `retry_key=request_id`.

---

## ⚙ Environment Variables

Configure `.env` in the project root:

```env
# Database
DATABASE_URL=postgresql://user:password@host:5432/dbname  # Or leave empty for local SQLite app.db

# LINE Messaging API
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
LINE_CHANNEL_SECRET=your_line_channel_secret

# LLM (Google Gemini)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL_NAME=gemini-flash-latest

# Background Queue & Cache
REDIS_URL=redis://localhost:6379/0                       # Optional locally; required in prod
QUEUE_NAME=reports
REPORT_QUEUE_MODE=auto                                    # auto, rq, or local
MARKET_SNAPSHOT_TTL_MINUTES=15                           # Snapshot cache TTL

# Scheduler
SCHEDULER_TIMEZONE=Asia/Bangkok
```

---

## 🧪 Local Development & Testing

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Initialize Database
```bash
python src/database.py
```

### 3. Run Test Suite
```bash
python -m unittest discover -s tests -v
```

### 4. Run Application Server
```bash
python src/app.py
```

### 5. Run Background Scheduler / RQ Worker
```bash
# Run Schedule Dispatcher (cron alert checks):
python src/worker.py

# Run Standalone RQ Worker (requires Redis):
python src/worker.py rq
```

---

## 🚀 Deployment Guide

### Deploying to Google Cloud Run:
```bash
gcloud run deploy sm-stock-aiagent \
  --source . \
  --platform managed \
  --region asia-east1 \
  --allow-unauthenticated
```
