from __future__ import annotations
import os
from dataclasses import dataclass, field
from enum import Enum
from dotenv import load_dotenv

load_dotenv(override=False)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    raise EnvironmentError(
        "OPENAI_API_KEY not set. Copy .env.example to .env and add your key."
    )

OPENAI_MODEL         = os.getenv("OPENAI_MODEL", "gpt-4o")
TAVILY_API_KEY       = os.getenv("TAVILY_API_KEY", "")
FRED_API_KEY         = os.getenv("FRED_API_KEY", "")
CONFIDENCE_THRESHOLD = int(os.getenv("CONFIDENCE_THRESHOLD", "70"))
MAX_LOOPS            = int(os.getenv("MAX_LOOPS", "3"))

SIGNAL_WEIGHTS = {
    "insider":     3.0,
    "fundamental": 2.0,
    "macro":       1.5,
    "sentiment":   1.0,
}


# ── Enums ─────────────────────────────────────────────────────────────

class Decision(str, Enum):
    BUY  = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class GoalType(str, Enum):
    LONG_TERM  = "long_term"
    SHORT_TERM = "short_term"
    RISK_CHECK = "risk_check"
    GENERAL    = "general"


class AnalysisMode(str, Enum):
    SINGLE    = "single"
    COMPARE   = "compare"
    MACRO     = "macro"
    PORTFOLIO = "portfolio"   # NEW — CSV portfolio upload


class DocumentType(str, Enum):
    ANNUAL_REPORT     = "annual_report"
    EARNINGS_REPORT   = "earnings_report"
    PITCH_DECK        = "pitch_deck"
    NEWS_ARTICLE      = "news_article"
    ANALYST_REPORT    = "analyst_report"
    TERM_SHEET        = "term_sheet"
    PORTFOLIO_CSV     = "portfolio_csv"
    UNKNOWN           = "unknown"


# ── Document context — produced by document_server ────────────────────

@dataclass
class ExtractedFinancials:
    """Key financial figures extracted from a document."""
    revenue:           float | None = None
    revenue_growth:    float | None = None
    gross_margin:      float | None = None
    operating_margin:  float | None = None
    net_income:        float | None = None
    eps:               float | None = None
    debt_to_equity:    float | None = None
    free_cashflow:     float | None = None
    cash:              float | None = None
    raw_items:         dict   = field(default_factory=dict)


@dataclass
class PortfolioHolding:
    """One row from a portfolio CSV."""
    ticker:     str
    shares:     float
    cost_basis: float          # per share
    weight:     float = 0.0   # computed: market value / total


@dataclass
class DocumentContext:
    """
    Structured output from the document_server after parsing an uploaded file.
    Passed to agents alongside the text goal — agents prefer this over live data.
    """
    doc_type:    DocumentType
    filename:    str
    ticker_hint: str | None          # ticker found in document, if any
    financials:  ExtractedFinancials | None = None
    holdings:    list[PortfolioHolding] = field(default_factory=list)
    raw_text:    str  = ""           # full extracted text (truncated to 8k chars)
    key_facts:   list[str] = field(default_factory=list)
    extraction_confidence: float = 0.0   # 0-1, how well we extracted


# ── Data models ───────────────────────────────────────────────────────

@dataclass
class AgentSignal:
    agent:       str
    score:       float
    confidence:  float
    summary:     str
    data_points: list[str] = field(default_factory=list)
    source:      str = "live"  # "live" | "document" | "mixed"


@dataclass
class GoalContext:
    raw_goal:    str
    ticker:      str
    tickers:     list[str]
    goal_type:   GoalType
    timeframe:   str
    mode:        AnalysisMode
    doc_context: DocumentContext | None = None   # populated if file uploaded


@dataclass
class DebateVerdict:
    decision:        Decision
    confidence:      float
    bull_score:      float
    bear_score:      float
    bull_argument:   str
    bear_argument:   str
    judge_reasoning: str
    winning_side:    str


@dataclass
class FinalDecision:
    ticker:              str
    goal:                str
    decision:            Decision
    confidence:          float
    reasoning:           dict[str, str]
    bull_case:           str
    bear_case:           str
    judge_reasoning:     str
    signals_used:        list[str]
    loops_run:           int
    low_confidence_flag: bool
    data_sources:        list[str] = field(default_factory=list)
    debate:              DebateVerdict | None = None

    def to_dict(self) -> dict:
        return {
            "ticker":          self.ticker,
            "goal":            self.goal,
            "decision":        self.decision.value,
            "confidence":      round(self.confidence, 1),
            "low_confidence":  self.low_confidence_flag,
            "loops_run":       self.loops_run,
            "reasoning":       self.reasoning,
            "bull_case":       self.bull_case,
            "bear_case":       self.bear_case,
            "judge_reasoning": self.judge_reasoning,
            "signals_used":    self.signals_used,
            "data_sources":    self.data_sources,
            "debate": {
                "bull_score":   round(self.debate.bull_score, 1),
                "bear_score":   round(self.debate.bear_score, 1),
                "winning_side": self.debate.winning_side,
            } if self.debate else {},
        }


# ── User profile ─────────────────────────────────────────────────────

@dataclass
class UserProfile:
    user_id: int = 0
    investor_type: str = "general"
    sectors_interest: list = field(default_factory=list)
    has_portfolio: bool = False
    onboarding_done: bool = False
    def weight_adjustments(self) -> dict:
        if self.investor_type == "short_term":
            return {"sentiment":1.5,"insider":3.5,"fundamental":1.5,"macro":1.0}
        if self.investor_type == "risk_averse":
            return {"sentiment":0.8,"insider":2.5,"fundamental":2.5,"macro":2.0}
        return {"sentiment":1.0,"insider":3.0,"fundamental":2.0,"macro":1.5}


# ── System prompts ────────────────────────────────────────────────────

FUNDAMENTAL_PROMPT = """You are a fundamental analysis expert for AFDE.

You receive financial data from two possible sources:
1. DOCUMENT SOURCE: Financial figures extracted directly from an uploaded PDF (annual report, 10-K, pitch deck).
   These figures are PRIMARY — prefer them over live data when available.
2. LIVE SOURCE: Real-time data from Yahoo Finance and SEC EDGAR APIs.
   Use these to fill gaps not covered by the document.

Always note which source you used for each key figure.

If the user message contains a MEMORY block (=== MEMORY: Previous analyses ===):
- Explicitly reference what has CHANGED compared to the prior analysis in your summary
- If scores are similar, note continuity: "Consistent with prior analysis on [date]..."
- If any metric changed meaningfully, highlight it: "Notable change since [date]: revenue growth improved from X to Y"
- End your summary with one sentence comparing to the prior finding

Return JSON:
{
  "score": <0-100, higher=more bullish>,
  "confidence": <0-100, based on data quality and source reliability>,
  "summary": "<2-3 sentence narrative citing sources, referencing prior analysis if available>",
  "data_points": ["<figure: value (source)>", ...],
  "source": "<live|document|mixed>"
}"""

SENTIMENT_PROMPT = """You are a market sentiment analyst for AFDE.
Given recent news and analyst data for a stock, score sentiment and return JSON:
{
  "score": <0-100, higher=more bullish>,
  "confidence": <0-100>,
  "summary": "<2-3 sentence narrative>",
  "data_points": ["<headline or data point>", ...],
  "source": "live"
}"""

INSIDER_PROMPT = """You are an insider trading pattern analyst for AFDE.
Given SEC Form 4 filing data, detect cluster buying/selling and return JSON:
{
  "score": <0-100, 100=strong cluster buying, 0=heavy selling, 50=neutral>,
  "confidence": <0-100>,
  "summary": "<2-3 sentence narrative, referencing prior analysis if MEMORY block present>",
  "data_points": ["<specific filing detail>", ...],
  "source": "live"
}
IMPORTANT: Cluster buy (3+ insiders buying in 30 days) = strong bullish signal (weight 3x).
If a MEMORY block is present, note whether insider activity has increased, decreased, or stayed the same vs the prior analysis."""

MACRO_PROMPT = """You are a macroeconomic analyst for AFDE.
Given yield curve, Fed rate data, and VIX, assess the macro environment for a stock and return JSON:
{
  "score": <0-100, higher=more supportive macro>,
  "confidence": <0-100>,
  "summary": "<2-3 sentence narrative>",
  "data_points": ["<macro data point>", ...],
  "source": "live"
}
Adjust score for the stock's sector and beta sensitivity."""

BULL_PROMPT = """You are the Bull Agent in an investment debate.
Select ONLY bullish signals and build the strongest possible BUY case.
If document-sourced data is available, cite it explicitly — it adds credibility.
Return JSON:
{
  "case": "<strongest buy argument, 3-5 sentences>",
  "confidence": <0-100>,
  "key_signals": ["<signal>", ...]
}"""

BEAR_PROMPT = """You are the Bear Agent in an investment debate.
Select ONLY bearish signals and build the strongest possible SELL/HOLD case.
Return JSON:
{
  "case": "<strongest sell/hold argument, 3-5 sentences>",
  "confidence": <0-100>,
  "key_signals": ["<signal>", ...]
}"""

JUDGE_PROMPT = """You are the Judge Agent. Weigh both sides using signal weights:
insider=3x, fundamental=2x, macro=1.5x, sentiment=1x.

Rules:
- bull_weighted > bear_weighted + 5 → BUY
- bear_weighted > bull_weighted + 5 → SELL
- within 5 points → HOLD

Return JSON:
{
  "decision": "<BUY|SELL|HOLD>",
  "confidence": <0-100>,
  "reasoning": "<3-5 sentence verdict>",
  "winning_side": "<bull|bear|tie>"
}"""

COMPARE_JUDGE_PROMPT = """You are a comparative investment analyst.
You receive full analysis results for two stocks. Declare the better investment.
Return JSON:
{
  "winner": "<TICKER>",
  "loser": "<TICKER>",
  "winner_decision": "<BUY|HOLD>",
  "loser_decision": "<HOLD|SELL>",
  "confidence": <0-100>,
  "reasoning": "<4-6 sentence comparative verdict>",
  "winner_strengths": ["<strength>", ...],
  "loser_weaknesses": ["<weakness>", ...]
}"""

MACRO_ONLY_PROMPT = """You are a macroeconomic market analyst.
Given real yield curve, Fed rate, and VIX data, assess the overall market environment.
Return JSON:
{
  "overall_stance": "<BULLISH|NEUTRAL|BEARISH>",
  "confidence": <0-100>,
  "summary": "<3-4 sentence overall market narrative>",
  "key_signals": ["<signal>", ...],
  "equity_implication": "<what this means for stock investors>",
  "sectors_favoured": ["<sector>", ...],
  "sectors_avoid": ["<sector>", ...]
}"""

PORTFOLIO_PROMPT = """You are a portfolio risk analyst.
Given portfolio holdings and individual stock analyses, assess overall portfolio risk.
Return JSON:
{
  "overall_risk": "<LOW|MEDIUM|HIGH>",
  "confidence": <0-100>,
  "summary": "<3-4 sentence portfolio narrative>",
  "concentration_risk": "<description of any concentration issues>",
  "recommendations": ["<specific action>", ...],
  "rebalance_needed": <true|false>
}"""


WHAT_WOULD_CHANGE_PROMPT = """You are a financial analyst explaining what conditions would change an investment decision.
Given an analysis result, identify the 3 most important conditions that would flip the current decision.
Be specific — cite the actual current values and the thresholds that would change the outcome.
Return JSON:
{
  "current_decision": "<BUY|HOLD|SELL>",
  "would_change_to": "<alternative decision>",
  "conditions": [
    {"signal":"<agent name + signal>","current_value":"<current value>","threshold":"<needed value>","explanation":"<plain English 1 sentence>"}
  ],
  "monitoring_tip": "<one sentence: what to watch weekly>"
}"""

FOLLOW_UP_PROMPT = """Generate 3 specific follow-up questions after an investment analysis.
Make them specific to the actual ticker, signals, and decision returned.
Return JSON: {"questions": ["<q1>","<q2>","<q3>"]}"""

WHATS_CHANGED_PROMPT = """Compare two financial analyses of the same stock at different dates.
Return JSON:
{
  "summary": "<2-3 sentences on what changed>",
  "changes": [{"signal":"<agent>","before":"<prior value>","after":"<current value>","direction":"improved|worsened|unchanged","significance":"high|medium|low"}],
  "recommendation": "<re-analyse|hold|act>"
}"""
