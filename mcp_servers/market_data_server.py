"""
mcp_servers/market_data_server.py

Real MCP server — Yahoo Finance tools.
Runs as a subprocess; agents connect via MCPServerStdio.
Tools: get_stock_info, get_price_history
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types
import yfinance as yf

server = Server("market-data-server")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_stock_info",
            description="Fetch live stock fundamentals from Yahoo Finance: price, P/E, margins, growth, debt/equity, FCF, analyst target.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol e.g. AAPL"}
                },
                "required": ["ticker"]
            }
        ),
        types.Tool(
            name="get_price_history",
            description="Fetch historical price data and moving averages for a ticker.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "period": {"type": "string", "description": "1mo, 3mo, 6mo, 1y, 2y", "default": "6mo"}
                },
                "required": ["ticker"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_stock_info":
        result = await _get_stock_info(arguments["ticker"])
    elif name == "get_price_history":
        result = await _get_price_history(arguments["ticker"], arguments.get("period", "6mo"))
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


async def _get_stock_info(ticker: str) -> dict:
    def _fetch():
        stock = yf.Ticker(ticker)
        info  = stock.info
        return {
            "ticker":            ticker.upper(),
            "company_name":      info.get("longName", ticker),
            "sector":            info.get("sector", "N/A"),
            "current_price":     info.get("currentPrice") or info.get("regularMarketPrice"),
            "pe_ratio":          info.get("trailingPE"),
            "forward_pe":        info.get("forwardPE"),
            "eps":               info.get("trailingEps"),
            "revenue_growth":    info.get("revenueGrowth"),
            "gross_margins":     info.get("grossMargins"),
            "operating_margins": info.get("operatingMargins"),
            "debt_to_equity":    info.get("debtToEquity"),
            "free_cashflow":     info.get("freeCashflow"),
            "market_cap":        info.get("marketCap"),
            "beta":              info.get("beta"),
            "52w_high":          info.get("fiftyTwoWeekHigh"),
            "52w_low":           info.get("fiftyTwoWeekLow"),
            "analyst_target":    info.get("targetMeanPrice"),
            "recommendation":    info.get("recommendationKey"),
        }
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def _get_price_history(ticker: str, period: str) -> dict:
    def _fetch():
        hist   = yf.Ticker(ticker).history(period=period)
        if hist.empty:
            return {"error": "no price data", "ticker": ticker}
        closes = hist["Close"].tolist()
        ma50   = hist["Close"].rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
        ma200  = hist["Close"].rolling(200).mean().iloc[-1] if len(closes) >= 200 else None
        return {
            "ticker":           ticker.upper(),
            "period":           period,
            "latest_close":     round(closes[-1], 2),
            "period_high":      round(max(closes), 2),
            "period_low":       round(min(closes), 2),
            "price_change_pct": round(((closes[-1] - closes[0]) / closes[0]) * 100, 2),
            "ma_50":            round(float(ma50), 2) if ma50 else None,
            "ma_200":           round(float(ma200), 2) if ma200 else None,
        }
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
