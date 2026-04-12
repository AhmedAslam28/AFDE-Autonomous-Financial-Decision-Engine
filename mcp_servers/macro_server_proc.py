"""
mcp_servers/macro_server_proc.py

Real MCP server — FRED + VIX macro data tools.
Tools: get_yield_curve, get_fed_rate, get_vix
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
import yfinance as yf

server   = Server("macro-server")
FRED_KEY = os.getenv("FRED_API_KEY", "")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_yield_curve",
            description="Fetch US Treasury yield curve (2Y, 10Y, 30Y) from FRED. Returns spreads and curve shape (normal/flat/inverted).",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_fed_rate",
            description="Fetch Federal Funds Rate and trajectory (hiking/cutting/pausing) from FRED.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_vix",
            description="Fetch VIX fear index from Yahoo Finance. Returns level and market fear interpretation.",
            inputSchema={"type": "object", "properties": {}}
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_yield_curve":
        result = await _get_yield_curve()
    elif name == "get_fed_rate":
        result = await _get_fed_rate()
    elif name == "get_vix":
        result = await _get_vix()
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


async def _get_yield_curve() -> dict:
    if not FRED_KEY:
        return {"error": "FRED_API_KEY not set", "note": "Add FRED_API_KEY to .env (free at fred.stlouisfed.org)"}
    series = {"2Y": "DGS2", "10Y": "DGS10", "30Y": "DGS30"}
    yields = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for label, sid in series.items():
            try:
                r = await client.get(
                    f"https://api.stlouisfed.org/fred/series/observations"
                    f"?series_id={sid}&api_key={FRED_KEY}&limit=1&sort_order=desc&file_type=json"
                )
                obs = r.json().get("observations", [])
                val = obs[-1]["value"] if obs else "."
                yields[label] = float(val) if val != "." else None
            except Exception:
                yields[label] = None
    spread = None
    if yields.get("10Y") and yields.get("2Y"):
        spread = round(yields["10Y"] - yields["2Y"], 3)
    shape = ("inverted" if spread is not None and spread < -0.1
             else "flat" if spread is not None and spread < 0.3
             else "normal")
    return {"yields": yields, "spread_2s10s": spread, "curve_shape": shape}


async def _get_fed_rate() -> dict:
    if not FRED_KEY:
        return {"error": "FRED_API_KEY not set"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=FEDFUNDS&api_key={FRED_KEY}&limit=6&sort_order=desc&file_type=json"
        )
        obs = [float(o["value"]) for o in r.json().get("observations", []) if o.get("value", ".") != "."]
    if len(obs) < 2:
        return {"error": "insufficient FRED data"}
    trajectory = "hiking" if obs[0] > obs[-1] else "cutting" if obs[0] < obs[-1] else "pausing"
    return {"current_rate": obs[0], "trajectory": trajectory, "recent": obs}


async def _get_vix() -> dict:
    def _fetch():
        vix   = yf.Ticker("^VIX")
        hist  = vix.history(period="1d")
        price = float(hist["Close"].iloc[-1]) if not hist.empty else None
        level = ("extreme_fear" if price and price > 30
                 else "elevated"  if price and price > 20
                 else "normal"    if price and price > 15
                 else "complacency")
        return {"vix": round(price, 2) if price else None, "level": level}
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
