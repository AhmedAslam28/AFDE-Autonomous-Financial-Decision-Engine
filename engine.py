"""
engine.py — AFDE core pipeline with all features wired in.
Streaming / macro-regime / memory / audit trail / alerts
"""
from __future__ import annotations
import sys, os, json, asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import AsyncOpenAI
from rich.console import Console

from config import (
    OPENAI_API_KEY, OPENAI_MODEL,
    AnalysisMode, AgentSignal, DocumentContext,
    COMPARE_JUDGE_PROMPT, MACRO_ONLY_PROMPT, PORTFOLIO_PROMPT,
)
from afde_agents.orchestrator_agent import run_orchestrator
from debate.debate_engine            import run_debate_engine
from output.formatter                import build_final_decision, print_decision, to_json
from features.streaming    import (emit_stage, emit_agent, emit_signal,
                                   emit_verdict, emit_done, emit_error)
from features.macro_regime import apply_regime_adjustment, get_current_regime
from features.memory       import store_analysis_memory, get_memory_context
from features.audit        import build_audit_trail
from features.alerts       import register_alert
from features.backtest            import store_decision
from features.email_notifications import send_verdict_email

_llm    = AsyncOpenAI(api_key=OPENAI_API_KEY)
console = Console()


async def _run_compare(goal, signals, sid=""):
    t1, t2 = goal.tickers[0], goal.tickers[1]
    if sid: emit_stage(sid, "compare_judge", f"Comparing {t1} vs {t2}")

    def _sum(ticker):
        lines = [f"=== {ticker} ==="]
        for key, sig in signals.items():
            if key.startswith(f"{ticker}_"):
                agent = key[len(ticker)+1:]
                w = {"fundamental":"2x","insider":"3x","macro":"1.5x","sentiment":"1x"}.get(agent,"1x")
                lines.append(f"\n  [{agent.upper()} weight={w}]")
                lines.append(f"  Score: {sig.score:.0f}/100  Confidence: {sig.confidence:.0f}%")
                lines.append(f"  Summary: {sig.summary}")
                for dp in sig.data_points[:3]:
                    lines.append(f"    • {dp}")
        return "\n".join(lines)

    resp = await _llm.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": COMPARE_JUDGE_PROMPT},
            {"role": "user",   "content": (
                f"Goal: {goal.raw_goal}\n\n{_sum(t1)}\n\n{_sum(t2)}\n\n"
                f"IMPORTANT: Only declare a clear winner if one stock's weighted signals "
                f"are MEANINGFULLY stronger (>10 point advantage). If scores are close, "
                f"reflect that in your reasoning and set confidence below 70%.\n\nReturn JSON."
            )},
        ],
        response_format={"type": "json_object"}, temperature=0,
    )
    r    = json.loads(resp.choices[0].message.content)
    conf = float(r.get("confidence", 50))
    conf, regime_note = apply_regime_adjustment(r.get("winner_decision", "BUY"), conf)
    if sid: emit_verdict(sid, r.get("winner_decision","BUY"), conf, 0, 0)
    regime = get_current_regime()

    return {
        "mode": "compare", "goal": goal.raw_goal,
        "tickers_compared": [t1, t2],
        "winner": r.get("winner", t1), "loser": r.get("loser", t2),
        "winner_decision": r.get("winner_decision","BUY"),
        "loser_decision":  r.get("loser_decision","HOLD"),
        "confidence": conf, "regime_note": regime_note,
        "macro_regime": regime.get("regime"),
        "reasoning": r.get("reasoning",""),
        "winner_strengths": r.get("winner_strengths",[]),
        "loser_weaknesses": r.get("loser_weaknesses",[]),
        f"{t1}_analysis": {k[len(t1)+1:]: v.summary for k,v in signals.items() if k.startswith(f"{t1}_")},
        f"{t2}_analysis": {k[len(t2)+1:]: v.summary for k,v in signals.items() if k.startswith(f"{t2}_")},
        "timestamp": datetime.now().isoformat(),
        "disclaimer": "AI-generated analysis only. Not financial advice.",
    }


async def _run_macro(goal, signals, sid=""):
    if sid: emit_stage(sid, "macro_report", "Building macro report")
    summaries = "\n".join(f"{n}: score={s.score:.0f}\n  {s.summary}" for n,s in signals.items())
    data_pts  = [dp for sig in signals.values() for dp in sig.data_points]
    resp = await _llm.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": MACRO_ONLY_PROMPT},
            {"role": "user",   "content": f"Goal: {goal.raw_goal}\n\n{summaries}\n\n" +
             "\n".join(f"• {dp}" for dp in data_pts[:10]) + "\n\nReturn JSON."},
        ],
        response_format={"type": "json_object"}, temperature=0.1,
    )
    r = json.loads(resp.choices[0].message.content)
    if sid: emit_signal(sid, "Market stance", r.get("overall_stance","NEUTRAL"), r.get("overall_stance")=="BULLISH")
    return {
        "mode": "macro", "goal": goal.raw_goal,
        "overall_stance": r.get("overall_stance","NEUTRAL"),
        "confidence": r.get("confidence",50), "summary": r.get("summary",""),
        "key_signals": r.get("key_signals",[]),
        "equity_implication": r.get("equity_implication",""),
        "sectors_favoured": r.get("sectors_favoured",[]),
        "sectors_avoid": r.get("sectors_avoid",[]),
        "raw_signals": {n: s.summary for n,s in signals.items()},
        "timestamp": datetime.now().isoformat(),
        "disclaimer": "AI-generated analysis only. Not financial advice.",
    }


async def _run_portfolio(goal, signals, sid=""):
    if sid: emit_stage(sid, "portfolio_risk", "Assessing portfolio risk")
    holdings = goal.doc_context.holdings if goal.doc_context else []
    ticker_summaries: dict[str, list] = {}
    for key, sig in signals.items():
        parts = key.split("_", 1)
        if len(parts) == 2:
            t, agent = parts
            ticker_summaries.setdefault(t, []).append(
                f"{agent}: score={sig.score:.0f} — {sig.summary[:80]}")

    holdings_text = "\n".join(
        f"  {h.ticker}: {h.shares} shares @ ${h.cost_basis:.2f} ({h.weight:.1%})"
        for h in holdings
    )
    analysis_text = "\n".join(
        f"\n{t}:\n" + "\n".join(f"  {s}" for s in sums)
        for t, sums in ticker_summaries.items()
    )
    resp = await _llm.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": PORTFOLIO_PROMPT},
            {"role": "user",   "content": f"Holdings:\n{holdings_text}\n\nAnalyses:\n{analysis_text}\n\nReturn JSON."},
        ],
        response_format={"type": "json_object"}, temperature=0.1,
    )
    r = json.loads(resp.choices[0].message.content)
    regime = get_current_regime()
    if sid: emit_done(sid, {"mode": "portfolio"})
    return {
        "mode": "portfolio", "goal": goal.raw_goal,
        "holdings_analysed": list(ticker_summaries.keys()),
        "overall_risk": r.get("overall_risk","MEDIUM"),
        "confidence": r.get("confidence",50),
        "summary": r.get("summary",""),
        "concentration_risk": r.get("concentration_risk",""),
        "recommendations": r.get("recommendations",[]),
        "rebalance_needed": r.get("rebalance_needed",False),
        "per_stock_analysis": ticker_summaries,
        "macro_regime": regime.get("regime"),
        "regime_note": f"Current macro regime: {regime.get('regime')}",
        "holdings": [{"ticker":h.ticker,"shares":h.shares,"cost_basis":h.cost_basis,"weight":h.weight} for h in holdings],
        "timestamp": datetime.now().isoformat(),
        "disclaimer": "AI-generated analysis only. Not financial advice.",
    }


async def run_afde(
    goal:        str,
    verbose:     bool = True,
    doc_context: DocumentContext | None = None,
    session_id:  str  = "",
    user_id:     int  = 0,
) -> dict:
    """
    Full AFDE pipeline — single entry point for all modes.
    Wires streaming, macro regime, memory, audit trail, and alerts.
    """
    sid = session_id
    try:
        if sid: emit_stage(sid, "parse", "Parsing goal and routing to agents")

        # Memory context is fetched INSIDE run_orchestrator after the ticker is parsed
        # We pass user_id so orchestrator can look up the right user's history
        goal_ctx, signals, loops, confidence = await run_orchestrator(
            goal, doc_context, user_id=user_id
        )

        # Stream agent results
        if sid:
            for name, sig in signals.items():
                if "_" not in name:
                    emit_agent(sid, name, "done", sig.score, sig.confidence, sig.summary)
                    for dp in sig.data_points[:2]:
                        emit_signal(sid, name, dp[:80], sig.score > 55)

        # Non-single modes
        if goal_ctx.mode == AnalysisMode.COMPARE:
            result = await _run_compare(goal_ctx, signals, sid)
            if sid: emit_done(sid, result)
            return result

        if goal_ctx.mode == AnalysisMode.MACRO:
            result = await _run_macro(goal_ctx, signals, sid)
            if sid: emit_done(sid, result)
            return result

        if goal_ctx.mode == AnalysisMode.PORTFOLIO:
            result = await _run_portfolio(goal_ctx, signals, sid)
            if sid: emit_done(sid, result)
            return result

        # SINGLE mode — debate
        if sid: emit_stage(sid, "debate", "Bull vs Bear debate")
        verdict = await run_debate_engine(goal_ctx.ticker, signals)
        if sid: emit_verdict(sid, verdict.decision.value, verdict.confidence,
                             verdict.bull_score, verdict.bear_score)

        final  = build_final_decision(goal_ctx, signals, verdict, loops, confidence)
        if verbose: print_decision(final)
        result = to_json(final)

        # Macro regime adjustment
        adj_conf, regime_note = apply_regime_adjustment(result["decision"], result["confidence"])
        result["confidence"]   = adj_conf
        result["regime_note"]  = regime_note
        result["macro_regime"] = get_current_regime().get("regime")

        # Memory storage
        store_analysis_memory(goal_ctx.ticker, signals, result["decision"], user_id)

        # Backtest: store price at decision for 30-day return tracking
        _price_for_bt = result.get("alert_price")
        if not _price_for_bt:
            import yfinance as _yf
            def _pb(t=goal_ctx.ticker):
                i = _yf.Ticker(t).info
                return i.get("currentPrice") or i.get("regularMarketPrice")
            try: _price_for_bt = await asyncio.get_event_loop().run_in_executor(None, _pb)
            except Exception: pass
        if _price_for_bt:
            store_decision(goal_ctx.ticker, result["decision"], result["confidence"], _price_for_bt, user_id)

        # Audit trail
        result["audit_trail"] = build_audit_trail(
            goal_ctx.ticker, signals, result["decision"], result["timestamp"],
            doc_filename=doc_context.filename if doc_context else None,
        )

        # Price alert
        if result["decision"] == "BUY":
            import yfinance as yf
            def _p(t=goal_ctx.ticker):
                info = yf.Ticker(t).info
                return info.get("currentPrice") or info.get("regularMarketPrice")
            try:
                price = await asyncio.get_event_loop().run_in_executor(None, _p)
                register_alert(goal_ctx.ticker, "BUY", price or 0, user_id)
                result["alert_registered"] = bool(price)
                result["alert_price"]      = price
            except Exception:
                result["alert_registered"] = False

        # Send verdict email — non-blocking background task
        if user_id:
            import asyncio as _aio, threading as _th
            def _send_ve():
                try:
                    _aio.run(send_verdict_email(result, user_id))
                except Exception:
                    pass
            _th.Thread(target=_send_ve, daemon=True).start()

        if sid: emit_done(sid, result)
        return result

    except Exception as e:
        if sid: emit_error(sid, str(e))
        raise