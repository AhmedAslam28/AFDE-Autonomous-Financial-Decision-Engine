"""
agents/orchestrator_agent.py

Orchestrator Agent — autonomous brain of AFDE.

Modes:
  SINGLE    → one ticker, normal agent flow + debate
  COMPARE   → two tickers, run both independently
  MACRO     → no ticker, market-wide macro analysis
  PORTFOLIO → CSV upload, analyse top holdings by weight
"""
from __future__ import annotations
import json
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI
from rich.console import Console

from features.memory import get_memory_context
from config import (
    OPENAI_API_KEY, OPENAI_MODEL,
    CONFIDENCE_THRESHOLD, MAX_LOOPS, SIGNAL_WEIGHTS,
    AgentSignal, GoalContext, GoalType, AnalysisMode,
    DocumentContext, DocumentType,
)
from afde_agents.fundamental_agent import run_fundamental_agent
from afde_agents.sentiment_agent   import run_sentiment_agent
from afde_agents.insider_agent     import run_insider_agent
from afde_agents.macro_agent       import run_macro_agent

_llm     = AsyncOpenAI(api_key=OPENAI_API_KEY)
console  = Console()

_AGENT_RUNNERS = {
    "fundamental": run_fundamental_agent,
    "sentiment":   run_sentiment_agent,
    "insider":     run_insider_agent,
    "macro":       run_macro_agent,
}

_AGENT_SELECTION: dict[GoalType, list[str]] = {
    GoalType.LONG_TERM:  ["fundamental", "macro", "insider"],
    GoalType.SHORT_TERM: ["sentiment", "insider", "macro"],
    GoalType.RISK_CHECK: ["fundamental", "sentiment", "insider", "macro"],
    GoalType.GENERAL:    ["fundamental", "sentiment", "insider", "macro"],
}


async def parse_goal(raw_goal: str, doc_context: DocumentContext | None = None) -> GoalContext:
    """Use LLM to extract tickers, mode, goal type from natural language + optional document."""

    doc_hint = ""
    if doc_context:
        if doc_context.doc_type == DocumentType.PORTFOLIO_CSV:
            doc_hint = f"\nDocument uploaded: Portfolio CSV with {len(doc_context.holdings)} holdings."
        else:
            doc_hint = (
                f"\nDocument uploaded: {doc_context.doc_type.value} "
                f"(ticker hint: {doc_context.ticker_hint or 'unknown'})"
            )

    resp = await _llm.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": (
                "Extract financial goal info. Return JSON:\n"
                "- tickers: list of uppercase stock ticker symbols ([] if none)\n"
                "- mode: 'single' | 'compare' | 'macro' | 'portfolio'\n"
                "  portfolio = user uploaded a portfolio file\n"
                "  macro = market-wide question, no specific stock\n"
                "- goal_type: long_term | short_term | risk_check | general\n"
                "- timeframe: string\n\n"
                "Examples:\n"
                "  'Compare MSFT vs GOOGL' → mode=compare, tickers=[MSFT,GOOGL]\n"
                "  'Is S&P 500 bullish?'   → mode=macro, tickers=[]\n"
                "  'Analyse my portfolio'  → mode=portfolio, tickers=[]\n"
                "  'Should I buy TSLA?'    → mode=single, tickers=[TSLA]"
            )},
            {"role": "user", "content": raw_goal + doc_hint},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    parsed  = json.loads(resp.choices[0].message.content)
    tickers = [t.upper().strip() for t in parsed.get("tickers", []) if t.strip()]
    raw_mode = parsed.get("mode", "single").lower()

    # Override mode if portfolio CSV was uploaded
    if doc_context and doc_context.doc_type == DocumentType.PORTFOLIO_CSV:
        mode    = AnalysisMode.PORTFOLIO
        tickers = [h.ticker for h in (doc_context.holdings or [])]
        ticker  = tickers[0] if tickers else "PORTFOLIO"
    elif raw_mode == "macro" or len(tickers) == 0:
        mode   = AnalysisMode.MACRO
        ticker = "MACRO"
        tickers = []
    elif raw_mode == "compare" or len(tickers) >= 2:
        mode    = AnalysisMode.COMPARE
        tickers = tickers[:2]
        ticker  = tickers[0]
    else:
        mode   = AnalysisMode.SINGLE
        ticker = tickers[0] if tickers else None

        # If document has ticker hint and user didn't specify, use document's ticker
        if not ticker and doc_context and doc_context.ticker_hint:
            ticker  = doc_context.ticker_hint
            tickers = [ticker]

        if not ticker:
            raise ValueError(
                f"Could not extract a ticker from: '{raw_goal}'\n"
                "Try: 'Should I invest in AAPL?' or 'Compare MSFT vs GOOGL'\n"
                "Or upload a financial document with a ticker visible."
            )

    goal_type_map = {
        "long_term":  GoalType.LONG_TERM,
        "short_term": GoalType.SHORT_TERM,
        "risk_check": GoalType.RISK_CHECK,
        "general":    GoalType.GENERAL,
    }

    return GoalContext(
        raw_goal=raw_goal,
        ticker=ticker,
        tickers=tickers,
        goal_type=goal_type_map.get(parsed.get("goal_type", "general"), GoalType.GENERAL),
        timeframe=parsed.get("timeframe", "not specified"),
        mode=mode,
        doc_context=doc_context,
    )


def _weighted_confidence(signals: dict[str, AgentSignal]) -> float:
    total_w = total_c = 0.0
    for name, sig in signals.items():
        w = SIGNAL_WEIGHTS.get(name, 1.0)
        total_c += sig.confidence * w
        total_w += w
    return (total_c / total_w) if total_w else 0.0


def _weakest_agent(signals: dict[str, AgentSignal]) -> str:
    return min(signals, key=lambda n: signals[n].confidence)


async def _run_agents(
    names: list[str],
    ticker: str,
    context: str,
    doc_context: DocumentContext | None = None,
) -> dict[str, AgentSignal]:
    """Run selected agents concurrently, passing doc_context to each."""
    tasks = {
        n: _AGENT_RUNNERS[n](ticker, context, doc_context)
        for n in names if n in _AGENT_RUNNERS
    }
    done = await asyncio.gather(*tasks.values(), return_exceptions=True)
    result = {}
    for name, outcome in zip(tasks.keys(), done):
        if isinstance(outcome, Exception):
            console.print(f"[red]  Agent '{name}' failed: {outcome}[/red]")
            result[name] = AgentSignal(
                agent=name, score=50.0, confidence=5.0,
                summary=f"Failed: {outcome}", data_points=[], source="error"
            )
        else:
            result[name] = outcome
    return result


async def _run_single_ticker(
    ticker: str,
    goal: GoalContext,
    doc_context: DocumentContext | None = None,
    memory_context: str = "",
) -> tuple[dict[str, AgentSignal], int, float]:
    """Run full agent loop with self-reflection for one ticker."""
    selected   = _AGENT_SELECTION[goal.goal_type]
    context    = f"Goal: {goal.raw_goal} | Ticker: {ticker}"
    if doc_context:
        context += f" | Document: {doc_context.filename} ({doc_context.doc_type.value})"
    if memory_context:
        context += memory_context   # inject previous analysis into all agent prompts

    signals    = await _run_agents(selected, ticker, context, doc_context)
    loops      = 1
    confidence = _weighted_confidence(signals)
    console.print(f"[yellow]  {ticker} loop {loops} confidence: {confidence:.1f}%[/yellow]")

    while confidence < CONFIDENCE_THRESHOLD and loops < MAX_LOOPS:
        weakest = _weakest_agent(signals)
        console.print(f"[yellow]  Re-running '{weakest}' for {ticker} (confidence {confidence:.1f}%)[/yellow]")
        deeper = await _run_agents(
            [weakest], ticker,
            context + "\n[DEEPER PASS: expand time window, use more granular analysis]",
            doc_context,
        )
        signals.update(deeper)
        loops += 1
        confidence = _weighted_confidence(signals)
        console.print(f"[yellow]  {ticker} loop {loops} confidence: {confidence:.1f}%[/yellow]")

    if confidence < CONFIDENCE_THRESHOLD:
        console.print(f"[red]  Max loops reached for {ticker}: {confidence:.1f}%[/red]")

    return signals, loops, confidence


async def run_orchestrator(
    raw_goal: str,
    doc_context: DocumentContext | None = None,
    user_id: int = 0,
) -> tuple[GoalContext, dict[str, AgentSignal], int, float]:
    """
    Main orchestrator. Returns (goal_context, signals, loops_run, confidence).
    For COMPARE: signals keys are prefixed with ticker e.g. 'MSFT_fundamental'.
    For PORTFOLIO: signals contain top-3 holdings analysed.
    """
    goal = await parse_goal(raw_goal, doc_context)

    # Fetch memory AFTER real ticker is known from LLM parse (not regex guessing)
    memory_context = ""
    if goal.ticker and goal.ticker not in ("UNKNOWN", "MACRO", "PORTFOLIO"):
        memory_context = get_memory_context(goal.ticker, user_id)
        if memory_context:
            console.print(f"[dim cyan]  Memory: prior analyses found for {goal.ticker}[/dim cyan]")

    doc_label = f" | Doc: {doc_context.filename}" if doc_context else ""
    console.print(
        f"\n[green]Mode:[/green] {goal.mode.value}  "
        f"[green]Tickers:[/green] {goal.tickers or 'N/A'}  "
        f"[green]Type:[/green] {goal.goal_type.value}{doc_label}"
    )

    # ── MACRO ────────────────────────────────────────────────────────
    if goal.mode == AnalysisMode.MACRO:
        console.print("[cyan]Macro-only mode: using SPY as market proxy[/cyan]")
        signals, loops, confidence = await _run_single_ticker("SPY", goal, doc_context)
        return goal, signals, loops, confidence

    # ── SINGLE ───────────────────────────────────────────────────────
    if goal.mode == AnalysisMode.SINGLE:
        selected = _AGENT_SELECTION[goal.goal_type]
        console.print(f"[cyan]Running: {', '.join(selected)} for {goal.ticker}[/cyan]")
        signals, loops, confidence = await _run_single_ticker(
            goal.ticker, goal, doc_context, memory_context=memory_context
        )
        return goal, signals, loops, confidence

    # ── COMPARE ──────────────────────────────────────────────────────
    if goal.mode == AnalysisMode.COMPARE:
        t1, t2 = goal.tickers[0], goal.tickers[1]
        console.print(f"[cyan]Comparing {t1} vs {t2} in parallel[/cyan]")
        (sig1, loops1, conf1), (sig2, loops2, conf2) = await asyncio.gather(
            _run_single_ticker(t1, goal, doc_context),
            _run_single_ticker(t2, goal, doc_context),
        )
        merged = {}
        for name, sig in sig1.items():
            merged[f"{t1}_{name}"] = sig
        for name, sig in sig2.items():
            merged[f"{t2}_{name}"] = sig
        return goal, merged, max(loops1, loops2), (conf1 + conf2) / 2

    # ── PORTFOLIO ────────────────────────────────────────────────────
    if goal.mode == AnalysisMode.PORTFOLIO:
        holdings = doc_context.holdings if doc_context else []
        if not holdings:
            raise ValueError("Portfolio mode requires a CSV file with holdings.")

        # Compute portfolio weights using cost basis * shares as proxy for value
        total_value = sum(h.shares * h.cost_basis for h in holdings) or 1
        for h in holdings:
            h.weight = round((h.shares * h.cost_basis) / total_value, 4)

        # Analyse top 3 holdings by weight
        top3 = sorted(holdings, key=lambda h: h.weight, reverse=True)[:3]
        console.print(f"[cyan]Portfolio mode: analysing top 3 holdings: {[h.ticker for h in top3]}[/cyan]")

        tasks = [
            _run_single_ticker(h.ticker, goal, None)
            for h in top3
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged = {}
        total_loops = 1
        total_conf  = 0.0
        for h, outcome in zip(top3, results):
            if isinstance(outcome, Exception):
                console.print(f"[red]  {h.ticker} failed: {outcome}[/red]")
                continue
            sigs, loops, conf = outcome
            for name, sig in sigs.items():
                merged[f"{h.ticker}_{name}"] = sig
            total_loops = max(total_loops, loops)
            total_conf += conf * h.weight

        return goal, merged, total_loops, min(total_conf, 100.0)

    raise ValueError(f"Unknown mode: {goal.mode}")