"""
output/formatter.py — Structured output for all 4 analysis modes.
"""
from __future__ import annotations
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import (
    AgentSignal, GoalContext, DebateVerdict,
    FinalDecision, Decision, SIGNAL_WEIGHTS,
    DocumentContext,
)

console = Console()


def build_final_decision(
    goal: GoalContext,
    signals: dict[str, AgentSignal],
    verdict: DebateVerdict,
    loops_run: int,
    confidence: float,
) -> FinalDecision:
    reasoning    = {name: sig.summary for name, sig in signals.items()}
    signals_used = [
        f"{name.upper()}: {dp}"
        for name, sig in signals.items()
        for dp in sig.data_points[:2]
    ]

    # Track data sources
    sources = list({sig.source for sig in signals.values() if sig.source not in ("error",)})
    if goal.doc_context:
        sources.append(f"document:{goal.doc_context.filename}")

    return FinalDecision(
        ticker=goal.ticker,
        goal=goal.raw_goal,
        decision=verdict.decision,
        confidence=round(verdict.confidence, 1),
        reasoning=reasoning,
        bull_case=verdict.bull_argument,
        bear_case=verdict.bear_argument,
        judge_reasoning=verdict.judge_reasoning,
        signals_used=signals_used,
        loops_run=loops_run,
        low_confidence_flag=confidence < 70,
        data_sources=sources,
        debate=verdict,
    )


def print_decision(fd: FinalDecision) -> None:
    color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(fd.decision.value, "white")

    console.print(Panel(
        f"[bold {color}]{fd.decision.value}[/bold {color}]  —  {fd.confidence:.0f}% confidence\n"
        f"Ticker: {fd.ticker}  |  Loops: {fd.loops_run}  |  Sources: {', '.join(fd.data_sources)}"
        + ("  |  [bold red]LOW CONFIDENCE[/bold red]" if fd.low_confidence_flag else ""),
        title=f"AFDE — {fd.ticker}",
        border_style=color,
        padding=(1, 4),
    ))

    tbl = Table(show_header=True, header_style="bold cyan")
    tbl.add_column("Agent",   min_width=14)
    tbl.add_column("Weight",  min_width=6,  justify="center")
    tbl.add_column("Source",  min_width=10, justify="center")
    tbl.add_column("Summary", min_width=50)

    for name, summary in fd.reasoning.items():
        tbl.add_row(
            name.upper(),
            f"{SIGNAL_WEIGHTS.get(name, 1.0)}×",
            fd.reasoning.get(f"{name}_source", "—"),
            summary[:70] + "..." if len(summary) > 70 else summary,
        )
    console.print(tbl)

    if fd.debate:
        console.print(Panel(
            f"[green]Bull:[/green] {fd.bull_case}\n\n"
            f"[red]Bear:[/red]  {fd.bear_case}\n\n"
            f"[bold]Judge:[/bold] {fd.judge_reasoning}",
            title="Debate Summary",
            border_style="magenta",
        ))


def to_json(fd: FinalDecision) -> dict:
    return {
        "mode":            "single",
        "ticker":          fd.ticker,
        "goal":            fd.goal,
        "decision":        fd.decision.value,
        "confidence":      fd.confidence,
        "low_confidence":  fd.low_confidence_flag,
        "loops_run":       fd.loops_run,
        "timestamp":       datetime.now().isoformat(),
        "data_sources":    fd.data_sources,
        "reasoning":       fd.reasoning,
        "bull_case":       fd.bull_case,
        "bear_case":       fd.bear_case,
        "judge_reasoning": fd.judge_reasoning,
        "signals_used":    fd.signals_used,
        "debate": {
            "bull_score":   round(fd.debate.bull_score, 1),
            "bear_score":   round(fd.debate.bear_score, 1),
            "winning_side": fd.debate.winning_side,
        } if fd.debate else {},
        "disclaimer": "AI-generated analysis only. Not financial advice.",
    }