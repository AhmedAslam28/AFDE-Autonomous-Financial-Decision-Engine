"""agents/macro_agent.py — Macro Economic Agent"""
from __future__ import annotations
import json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import Agent, Runner
from config import OPENAI_API_KEY, OPENAI_MODEL, MACRO_PROMPT, AgentSignal, DocumentContext
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


async def run_macro_agent(
    ticker: str,
    extra_context: str = "",
    doc_context: DocumentContext | None = None,
) -> AgentSignal:
    sector_hint = ""
    if doc_context and doc_context.raw_text:
        t = doc_context.raw_text.lower()
        if any(k in t for k in ["semiconductor","chip","gpu"]): sector_hint = "Tech/Semiconductors"
        elif any(k in t for k in ["pharma","biotech","drug"]):  sector_hint = "Healthcare/Biotech"
        elif any(k in t for k in ["bank","lending","credit"]):  sector_hint = "Financial Services"

    user_message = f"""Assess macro environment for: {ticker.upper()}
{f'Sector hint: {sector_hint}' if sector_hint else ''}
Use ALL three tools: get_yield_curve, get_fed_rate, get_vix.
{extra_context}
Return JSON only: {{"score": 0-100, "confidence": 0-100, "summary": "...", "data_points": [...], "source": "live"}}"""

    servers = []
    try:
        for srv in get_servers_for_agent("macro"):
            await srv.__aenter__()
            servers.append(srv)
        agent = Agent(name="Macro Agent", instructions=MACRO_PROMPT,
                      model=OPENAI_MODEL, mcp_servers=servers)
        result = await Runner.run(agent, input=user_message, max_turns=5)
        raw = str(result.final_output) if result.final_output else "{}"
    except Exception as e:
        return AgentSignal(agent="macro", score=50.0, confidence=5.0,
                           summary=f"Macro agent failed: {e}", data_points=[], source="error")
    finally:
        for srv in servers:
            try: await srv.__aexit__(None, None, None)
            except: pass

    out = _parse_json(raw)
    return AgentSignal(
        agent="macro",
        score=float(out.get("score", 50)),
        confidence=float(out.get("confidence", 60)),
        summary=out.get("summary", "Macro analysis completed."),
        data_points=out.get("data_points", []),
        source="live",
    )