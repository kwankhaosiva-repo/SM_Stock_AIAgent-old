# AIAgent LineStock - AI-Powered Personal Investment Assistant

A smart LINE Chatbot functioning as a personal financial analyst. It uses **Google Gemini 2.5 Flash** along with financial data APIs to analyze stock market trends, technical indicators, and headlines in real-time. It then generates personalized investment recommendations (BUY/SELL/HOLD/WAIT) presented through interactive LINE Flex Messages.

---

## 📌 Table of Contents
1. [Objectives & Overview](#-objectives--overview)
2. [UX/UI & Flex Messages](#-uxui--flex-messages)
3. [Tech Stack & Library Rationale](#-tech-stack--library-rationale)
4. [System Architecture & Data Flow](#-system-architecture--data-flow)
5. [Directory Structure](#-directory-structure)
6. [Database Schema & Models](#-database-schema--models)
7. [Environment Variables & Configuration](#-environment-variables--configuration)
8. [Deployment Guide](#-deployment-guide)
9. [Developer Guidelines (For AI Agents)](#-developer-guidelines-for-ai-agents)

---

## 🎯 Objectives & Overview
The system enables users to manage a personal stock watchlist, customize investment profiles (risk appetite, strategy, and goals), and receive either on-demand analyses or automated daily reports directly on LINE. 

### Core Features:
- **Watchlist Management**: Add/Delete stocks (US & Thai) via text input or interactive carousel.
- **Personalized AI Analysis**: Holistic stock evaluation context-aware of user preferences (e.g. Value, DCA, Growth, Dividend, Technical) using **Gemini 2.5 Flash**.
- **Automated Alert Scheduler**: Daily morning reports or customizable scheduling intervals triggered automatically.
- **Interactive UI**: Fully built with LINE Flex Messages, rich menus, and dynamically generated 30-day price trend charts.

---

## 📱 UX/UI & Flex Messages

| Add Stock | Scheduler | Watchlist Carousel |
|:---------:|:---------:|:------------------:|
| <img width="371" height="222" alt="Add" src="https://github.com/user-attachments/assets/ee16bde5-bf96-4590-bd08-85b7ea32047b" /> | <img width="377" height="370" alt="Scheduler" src="https://github.com/user-attachments/assets/41659e15-be0d-4a5a-9dfb-2bbe8d044238" /> | <img width="751" height="340" alt="WatchList" src="https://github.com/user-attachments/assets/4c8dc80b-0388-4cac-9664-b1b174e363a7" /> |

| Settings Menu | AI Analysis Report |
|:------------:|:------------------:|
| <img width="1529" height="588" alt="MainSetting" src="https://github.com/user-attachments/assets/922fb671-fb05-4ca9-b4f0-081b455c808f" /> | <img width="1531" height="722" alt="Report" src="https://github.com/user-attachments/assets/2673091d-c41f-4f9d-934a-d8f198ae4cbf" /> |

---

## 🛠 Tech Stack & Library Rationale

The project relies on specific libraries designed to maximize reliability and avoid subscription costs:

1. **Web Framework**: `Flask` (v3.0.0) — Lightweight receiver for LINE webhook events.
2. **AI Model**: `google-generativeai` — Direct API interface to `gemini-flash-latest` (Gemini 2.5 Flash), optimized with temperature `0.1` for deterministic, reliable financial outputs.
3. **Database & ORM**: `SQLAlchemy` + `pg8000` — ORM layer supporting seamless fallback between **SQLite** (local testing) and **Cloud SQL PostgreSQL** (production) without modifying database queries.
4. **Data Acquisition**:
   - `yfinance` — Fetches real-time prices, historical candles, and company profiles for global stocks. It also acts as the backend fallback for Thai stocks (using the `.BK` suffix) to bypass complex API connections.
   - `urllib.request` + `xml.etree.ElementTree` — Parses Google News RSS feeds in Thai, acting as a free and structured news pipeline.
5. **Charts Generation**: `QuickChart API` — Generates 30-day stock trend line charts on-the-fly and outputs public URLs to embed directly inside LINE Flex Messages without local storage overhead.
6. **Task Scheduler**: `APScheduler` — Manages automated checks and schedules daily maintenance tasks (e.g., database cache pruning at 3:00 AM Bangkok Time).

---

## 🏗 System Architecture & Data Flow

```mermaid
graph TD
    LineUser[LINE User] <-->|Interactive Messages / Menu| LineServer[LINE Platform]
    LineServer -->|Webhook / Postback Event| FlaskServer[Flask Web Server: app.py]
    
    subgraph Core Server
        FlaskServer -->|Deduplication & Request Check| DB[(PostgreSQL / SQLite)]
        FlaskServer -->|Fire-and-Forget Thread| AnalysisEngine[Analysis Engine: analyzer.py]
        
        AnalysisEngine -->|Cache Check / Load| CacheDB[(global_stock_info Cache)]
        AnalysisEngine -->|Fetch Real-time Quotes & History| YFinance[yfinance Wrapper]
        AnalysisEngine -->|Parse Headlines| GoogleNewsRSS[Google News RSS Feed]
        AnalysisEngine -->|Holistic Stock Prompt| Gemini[Gemini 2.5 Flash API]
        
        AnalysisEngine -->|Generate Trend Charts| QuickChart[QuickChart URL Generator]
        AnalysisEngine -->|Compile UI Placeholders| FlexTemplate[Template Loader: line_templates.py]
    end
    
    FlexTemplate -->|Rendered Flex Message| PushAPI[LINE Push Message API]
    PushAPI -->|Deliver Report / Menu| LineServer
    
    subgraph Background Scheduler
        CloudScheduler[Google Cloud Scheduler] -->|Hourly POST /cron/trigger| FlaskServer
        FlaskServer -->|Hourly Jobs Run| Worker[worker.py]
        Worker -->|Scheduled Watchlists| AnalysisEngine
        Worker -->|Daily Cache Reset 3 AM| CacheDB
    end
```

### Key Integration Mechanics:
- **Request Deduplication**: Uses LINE’s `isRedelivery` flag in the webhook context to ignore duplicates.
- **Fail-Fast & Fallbacks**: API requests have short timeouts (3 seconds). If an indicator fails to calculate or is missing (e.g. ETF P/E ratio), it falls back to `"N/A"` to prevent system crashes.
- **Non-blocking Operations**: On-demand analysis requests reply instantly with an estimated processing time and fire a background thread to call the APIs/LLM, bypassing LINE's strict webhook timeout limits.

---

## 📂 Directory Structure

```directory
SM_Stock_AIAgent/
├── line_ux/                        # LINE Flex Message Templates (JSON configurations)
│   ├── rich_menu.json              # Custom Rich Menu layout and coordinates mapping
│   ├── rich_menu.lbd               # Line Bot Designer project file for editing menus
│   ├── add.json                    # Flex layout for 'Add Stock' verification card
│   ├── watch_list.json             # Scrollable watchlist layout
│   ├── analysis.json               # Stock report card (indicators, news, recommendations)
│   ├── scheduler.json              # Daily scheduler configuration window
│   ├── carousel_setting_global.json# Global profile preferences (risk, strategy)
│   └── carousel_setting_stock.json # Stock-specific override configurations
│
├── src/                            # Source Code
│   ├── app.py                      # Flask Application Server (Entry point, webhooks, callbacks)
│   ├── config.py                   # Environment configuration (SQLite vs PostgreSQL parsing)
│   ├── database.py                 # SQLAlchemy schemas & session definitions
│   ├── init_cache_db.py            # Global Stock cache schema initialization
│   ├── line_templates.py           # Flex template parser and placeholder resolver
│   ├── services.py                 # Batch processing queue and rate-limiting wrapper
│   ├── analyzer.py                 # Core analysis script (combines yfinance, RSS, and LLM)
│   ├── llm_service.py              # Gemini client wrapper, prompt manager, and regex parser
│   ├── global_stock_helper.py      # US/Global stock helper & news scraper
│   ├── thai_stock_helper.py        # Thai stock helper (integrates yfinance with `.BK` suffix)
│   ├── worker.py                   # Background scheduler & cache maintenance worker
│   ├── upload_rich_menu.py         # Utility script to build, upload, and publish Rich Menus
│   └── scratch/                    # Temporary testing scripts and sandbox files
│
├── Dockerfile                      # Production container builder
├── requirements.txt                # Python dependencies list
└── app.db                          # Local SQLite Database (Used in local environment)
```

---

## 🗄 Database Schema & Models

The system runs on the following relational schemas mapped inside `src/database.py` and `src/init_cache_db.py`:

```mermaid
erDiagram
    users {
        int id PK
        string line_user_id UK "Index"
        string display_name
        string investment_goal "Default: Medium"
        string core_strategy "Default: AI-Auto"
        string risk_appetite "Default: Medium"
        string report_format "Default: Short"
    }
    
    watchlist {
        int id PK
        int user_id FK
        string symbol
        string strategy "DCA/Value/Growth/etc"
        string goal "Short/Medium/Long"
        string risk "Low/Medium/High"
        string report_format
        float target_price
        float alert_on_drop_percent
    }
    
    schedules {
        int id PK
        int user_id FK
        int frequency_days "Default: 1"
        string alert_time "Default: 06:00"
        datetime last_run
        boolean is_active "Default: True"
    }
    
    global_stock_info {
        string symbol PK
        string company_name
        string market_cap
        float pe_ratio
        float dividend_yield
        datetime updated_at
    }

    users ||--o{ watchlist : "manages"
    users ||--o| schedules : "has"
```

---

## ⚙ Environment Variables & Configuration

Create a `.env` file at the root of the project to set up the configuration parameters:

```env
# Line Channel Config
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
LINE_CHANNEL_SECRET=your_line_channel_secret

# LLM API
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL_NAME=gemini-flash-latest

# Database Config (Leave blank to automatically fallback to Local SQLite 'app.db')
DATABASE_URL=postgresql://username:password@host:port/database

# Optional Settrade Sandbox Configuration (If using Settrade API instead of yfinance fallbacks)
SETTRADE_APP_ID=your_settrade_app_id
SETTRADE_APP_SECRET=your_settrade_app_secret
```

---

## 🚀 Deployment Guide

### Running Locally:
1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Initialize local database schemas**:
   ```bash
   python src/database.py
   python src/init_cache_db.py
   ```
3. **Run local server**:
   ```bash
   python src/app.py
   ```
4. **Expose Localhost Webhook (ngrok)**:
   ```bash
   ngrok http 8080
   ```
   *Note: Copy the ngrok URL and configure it in your LINE Developers Console Webhook URL as `https://<subdomain>.ngrok-free.app/callback`*

5. **Upload Rich Menu**:
   ```bash
   python src/upload_rich_menu.py line_ux/rich_menu.json [path_to_rich_menu_image]
   ```

### Deploying to Cloud Run:
Deploy directly using Docker containerization:
```bash
gcloud run deploy sm-stock-aiagent --source . --platform managed --region asia-east1 --allow-unauthenticated
```

---

## 🤖 Developer Guidelines (For AI Agents)

When modifying or expanding this codebase, you **must** adhere to the following architectural design constraints and execution patterns:

### 1. Database Operations
- **Safety First**: Never execute commands that alter, truncate, or drop database tables without explicit user approval.
- **URL Overrides**: Ensure SQLAlchemy PostgreSQL URL conversion logic (`postgresql+pg8000://`) inside `src/config.py` is maintained to prevent database driver errors on Cloud Run.

### 2. API Rate Limiting & Performance
- **Enforced Delays**: When requesting quotes or candles in a loop, always call `time.sleep(1)` inside the loop (as implemented in `src/services.py`) to respect the free tier rate limits of yfinance/TwelveData APIs.
- **Fail-Safe Values**: Always verify return values for indicators or P/E metrics. If a value is missing or zero, store/display it as `"N/A"` or `None` rather than default values which distort LLM outputs.

### 3. AI Prompts & Parsing
- **Regex Enforcement**: The LLM prompt inside `src/llm_service.py` requires a strict format output: `SIGNAL | REASON | NEWS_SUMMARY`. If you modify the prompt, ensure the regex matching logic in `src/analyzer.py` is updated accordingly to avoid parsing failures.
- **LLM Consistency**: Always keep `temperature=0.1` for LLM configurations to guarantee reproducible signal decisions for similar market conditions.

### 4. Pure Function Skill System (`src/skills/`)
- If you write new logic that is not tied to database side effects or framework webhooks (e.g. proprietary financial indicators calculation, text sanitization, custom regex parser):
  - Check `src/skills/` first for existing pure functions.
  - If a relevant skill is missing, create a clean implementation inside `src/skills/{skill_name}.py` containing a descriptive docstring defining inputs/outputs, and list it in `src/skills/README.md`.
  - Always keep skill functions "pure" (input -> output, no global mutations or state dependency).

### 5. Task Workflows
- **Phase 1 (Analysis)**: Examine target files, active configurations, and environment configurations before proposing changes.
- **Phase 2 (Execution)**: Create logic tests inside `src/scratch/` and verify locally before deployment.
- **Phase 3 (Validation)**: Run local validation tests to confirm your updates do not break existing components (regression check). Do not attempt to run live cloud deploy steps in the terminal.
