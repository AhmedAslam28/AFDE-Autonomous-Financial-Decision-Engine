"""
document_processor.py

Processes uploaded PDF and CSV files into DocumentContext objects.
Calls document_server tool functions directly (imported as Python module)
rather than via subprocess MCP protocol — simpler, faster, no IPC overhead.

The MCP servers are still real MCP servers used by the agents SDK at runtime.
Document parsing happens before agents start, so direct import is cleaner here.
"""
from __future__ import annotations
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    DocumentContext, DocumentType,
    ExtractedFinancials, PortfolioHolding,
)


async def process_pdf(filepath: str) -> DocumentContext:
    """Parse an uploaded PDF into a DocumentContext."""
    # Import document server functions directly
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mcp_servers'))
    from mcp_servers.document_server import _parse_pdf, _extract_financials

    parsed = await _parse_pdf(filepath)

    if "error" in parsed:
        return DocumentContext(
            doc_type=DocumentType.UNKNOWN,
            filename=os.path.basename(filepath),
            ticker_hint=None,
            raw_text="",
            extraction_confidence=0.0,
        )

    raw_text    = parsed.get("raw_text", "")
    ticker_hint = parsed.get("ticker_hint")
    doc_type_map = {
        "annual_report":   DocumentType.ANNUAL_REPORT,
        "earnings_report": DocumentType.EARNINGS_REPORT,
        "pitch_deck":      DocumentType.PITCH_DECK,
        "macro_report":    DocumentType.ANALYST_REPORT,
        "unknown":         DocumentType.UNKNOWN,
    }
    doc_type = doc_type_map.get(parsed.get("doc_type", "unknown"), DocumentType.UNKNOWN)

    financials_raw = {}
    if raw_text:
        financials_raw = _extract_financials(raw_text, ticker_hint or "")

    financials = ExtractedFinancials(
        revenue=financials_raw.get("revenue"),
        revenue_growth=financials_raw.get("revenue_growth"),
        gross_margin=financials_raw.get("gross_margin"),
        operating_margin=financials_raw.get("operating_margin"),
        eps=financials_raw.get("eps"),
        net_income=financials_raw.get("net_income"),
        raw_items=financials_raw,
    ) if financials_raw else None

    return DocumentContext(
        doc_type=doc_type,
        filename=os.path.basename(filepath),
        ticker_hint=ticker_hint or (financials_raw.get("ticker") if financials_raw else None),
        financials=financials,
        raw_text=raw_text,
        key_facts=financials_raw.get("key_facts", []) if financials_raw else [],
        extraction_confidence=financials_raw.get("extraction_confidence", 0.0) if financials_raw else 0.0,
    )


async def process_csv(filepath: str) -> DocumentContext:
    """Parse a portfolio CSV into a DocumentContext with holdings."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mcp_servers'))
    from mcp_servers.document_server import _parse_csv

    parsed = await _parse_csv(filepath)

    if "error" in parsed:
        return DocumentContext(
            doc_type=DocumentType.PORTFOLIO_CSV,
            filename=os.path.basename(filepath),
            ticker_hint=None,
            extraction_confidence=0.0,
        )

    holdings_raw = parsed.get("holdings", [])
    holdings = [
        PortfolioHolding(
            ticker=h["ticker"],
            shares=float(h.get("shares", 0)),
            cost_basis=float(h.get("cost_basis", 0)),
        )
        for h in holdings_raw
        if h.get("ticker")
    ]

    return DocumentContext(
        doc_type=DocumentType.PORTFOLIO_CSV,
        filename=os.path.basename(filepath),
        ticker_hint=holdings[0].ticker if holdings else None,
        holdings=holdings,
        extraction_confidence=1.0 if holdings else 0.0,
    )


async def process_uploaded_file(filepath: str) -> DocumentContext:
    """Detect file type and route to the right processor."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return await process_pdf(filepath)
    elif ext == ".csv":
        return await process_csv(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Supported: .pdf, .csv")