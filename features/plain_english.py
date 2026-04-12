"""features/plain_english.py — Rewrite analysis in plain English for non-finance users."""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PLAIN_ENGLISH_PROMPT = """You are a plain English translator for financial analysis.
Rewrite technical financial analysis so a complete beginner can understand it.

RULES:
- No jargon. Replace every financial term with everyday language:
  P/E ratio → "how expensive the stock is compared to what it earns"
  Gross margin → "how much profit the company keeps from each sale before paying overhead"
  Debt/equity ratio → "how much debt the company has compared to what it actually owns"
  Yield curve → "whether short-term or long-term interest rates are higher"
  VIX → "a measure of how nervous investors are right now (higher = more fear)"
  Insider buying (Form 4) → "company executives buying their own stock with their personal money"
  Cluster buy → "several executives bought stock around the same time — a sign they're confident"
  Fed rate cut → "the central bank is making borrowing cheaper to stimulate the economy"
- Use analogies and real-world comparisons
- Short sentences — maximum 2 per idea
- Warm, friendly tone like explaining to a smart friend who doesn't know finance
- Keep the same BUY/HOLD/SELL conclusion — just explain WHY in plain terms

Return JSON:
{
  "verdict_plain": "<1 sentence: what to do and why, in plain English>",
  "reasoning_plain": {"<agent_name>": "<plain English explanation>"},
  "bull_case_plain": "<plain English bull case>",
  "bear_case_plain": "<plain English bear case>",
  "bottom_line": "<1-2 sentence bottom line for a complete beginner>"
}"""

async def simplify_analysis(result: dict) -> dict:
    from openai import AsyncOpenAI
    from config import OPENAI_API_KEY, OPENAI_MODEL
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    context = f"""Ticker: {result.get('ticker','?')}
Decision: {result.get('decision','?')} ({result.get('confidence',0)}% confidence)
Goal: {result.get('goal','')}
Agent summaries: {json.dumps(result.get('reasoning',{}), indent=2)}
Bull case: {result.get('bull_case','')}
Bear case: {result.get('bear_case','')}
Judge: {result.get('judge_reasoning','')}
Rewrite all of this in plain English for a beginner. Return JSON."""
    resp = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role":"system","content":PLAIN_ENGLISH_PROMPT},{"role":"user","content":context}],
        response_format={"type":"json_object"}, temperature=0.3)
    out = json.loads(resp.choices[0].message.content)
    return {"verdict_plain":out.get("verdict_plain",""),"reasoning_plain":out.get("reasoning_plain",{}),
            "bull_case_plain":out.get("bull_case_plain",""),"bear_case_plain":out.get("bear_case_plain",""),
            "bottom_line":out.get("bottom_line","")}
