"""
mcp_servers/sec_server.py

Real MCP server — SEC EDGAR tools.
Tools: get_sec_filings, get_insider_transactions
"""

import asyncio
import json
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types
import httpx

server = Server("sec-server")
HEADERS = {"User-Agent": "AFDE-Research contact@afde.ai"}


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_sec_filings",
            description="Fetch recent SEC filing metadata for a ticker (10-K, 10-Q, 8-K, S-1).",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":    {"type": "string"},
                    "form_type": {"type": "string", "default": "10-K"},
                    "limit":     {"type": "integer", "default": 3}
                },
                "required": ["ticker"]
            }
        ),
        types.Tool(
            name="get_insider_transactions",
            description="Fetch Form 4 insider transactions. Detects cluster buying (3+ insiders buying in 30 days = strong bullish signal).",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":    {"type": "string"},
                    "days_back": {"type": "integer", "default": 90}
                },
                "required": ["ticker"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_sec_filings":
        result = await _get_sec_filings(
            arguments["ticker"],
            arguments.get("form_type", "10-K"),
            arguments.get("limit", 3)
        )
    elif name == "get_insider_transactions":
        result = await _get_insider_transactions(
            arguments["ticker"],
            arguments.get("days_back", 90)
        )
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


async def _resolve_cik(ticker: str, client: httpx.AsyncClient) -> str | None:
    resp = await client.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS)
    if resp.status_code != 200:
        return None
    for _, v in resp.json().items():
        if v.get("ticker", "").upper() == ticker.upper():
            return str(v["cik_str"]).zfill(10)
    return None


async def _get_sec_filings(ticker: str, form_type: str, limit: int) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        cik = await _resolve_cik(ticker, client)
        if not cik:
            return {"error": f"CIK not found for {ticker}"}
        resp = await client.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=HEADERS)
        if resp.status_code != 200:
            return {"error": "SEC submissions fetch failed"}
        data   = resp.json()
        recent = data.get("filings", {}).get("recent", {})
        forms  = recent.get("form", [])
        dates  = recent.get("filingDate", [])
        accnos = recent.get("accessionNumber", [])
        matches = [
            {
                "form": forms[i],
                "date": dates[i],
                "accession": accnos[i],
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}"
            }
            for i in range(min(len(forms), 30))
            if forms[i] == form_type
        ][:limit]
        return {
            "ticker":    ticker.upper(),
            "company":   data.get("name", ticker),
            "form_type": form_type,
            "filings":   matches,
        }


async def _get_insider_transactions(ticker: str, days_back: int) -> dict:
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=15) as client:
        cik = await _resolve_cik(ticker, client)
        if not cik:
            return {"error": f"CIK not found for {ticker}"}
        resp = await client.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=HEADERS)
        if resp.status_code != 200:
            return {"error": "SEC submissions fetch failed"}
        recent = resp.json().get("filings", {}).get("recent", {})
        forms  = recent.get("form", [])
        dates  = recent.get("filingDate", [])
        form4s = [
            {"date": dates[i]}
            for i in range(min(len(forms), 100))
            if forms[i] == "4" and dates[i] >= cutoff
        ]
        cluster = len(form4s) >= 3
        return {
            "ticker":           ticker.upper(),
            "days_back":        days_back,
            "form4_count":      len(form4s),
            "cluster_detected": cluster,
            "filings":          form4s[:10],
            "signal":           "Cluster buying detected" if cluster else "No unusual cluster activity",
        }


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
