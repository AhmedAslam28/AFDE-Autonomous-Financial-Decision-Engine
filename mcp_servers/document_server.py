"""
mcp_servers/document_server.py

Real MCP server — PDF and CSV document parsing.
This is the new capability that makes AFDE a document intelligence system.

Tools:
  parse_pdf        → extract text + financial tables from uploaded PDF
  parse_csv        → parse portfolio CSV into holdings list
  extract_financials → pull key financial figures from extracted PDF text
"""

import asyncio
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

server = Server("document-server")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="parse_pdf",
            description="Extract text and tables from an uploaded PDF file. Returns raw text and detected financial figures.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Absolute path to the uploaded PDF file"}
                },
                "required": ["filepath"]
            }
        ),
        types.Tool(
            name="parse_csv",
            description="Parse a portfolio CSV file. Expected columns: ticker, shares, cost_basis. Returns holdings list.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Absolute path to the uploaded CSV file"}
                },
                "required": ["filepath"]
            }
        ),
        types.Tool(
            name="extract_financials",
            description="Extract key financial metrics from raw PDF text. Looks for revenue, margins, EPS, debt ratios.",
            inputSchema={
                "type": "object",
                "properties": {
                    "raw_text": {"type": "string", "description": "Raw text extracted from a financial document"},
                    "ticker":   {"type": "string", "description": "Ticker hint to improve extraction accuracy", "default": ""}
                },
                "required": ["raw_text"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "parse_pdf":
        result = await _parse_pdf(arguments["filepath"])
    elif name == "parse_csv":
        result = await _parse_csv(arguments["filepath"])
    elif name == "extract_financials":
        result = _extract_financials(arguments["raw_text"], arguments.get("ticker", ""))
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


async def _parse_pdf(filepath: str) -> dict:
    """Extract text and tables from a PDF using pdfplumber."""
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}
    try:
        import pdfplumber
    except ImportError:
        return {"error": "pdfplumber not installed. Run: pip install pdfplumber"}

    def _extract():
        all_text   = []
        all_tables = []
        page_count = 0

        with pdfplumber.open(filepath) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages[:30]):   # cap at 30 pages
                text = page.extract_text()
                if text:
                    all_text.append(text.strip())
                tables = page.extract_tables()
                for table in (tables or []):
                    if table and len(table) > 1:
                        clean = [[str(cell).strip() if cell else "" for cell in row] for row in table]
                        all_tables.append({"page": i + 1, "rows": clean[:20]})

        full_text = "\n".join(all_text)

        # Detect document type from content
        text_lower = full_text.lower()
        if any(k in text_lower for k in ["annual report", "form 10-k", "10-k"]):
            doc_type = "annual_report"
        elif any(k in text_lower for k in ["quarterly report", "10-q", "form 10-q"]):
            doc_type = "earnings_report"
        elif any(k in text_lower for k in ["pitch deck", "investment opportunity", "series a", "seed round"]):
            doc_type = "pitch_deck"
        elif any(k in text_lower for k in ["federal open market", "fomc", "monetary policy"]):
            doc_type = "macro_report"
        else:
            doc_type = "unknown"

        # Detect ticker hint
        ticker_hint = None
        ticker_match = re.search(r'\b(AAPL|TSLA|MSFT|GOOGL|AMZN|NVDA|META|BRK|NFLX|AMD|INTC|CRM|ORCL|PYPL|UBER|LYFT|SNAP|TWTR|SQ|SHOP|SPOT|ZM|DOCU|RBLX|COIN|HOOD)\b', full_text)
        if ticker_match:
            ticker_hint = ticker_match.group(0)

        return {
            "filepath":    filepath,
            "filename":    os.path.basename(filepath),
            "page_count":  page_count,
            "doc_type":    doc_type,
            "ticker_hint": ticker_hint,
            "raw_text":    full_text[:8000],   # cap at 8k chars for LLM context
            "table_count": len(all_tables),
            "tables":      all_tables[:5],      # first 5 tables only
            "char_count":  len(full_text),
        }

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _extract)


async def _parse_csv(filepath: str) -> dict:
    """Parse a portfolio CSV. Accepts flexible column naming."""
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    def _extract():
        try:
            import csv
            holdings = []

            with open(filepath, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                headers = [h.lower().strip() for h in (reader.fieldnames or [])]

                # Map flexible column names
                ticker_col     = next((h for h in headers if h in ["ticker", "symbol", "stock", "name"]), None)
                shares_col     = next((h for h in headers if h in ["shares", "quantity", "qty", "units", "amount"]), None)
                cost_col       = next((h for h in headers if h in ["cost_basis", "cost", "price", "avg_price", "average_price", "purchase_price"]), None)

                if not ticker_col:
                    return {"error": "Could not find ticker/symbol column. Expected: ticker, symbol, or stock"}
                if not shares_col:
                    return {"error": "Could not find shares/quantity column. Expected: shares, quantity, or qty"}

                for row in reader:
                    try:
                        ticker     = str(row.get(ticker_col, "")).upper().strip()
                        shares_raw = str(row.get(shares_col, "0")).replace(",", "").strip()
                        shares     = float(shares_raw) if shares_raw else 0.0
                        cost_raw   = str(row.get(cost_col, "0")).replace(",", "").replace("$", "").strip() if cost_col else "0"
                        cost_basis = float(cost_raw) if cost_raw else 0.0

                        if ticker and shares > 0:
                            holdings.append({
                                "ticker":     ticker,
                                "shares":     shares,
                                "cost_basis": cost_basis,
                            })
                    except (ValueError, TypeError):
                        continue

            return {
                "filepath":      filepath,
                "filename":      os.path.basename(filepath),
                "holdings":      holdings,
                "holding_count": len(holdings),
                "tickers":       [h["ticker"] for h in holdings],
            }
        except Exception as e:
            return {"error": str(e)}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _extract)


def _extract_financials(raw_text: str, ticker: str = "") -> dict:
    """
    Extract key financial figures from raw PDF text using regex patterns.
    Looks for revenue, margins, EPS, debt ratios etc.
    """
    text = raw_text.replace(",", "")  # remove commas for number parsing

    def _find_number(patterns: list[str]) -> float | None:
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    val = float(match.group(1).replace("$", "").replace("%", "").strip())
                    return val
                except (ValueError, IndexError):
                    continue
        return None

    def _find_pct(patterns: list[str]) -> float | None:
        val = _find_number(patterns)
        if val and val > 1:
            return val / 100   # convert percentage to decimal
        return val

    revenue = _find_number([
        r"(?:total\s+)?(?:net\s+)?revenue[s]?\s*[\$:]\s*([\d.]+)\s*(?:billion|million|B|M)?",
        r"revenue[s]?\s+(?:of|was|were)\s+\$?([\d.]+)",
    ])

    gross_margin = _find_pct([
        r"gross\s+(?:profit\s+)?margin[s]?\s*:?\s*([\d.]+)\s*%",
        r"gross\s+margin[s]?\s+(?:of|was)\s+([\d.]+)\s*%",
    ])

    operating_margin = _find_pct([
        r"operating\s+(?:profit\s+)?margin[s]?\s*:?\s*([\d.]+)\s*%",
        r"operating\s+margin[s]?\s+(?:of|was)\s+([\d.]+)\s*%",
    ])

    eps = _find_number([
        r"(?:diluted\s+)?(?:earnings|loss)\s+per\s+share\s*:?\s*\$?([\d.]+)",
        r"EPS\s*:?\s*\$?([\d.]+)",
    ])

    net_income = _find_number([
        r"net\s+(?:income|earnings|profit)\s*[\$:]\s*([\d.]+)\s*(?:billion|million|B|M)?",
        r"net\s+income\s+(?:of|was|were)\s+\$?([\d.]+)",
    ])

    # Extract any mentioned ticker if not provided
    if not ticker:
        match = re.search(r'\bNASDAQ:\s*([A-Z]{2,5})\b|\bNYSE:\s*([A-Z]{2,5})\b', raw_text)
        if match:
            ticker = match.group(1) or match.group(2)

    # Find key facts — sentences with financial keywords
    sentences = re.split(r'[.!?]\s+', raw_text[:3000])
    key_facts = [
        s.strip() for s in sentences
        if any(kw in s.lower() for kw in
               ["revenue", "growth", "margin", "profit", "eps", "earnings", "debt", "cash", "guidance"])
        and 20 < len(s) < 200
    ][:8]

    extracted = {
        "ticker":           ticker.upper() if ticker else None,
        "revenue":          revenue,
        "gross_margin":     gross_margin,
        "operating_margin": operating_margin,
        "eps":              eps,
        "net_income":       net_income,
        "key_facts":        key_facts,
        "extraction_confidence": sum(1 for v in [revenue, gross_margin, operating_margin, eps] if v is not None) / 4,
    }
    return extracted


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
