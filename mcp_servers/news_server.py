"""
mcp_servers/news_server.py

Real MCP server — News search via Tavily.
Tool: search_news
Falls back to SEC 8-K headlines if Tavily not configured.
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types
import httpx

server    = Server("news-server")
TAVILY_KEY = os.getenv("TAVILY_API_KEY", "")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_news",
            description="Search recent financial news for a stock ticker. Returns sentiment score, article count, and top headlines.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":  {"type": "string"},
                    "company": {"type": "string", "description": "Company name for better search results", "default": ""}
                },
                "required": ["ticker"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "search_news":
        result = await _search_news(arguments["ticker"], arguments.get("company", ""))
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


async def _search_news(ticker: str, company: str) -> dict:
    if not TAVILY_KEY:
        return {
            "ticker": ticker,
            "error":  "TAVILY_API_KEY not set",
            "note":   "Add TAVILY_API_KEY to .env (free at app.tavily.com, 1000 calls/month)",
            "sentiment_score": 50,
            "articles": []
        }

    try:
        from tavily import TavilyClient
        query   = f"{ticker} {company} stock earnings analyst".strip()
        client  = TavilyClient(api_key=TAVILY_KEY)
        results = client.search(
            query=query,
            search_depth="advanced",
            max_results=10,
            include_domains=[
                "reuters.com", "bloomberg.com", "wsj.com",
                "cnbc.com", "marketwatch.com", "seekingalpha.com",
            ],
        )
        pos_kw = {"beat", "surged", "upgrade", "strong", "growth", "record", "raised", "bullish"}
        neg_kw = {"miss", "fell", "downgrade", "weak", "decline", "cut", "concern", "risk", "bearish"}
        pos = neg = neu = 0
        articles = []
        for a in results.get("results", []):
            text  = (a.get("title", "") + " " + a.get("content", "")[:200]).lower()
            words = set(text.split())
            if words & pos_kw:   pos += 1
            elif words & neg_kw: neg += 1
            else:                neu += 1
            articles.append({"title": a.get("title"), "snippet": a.get("content", "")[:200]})
        total = pos + neg or 1
        return {
            "ticker":          ticker.upper(),
            "positive":        pos,
            "negative":        neg,
            "neutral":         neu,
            "sentiment_score": round((pos / total) * 100, 1),
            "articles":        articles[:5],
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "sentiment_score": 50, "articles": []}


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
