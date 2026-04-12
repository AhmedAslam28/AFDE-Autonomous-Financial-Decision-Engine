"""
debate/debate_engine.py

Bull vs Bear debate engine.
Uses direct OpenAI calls (no MCP needed — debate is reasoning only, no tool calls).

Round 1: Bull and Bear build independent cases from all agent signals.
Round 2: Each sees the other's case and prepares a counter.
Round 3: Judge applies evidence-weighted rules and delivers verdict.
"""
from __future__ import annotations
import json
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI
from rich.console import Console

from config import (
    OPENAI_API_KEY, OPENAI_MODEL,
    BULL_PROMPT, BEAR_PROMPT, JUDGE_PROMPT,
    SIGNAL_WEIGHTS, AgentSignal, Decision, DebateVerdict,
)

_llm    = AsyncOpenAI(api_key=OPENAI_API_KEY)
console = Console()


def _signals_to_text(signals: dict[str, AgentSignal]) -> str:
    lines = []
    for name, sig in signals.items():
        w = SIGNAL_WEIGHTS.get(name, 1.0)
        lines.append(f"\n[{name.upper()} — weight {w}×  |  source: {sig.source}]")
        lines.append(f"  Score (0-100 bullish): {sig.score:.1f}")
        lines.append(f"  Confidence: {sig.confidence:.1f}%")
        lines.append(f"  Summary: {sig.summary}")
        for dp in sig.data_points[:3]:
            lines.append(f"  • {dp}")
    return "\n".join(lines)


async def _call_side(role_prompt: str, ticker: str, signals_text: str, counter: str = "") -> dict:
    counter_section = f"\nOpponent's case to counter:\n{counter}" if counter else ""
    resp = await _llm.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": role_prompt},
            {"role": "user", "content": (
                f"Ticker: {ticker.upper()}\n\nAll agent signals:\n{signals_text}{counter_section}"
            )},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return json.loads(resp.choices[0].message.content)


async def _call_judge(
    ticker: str,
    signals: dict[str, AgentSignal],
    bull: dict,
    bear: dict,
) -> dict:
    bull_w = bear_w = 0.0
    lines  = []
    for name, sig in signals.items():
        w = SIGNAL_WEIGHTS.get(name, 1.0)
        bc = (sig.score / 100) * w
        sc = ((100 - sig.score) / 100) * w
        bull_w += bc
        bear_w += sc
        lines.append(f"  {name}: score={sig.score:.0f}, weight={w}×, bull={bc:.2f}, bear={sc:.2f}, source={sig.source}")

    total    = bull_w + bear_w or 1
    bull_pct = round((bull_w / total) * 100, 1)
    bear_pct = round(100 - bull_pct, 1)

    prompt = (
        f"Ticker: {ticker.upper()}\n\nWeighted signal breakdown:\n" + "\n".join(lines) +
        f"\n\nBull weighted total: {bull_pct}%"
        f"\nBear weighted total: {bear_pct}%"
        f"\n\nBull case (confidence {bull.get('confidence', 50):.0f}%):\n{bull.get('case', '')}"
        f"\n\nBear case (confidence {bear.get('confidence', 50):.0f}%):\n{bear.get('case', '')}"
        f"\n\nApply decision rules and return verdict as JSON."
    )
    resp = await _llm.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    out = json.loads(resp.choices[0].message.content)
    out["_bull_pct"] = bull_pct
    out["_bear_pct"] = bear_pct
    return out


async def run_debate_engine(
    ticker: str,
    signals: dict[str, AgentSignal],
) -> DebateVerdict:
    """Run full 3-round Bull vs Bear debate and return verdict."""
    signals_text = _signals_to_text(signals)
    console.print(f"\n[magenta]Debate starting for {ticker.upper()}[/magenta]")

    console.print("[magenta]  Round 1: independent cases...[/magenta]")
    bull1, bear1 = await asyncio.gather(
        _call_side(BULL_PROMPT, ticker, signals_text),
        _call_side(BEAR_PROMPT, ticker, signals_text),
    )

    console.print("[magenta]  Round 2: cross-examination...[/magenta]")
    bull2, bear2 = await asyncio.gather(
        _call_side(BULL_PROMPT, ticker, signals_text, counter=bear1.get("case", "")),
        _call_side(BEAR_PROMPT, ticker, signals_text, counter=bull1.get("case", "")),
    )

    console.print("[magenta]  Round 3: judge deliberating...[/magenta]")
    judge = await _call_judge(ticker, signals, bull2, bear2)

    dec_map  = {"BUY": Decision.BUY, "SELL": Decision.SELL, "HOLD": Decision.HOLD}
    decision = dec_map.get(judge.get("decision", "HOLD").upper(), Decision.HOLD)

    verdict = DebateVerdict(
        decision=decision,
        confidence=float(judge.get("confidence", 50)),
        bull_score=float(judge.get("_bull_pct", 50)),
        bear_score=float(judge.get("_bear_pct", 50)),
        bull_argument=bull2.get("case", ""),
        bear_argument=bear2.get("case", ""),
        judge_reasoning=judge.get("reasoning", ""),
        winning_side=judge.get("winning_side", "tie"),
    )

    color = "green" if decision == Decision.BUY else "red" if decision == Decision.SELL else "yellow"
    console.print(f"[{color}]  Verdict: {decision.value} ({verdict.confidence:.0f}% confidence)[/{color}]")
    return verdict