"""
agents/fundamental_agent.py — Fundamental Analysis Agent
Uses correct MCPServerStdio pattern: async with server, then pass to Agent.
"""
from __future__ import annotations
import json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import Agent, Runner
from agents.mcp import MCPServerStdio
from config import OPENAI_API_KEY, OPENAI_MODEL, FUNDAMENTAL_PROMPT, AgentSignal, DocumentContext
from mcp_servers.server_registry import get_servers_for_agent


def _parse_json_output(raw: str) -> dict:
    raw = raw.strip()
    if "```" in raw:
        parts = raw.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                try: return json.loads(p)
                except: pass
    try: return json.loads(raw)
    except: pass
    m = re.search(r'\{.*?"score".*?\}', raw, re.DOTALL)
    if m:
        try: return json.loads(m.group())
        except: pass
    return {}


async def run_fundamental_agent(
    ticker: str,
    extra_context: str = "",
    doc_context: DocumentContext | None = None,
) -> AgentSignal:
    has_doc = doc_context is not None
    doc_section = ""
    if has_doc and doc_context:
        fin = doc_context.financials
        doc_section = f"""
=== DOCUMENT SOURCE (PRIMARY) ===
File: {doc_context.filename} ({doc_context.doc_type.value})
Extraction confidence: {doc_context.extraction_confidence:.0%}
Revenue: {fin.revenue if fin else 'N/A'}
Gross margin: {fin.gross_margin if fin else 'N/A'}
Operating margin: {fin.operating_margin if fin else 'N/A'}
EPS: {fin.eps if fin else 'N/A'}
Key facts: {'; '.join(doc_context.key_facts[:4]) if doc_context.key_facts else 'N/A'}
Raw text snippet: {doc_context.raw_text[:1500] if doc_context.raw_text else 'N/A'}
INSTRUCTION: Use document figures as primary. Use live tools only to fill gaps.
"""

    user_message = f"""Analyse fundamentals for: {ticker.upper()}
{doc_section}
Use get_stock_info and get_price_history tools for live data.
{extra_context}
Return JSON only: {{"score": 0-100, "confidence": 0-100, "summary": "...", "data_points": [...], "source": "live|document|mixed"}}"""

    server_factories = get_servers_for_agent("fundamental", has_document=has_doc)

    try:
        # Connect all MCP servers, then run agent
        servers = []
        for factory_result in server_factories:
            await factory_result.__aenter__()
            servers.append(factory_result)

        agent = Agent(
            name="Fundamental Agent",
            instructions=FUNDAMENTAL_PROMPT,
            model=OPENAI_MODEL,
            mcp_servers=servers,
        )
        result = await Runner.run(agent, input=user_message, max_turns=5)
        raw_text = str(result.final_output) if result.final_output else "{}"
    except Exception as e:
        return AgentSignal(agent="fundamental", score=50.0, confidence=5.0,
                           summary=f"Fundamental agent failed: {e}", data_points=[], source="error")
    finally:
        for srv in servers:
            try: await srv.__aexit__(None, None, None)
            except: pass

    out = _parse_json_output(raw_text)
    return AgentSignal(
        agent="fundamental",
        score=float(out.get("score", 50)),
        confidence=float(out.get("confidence", 50)),
        summary=out.get("summary", "Fundamental analysis completed."),
        data_points=out.get("data_points", []),
        source=out.get("source", "document" if has_doc else "live"),
    )