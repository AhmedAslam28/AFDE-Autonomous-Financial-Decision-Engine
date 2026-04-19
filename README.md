<div align="center">

<img src="static/logoname.png" alt="AFDE Logo" width="280" style="border-radius:12px"/>

# AFDE — Autonomous Financial Decision Engine

**Multi-agent AI system that analyses stocks, portfolios, and markets — delivering structured BUY / HOLD / SELL verdicts with full reasoning, sourced data, and complete explainability.**

![Python](https://img.shields.io/badge/Python-3.12-3B82F6?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-111827?style=flat-square&logo=flask&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI_Agents_SDK-0.13-10B981?style=flat-square&logo=openai&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-Model_Context_Protocol-8B5CF6?style=flat-square)

</div>

---

## What is AFDE?

AFDE is a fully autonomous, multi-agent financial analysis platform. You type a natural-language goal — *"Should I invest in NVIDIA long term?"* — and four specialist AI agents run in parallel, each pulling live data from real financial APIs via the **Model Context Protocol (MCP)**. The agents debate, a judge arbitrates, and you receive a structured, sourced, explainable decision in under 90 seconds.

It is not a chatbot wrapper around a financial dataset. It is a genuine autonomous pipeline: the orchestrator interprets intent, routes to agents, monitors confidence, triggers self-reflection loops when uncertain, runs adversarial debate between bull and bear cases, and applies macro regime adjustments before returning its final verdict.

---

<img src="Architecure Diagram.png" alt="AFDE arch" width="280" style="border-radius:12px"/>

## Core Architecture

### The Four-Agent Pipeline

Every single-stock analysis runs four specialist agents concurrently via `asyncio.gather`:

| Agent | Data Sources | What It Does |
|-------|-------------|--------------|
| **Fundamental** | Yahoo Finance · SEC EDGAR 10-K | P/E ratio, revenue growth, gross margins, FCF, debt/equity, analyst targets |
| **Sentiment** | Tavily News Search · Yahoo Finance | Recent earnings news, analyst ratings, price momentum, social sentiment signals |
| **Insider Trading** | SEC Form 4 filings | Cluster buy/sell detection across last 30 days, executive confidence scoring |
| **Macro** | FRED Treasury rates · FRED Fed Funds · CBOE VIX | Yield curve shape, Fed stance, volatility regime, sector rotation signals |

Each agent returns an `AgentSignal` — a typed Pydantic dataclass containing a score (0–100), confidence (0–100), summary, and a list of sourced data points with URLs.

### Self-Reflection Loop

The orchestrator checks whether the combined weighted confidence crosses a 70% threshold after each agent run. If not, the weakest agent re-runs with a deeper, more specific prompt. Up to 3 loops before the system proceeds with best available confidence.

### Adversarial Debate Engine

After agents complete, a three-round debate runs between independent Bull and Bear AI instances:
1. Opening statements with evidence from agent signals
2. Cross-examination round (each attacks the other's weakest claim)
3. Judge arbiter synthesises both cases with weighted scoring

Temperature is fixed at 0 for the judge to guarantee deterministic verdicts across re-runs.

### MCP Server Architecture

All five data sources are implemented as real MCP servers communicating via stdio:

```
market_data_server.py  → Yahoo Finance (live prices, fundamentals, analyst data)
sec_server.py          → SEC EDGAR (10-K filings, Form 4 insider transactions)
news_server.py         → Tavily (news search, earnings reports)
macro_server_proc.py   → FRED API (Treasury yields, Fed funds rate, VIX)
document_server.py     → PDF/CSV parser (annual reports, portfolio files)
```

This means every data tool can be inspected and tested independently via the MCP Inspector (`npx @modelcontextprotocol/inspector`), and any MCP-compatible client can connect to individual servers.

---

## Analysis Modes

### Single Stock
Full four-agent pipeline on one ticker. Supports natural language goals — the orchestrator extracts the ticker symbol and investment horizon using GPT-4o before routing.

### Compare Two
Both tickers run through the full pipeline independently and in parallel. A compare-judge then evaluates both result sets and declares a winner with strengths/weaknesses comparison.

### Macro Only
Uses SPY as a proxy to assess the overall market environment. Returns a BULLISH / NEUTRAL / BEARISH stance with sector rotation recommendations and equity/bond/cash allocation guidance.

### Portfolio
Accepts a CSV upload (`ticker, shares, cost_basis`). Computes position weights, identifies the top 3 holdings, runs individual analyses, and returns a portfolio-level concentration risk assessment with rebalancing recommendations.

### Document Upload
PDF annual reports or earnings filings are parsed by the document MCP server. Extracted financial figures override live Yahoo Finance data. Gaps are filled from live APIs. The system detects whether the upload is a 10-K, earnings call, or portfolio CSV automatically.

### URL Research Mode
Paste any public news article or Reddit thread URL. The system fetches and parses the content, creates a sentiment context block, and injects it as an additional signal into the sentiment agent.

---

## Features

### Real-time Streaming (SSE)
Every analysis streams live updates to the UI via Server-Sent Events. Stage transitions (parse → agents → debate → finalise), per-agent score updates, and individual signal lines appear in real time as the pipeline executes.

### Macro Regime Classifier
A daily APScheduler job runs at 7am and classifies the current market regime into one of five states: Risk-on bull, Rate shock, Stagflation, Recession, or Neutral — using FRED yield curve shape, VIX level, and Fed stance. Every subsequent analysis has its confidence adjusted based on regime.

### Agent Memory
Every analysis is stored in a SQLite `agent_memory` table. When the same ticker is analysed again, agents receive a structured context block describing what changed since last time — enabling progressive refinement and trend detection.

### Accuracy Backtesting
The entry price is stored at decision time for every BUY/HOLD/SELL verdict. A daily APScheduler job at 8:30am fetches current prices for decisions 30+ days old and computes actual returns. The accuracy dashboard shows BUY average 30-day return, win rate, and full outcome history.

### Price Alerts
Every BUY decision auto-registers a price alert at a 10% drop threshold. A daily monitoring job checks current prices and fires in-app notifications and email alerts when thresholds are breached.

### Email Notification System
Four email types via direct SMTP (no third-party service):
- **Verdict email** — sent immediately after every single-stock analysis
- **Morning brief** — 7am watchlist scan with price movement and signal reversal detection
- **Session summary** — sent on sign-out with all analyses from the current session
- **Price drop alerts** — triggered when a BUY stock drops 10%

All four types have per-user opt-in/opt-out toggles in the UI sidebar.

### Audit Trail
Every verdict includes a complete audit trail: which data sources were queried, which specific data points influenced each agent's score, and clickable links to the original SEC filings, FRED series, and Yahoo Finance pages.

### Plain English Mode
A "Explain this simply" toggle rewrites the entire analysis in jargon-free language for non-finance users — replacing P/E ratios, yield curves, and debt/equity with everyday analogies. Powered by a dedicated GPT-4o prompt with explicit translation rules for financial terminology.

### What Would Change This Decision?
A panel showing the three specific conditions — with current values and exact thresholds — that would flip the current verdict. Includes a weekly monitoring tip. Gives users a concrete action list rather than a static snapshot.

### Follow-up Questions
Three contextual follow-up questions generated after every analysis, specific to the actual ticker, signals found, and decision returned. Clickable to immediately re-run analysis with that question.

### User Dashboard
Per-user analytics page showing: decision breakdown bars, 30-day activity heatmap, agent performance averages, accuracy stats, recent analysis table, active alerts, and quick re-analyse shortcuts for previously analysed tickers.

### Ticker Autocomplete
Curated database of 25 popular tickers with company logos (via Clearbit) and sectors. Live price and percentage change loaded from Yahoo Finance for watchlist items.

### PDF Report Export
Professional dark-themed PDF export via ReportLab (pure Python, no system dependencies). Includes verdict card, agent signal table with source links, bull/bear debate cards, judge verdict, and data source citations.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **LLM / Agents** | OpenAI GPT-4o · OpenAI Agents SDK (`openai-agents`) |
| **Agent Protocol** | Model Context Protocol (MCP) via `mcp` SDK |
| **Web Framework** | Flask 3.0 · Flask-Login · Server-Sent Events (SSE) |
| **Data — Market** | yfinance (Yahoo Finance) |
| **Data — Macro** | FRED API (St. Louis Fed) |
| **Data — News** | Tavily Search API |
| **Data — Filings** | SEC EDGAR REST API |
| **Data — Documents** | pdfplumber · pandas |
| **Task Scheduling** | APScheduler (BackgroundScheduler) |
| **Database** | SQLite (local) · PostgreSQL via psycopg2 (production) |
| **PDF Generation** | ReportLab |
| **Email** | Python smtplib (direct SMTP, no third-party) |
| **Validation** | Pydantic v2 |
| **Production** | Gunicorn · Railway (deployment target) |
| **Frontend** | Vanilla JS · CSS animations · Canvas particles · SSE |

---

## Prompt Engineering Approach

AFDE uses a multi-layer prompting strategy:

**Structured JSON outputs** — every agent prompt specifies an exact JSON schema in the system prompt. GPT-4o's `response_format: json_object` mode enforces structure, preventing free-text contamination in agent outputs.

**Role specialisation** — each agent's system prompt establishes a narrow specialist identity: "You are a fundamental analysis expert for AFDE. Your job is exclusively to assess financial health metrics." This prevents cross-contamination between analysis domains.

**Adversarial prompting** — the debate engine uses explicit adversarial framing: Bull instance is told "argue the strongest possible bull case based on the evidence below, then identify the two weakest points in the bear case." Bear instance vice versa.

**Temperature control** — analysis agents run at temperature 0.2 (enough creativity for synthesis, low enough for consistency). The debate judge runs at temperature 0 (fully deterministic — same input always produces same verdict).

**Self-reflection trigger** — the orchestrator prompt explicitly includes: "If your combined weighted confidence is below 70%, identify the agent with the weakest signal and specify exactly what additional data would increase confidence." This produces structured re-run instructions rather than vague uncertainty.

**Memory injection** — prior agent scores are injected into agent system prompts as structured context blocks: "PRIOR ANALYSIS (14 days ago): Fundamental score was 72/100 citing X. Current query should note any changes to these metrics."

---

## Project Structure

```
afde/
├── app.py                    Flask application — all routes, auth, APScheduler
├── engine.py                 Core pipeline coordinator
├── config.py                 Types, enums, Pydantic models, all system prompts
├── document_processor.py     PDF/CSV → DocumentContext
├── afde_agents/
│   ├── orchestrator_agent.py Goal parsing, mode routing, self-reflection, memory
│   ├── fundamental_agent.py  Yahoo Finance + SEC EDGAR via MCP
│   ├── sentiment_agent.py    Tavily news search via MCP
│   ├── insider_agent.py      SEC Form 4 via MCP
│   └── macro_agent.py        FRED + VIX via MCP
├── mcp_servers/
│   ├── market_data_server.py Yahoo Finance MCP server
│   ├── sec_server.py         SEC EDGAR MCP server
│   ├── macro_server_proc.py  FRED macro MCP server
│   ├── news_server.py        Tavily news MCP server
│   └── document_server.py    PDF/CSV MCP server
├── debate/
│   └── debate_engine.py      Bull · Bear · Judge, 3-round adversarial debate
├── features/
│   ├── streaming.py          SSE event queue
│   ├── macro_regime.py       Daily macro regime classifier
│   ├── memory.py             SQLite agent memory
│   ├── alerts.py             Price alert monitoring
│   ├── audit.py              Source URL audit trail builder
│   ├── backtest.py           30-day outcome tracker
│   ├── dashboard.py          User analytics data aggregator
│   ├── email_notifications.py Verdict · brief · signout · alert emails
│   ├── pdf_export.py         ReportLab PDF generator
│   ├── plain_english.py      Plain language rewriter
│   └── ticker_search.py      Autocomplete + logo lookup
├── output/
│   └── formatter.py          Final decision builder and JSON serialiser
├── templates/
│   ├── index.html            Main app UI with all animations
│   ├── dashboard.html        User analytics dashboard
│   ├── login.html            Login page
│   └── register.html         Registration page
└── static/
    ├── logo_full.jpg         Full logo with text (login/register)
    └── logo_icon.jpg         Shield icon (nav bar)
```

---


## Environment Variables

```env
OPENAI_API_KEY=sk-...
FRED_API_KEY=your_fred_key
TAVILY_API_KEY=tvly-...
FLASK_SECRET_KEY=long-random-string
SMTP_USER=your@gmail.com
SMTP_PASS=app-password-16-chars
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
BRIEF_FROM=AFDE <your@gmail.com>
# DATABASE_URL set automatically by Railway
```

---

*AI-generated analysis for educational purposes only. Not financial advice.*
