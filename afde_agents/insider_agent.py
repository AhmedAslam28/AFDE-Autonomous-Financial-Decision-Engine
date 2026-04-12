"""agents/insider_agent.py — Insider Trading Agent"""
from __future__ import annotations
import json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import Agent, Runner
from config import OPENAI_API_KEY, OPENAI_MODEL, INSIDER_PROMPT, AgentSignal, DocumentContext
from mcp_servers.server_registry import get_servers_for_agent


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if "```" in raw:
        for p in raw.split("```"):
            p = p.strip().lstrip("json").strip()
            if p.startswith("{"):
                try: return json.loads(p)
                except: pass
    try: return json.loads(raw)
    except: pass
    m = re.search(r'\{.*?"score".*?\}', raw, re.DOTALL)
    return json.loads(m.group()) if m else {}


async def run_insider_agent(
    ticker: str,
    extra_context: str = "",
    doc_context: DocumentContext | None = None,
) -> AgentSignal:
    user_message = f"""Analyse insider trading for: {ticker.upper()}
Call get_insider_transactions twice: once with days_back=30, once with days_back=90.
{extra_context}
Return JSON only: {{"score": 0-100, "confidence": 0-100, "summary": "...", "data_points": [...], "source": "live"}}
If cluster buy detected (3+ filings in 30 days), score must be above 75."""

    servers = []
    try:
        for srv in get_servers_for_agent("insider"):
            await srv.__aenter__()
            servers.append(srv)
        agent = Agent(name="Insider Agent", instructions=INSIDER_PROMPT,
                      model=OPENAI_MODEL, mcp_servers=servers)
        result = await Runner.run(agent, input=user_message, max_turns=4)
        raw = str(result.final_output) if result.final_output else "{}"
    except Exception as e:
        return AgentSignal(agent="insider", score=50.0, confidence=5.0,
                           summary=f"Insider agent failed: {e}", data_points=[], source="error")
    finally:
        for srv in servers:
            try: await srv.__aexit__(None, None, None)
            except: pass

    out = _parse_json(raw)
    confidence = float(out.get("confidence", 50))
    if any("cluster" in dp.lower() for dp in out.get("data_points", [])):
        confidence = min(confidence + 20, 95)

    return AgentSignal(
        agent="insider",
        score=float(out.get("score", 50)),
        confidence=confidence,
        summary=out.get("summary", "Insider analysis completed."),
        data_points=out.get("data_points", []),
        source="live",
    )